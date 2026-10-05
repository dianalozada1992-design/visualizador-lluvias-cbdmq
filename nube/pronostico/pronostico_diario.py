"""Pronostico de lluvia por parroquia para el DMQ (hoy, manana y pasado manana).

1. Consulta en Open-Meteo los modelos que mejor acertaron en Quito (calibracion.json).
2. Corrige cada modelo por su sesgo y promedia (conjunto).
3. Convierte la lluvia pronosticada en probabilidad de dia de lluvia fuerte y de
   inundacion, segun como se comportaron los pronosticos en 2024-2026.
4. Suma la lluvia de los ultimos 7 dias medida por las estaciones CBDMQ (API) y sube
   un nivel la alerta si el suelo ya esta cargado (mas de 30 mm en la semana).
Salidas en pronostico\\boletines\\: boletin_AAAA-MM-DD.pdf y .xlsx
Correr con el Python de ArcGIS Pro.
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import datetime as dt
import numpy as np
import pandas as pd
try:
    import arcpy  # en la computadora; en GitHub se usa geo_pronostico.json
except ImportError:
    arcpy = None
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

CARPETA = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(CARPETA)
PARROQUIAS = r"D:\Documentos\shapes\barrio_sector_parroquia_totales\barrio_sector_parroquia.shp"
ZONAS = r"D:\Documentos\shapes\adm_zonaldmq_total\202508_Limites_Administraciones_Zonales\organizacion_territorial_zonal_a.shp"
PRIORIDAD = os.path.join(BASE, "analisis_completo", "Analisis_completo_DMQ.xlsx")
TOKEN_TXT = os.path.join(BASE, "Api.txt")
CBDMQ = {"Pifo": ("22143392", -0.219587, -78.339425), "Guamani": ("22143393", -0.340409, -78.564906),
         "El Placer": ("22143394", -0.212939, -78.519091), "El Tingo": ("22143395", -0.2895, -78.443019),
         "Guayllabamba": ("22143396", -0.064709, -78.358171), "San Antonio": ("22143397", -0.010878, -78.456786),
         "Metropolitano": ("22143398", -0.191083, -78.469266), "Checa": ("22351557", -0.127112, -78.312592)}
WGS = arcpy.SpatialReference(4326) if arcpy else None
GEO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "geo_pronostico.json")
NIVELES = ["Verde", "Amarillo", "Naranja", "Rojo"]
COLORES = {"Verde": "#58d68d", "Amarillo": "#f4d03f", "Naranja": "#e67e22", "Rojo": "#c0392b"}
# lluvia pronosticada corregida (mm en el dia) desde la que se asigna cada nivel; en 2024-2026 por zona:
# 5-10 mm -> 34 % de dias con aguacero fuerte, 10-20 mm -> 55 %, 20 mm o mas -> 60 % y 16 % con inundacion
CORTES_MM = (5, 10, 20)
NOMBRES = {"Bel_Quevedo": "Belisario Quevedo", "Ctro_Historico": "Centro Histórico", "Com_del Pueblo": "Comité del Pueblo",
           "San I_del Inca": "San Isidro del Inca", "Iniaquito": "Iñaquito", "Calderon": "Calderón", "Guamani": "Guamaní",
           "Itchimbia": "Itchimbía", "Concepcion": "Concepción", "Alangasi": "Alangasí", "Pintag": "Píntag", "Cumbaya": "Cumbayá",
           "Carcelen": "Carcelén", "Zambiza": "Zámbiza", "Puengasi": "Puengasí", "Yaruqui": "Yaruquí", "Ponceano": "Ponceano"}
DIAS = 3


def pedir(url, intentos=5, encabezados=None):
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, headers=encabezados or {})
            return json.load(urllib.request.urlopen(req, timeout=180))
        except Exception:
            time.sleep(15 * (i + 1))
    raise RuntimeError("Sin respuesta: " + url[:100])


def puntos_parroquias():
    """Un punto dentro de cada parroquia (centroide interior) con su administracion zonal."""
    if arcpy is None:  # sin ArcGIS: puntos guardados por exportar_geodatos.py
        df = pd.DataFrame(json.load(open(GEO, encoding="utf8"))["puntos"])
        return df.drop(columns=["brigada"]), "GEO"
    diss = arcpy.management.Dissolve(PARROQUIAS, "memory/parr", "PARROQUIA")[0]
    filas = []
    with arcpy.da.SearchCursor(diss, ["PARROQUIA", "SHAPE@"]) as c:
        for nombre, g in c:
            pp = arcpy.PointGeometry(g.labelPoint, g.spatialReference).projectAs(WGS).firstPoint
            filas.append({"parroquia": nombre, "lat": pp.Y, "lon": pp.X})
    df = pd.DataFrame(filas)
    df["nombre"] = df.parroquia.replace(NOMBRES)
    fc = arcpy.management.CreateFeatureclass("memory", "pp", "POINT", spatial_reference=WGS)[0]
    arcpy.management.AddField(fc, "idx", "LONG")
    with arcpy.da.InsertCursor(fc, ["SHAPE@XY", "idx"]) as cur:
        for i, r in df.iterrows():
            cur.insertRow([(r.lon, r.lat), i])
    j = arcpy.analysis.SpatialJoin(fc, ZONAS, "memory/ppz", match_option="INTERSECT")[0]
    zona = {i: z for i, z in arcpy.da.SearchCursor(j, ["idx", "adm_zonal"])}
    df["zona"] = [zona.get(i) for i in df.index]
    return df, diss


def pronostico_modelos(pts, calib):
    modelos = calib["conjunto"]["modelos"]
    salida = []
    for m in modelos:
        for i in range(0, len(pts), 25):
            g = pts.iloc[i:i + 25]
            q = urllib.parse.urlencode({"latitude": ",".join(f"{x:.4f}" for x in g.lat), "longitude": ",".join(f"{x:.4f}" for x in g.lon),
                                        "hourly": "precipitation", "models": m, "forecast_days": DIAS, "timezone": "America/Guayaquil"})
            d = pedir("https://api.open-meteo.com/v1/forecast?" + q)
            d = d if isinstance(d, list) else [d]
            for parr, r in zip(g.parroquia, d):
                h = r["hourly"]
                salida.append(pd.DataFrame({"parroquia": parr, "modelo": m, "hora": pd.to_datetime(h["time"]),
                                            "mm": h["precipitation"]}))
            time.sleep(1)
    f = pd.concat(salida, ignore_index=True).dropna(subset=["mm"])
    f["mm"] = f.mm * f.modelo.map({m: calib[m]["factor_sesgo"] for m in modelos})
    f["dia"] = f.hora.dt.normalize()
    return f


def lluvia_7_dias():
    """Lluvia medida en los ultimos 7 dias en cada estacion CBDMQ (API LI-COR)."""
    try:
        tok = os.environ.get("LICOR_TOKEN") or re.search(r"Token\s*:\s*(\S+)", open(TOKEN_TXT, encoding="utf8").read()).group(1)
    except Exception:
        return {}
    fin = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, minute=0, second=0, microsecond=0)
    ini = fin - dt.timedelta(days=7)
    out = {}
    for nombre, (sn, lat, lon) in CBDMQ.items():
        total = 0.0
        t = ini
        try:
            while t < fin:
                q = urllib.parse.urlencode({"loggers": sn, "start_date_time": t.strftime("%Y-%m-%d %H:%M:%S"),
                                            "end_date_time": min(t + dt.timedelta(days=2), fin).strftime("%Y-%m-%d %H:%M:%S")})
                d = pedir("https://api.licor.cloud/v1/data?" + q, encabezados={"Authorization": "Bearer " + tok})
                total += sum(x["value"] for x in d["data"] if x["sensor_measurement_type"] == "Rain")
                t += dt.timedelta(days=2)
            out[nombre] = (round(total, 1), lat, lon)
        except Exception:
            continue
    return out


def rango_prob(valor, tabla):
    """Busca la probabilidad historica para la lluvia pronosticada (rangos tipo '[5, 10)')."""
    for k, p in tabla.items():
        a, b = [float(x) for x in re.findall(r"[\d.]+", k)[:2]]
        if a <= valor < b:
            return p
    return None


def nivel(mm, previa):
    n = sum(mm >= c for c in CORTES_MM)
    if previa is not None and previa > 30 and n >= 1:
        n = min(n + 1, 3)
    return NIVELES[n]


def main():
    # --si-falta: no hace nada si el boletin de hoy ya existe (para la ejecucion al iniciar sesion)
    if "--si-falta" in sys.argv:
        hoy = dt.datetime.now().strftime("%Y-%m-%d")
        bol = os.path.join(CARPETA, "boletines")
        if os.path.isdir(bol) and any(f.startswith("pronostico_1_HOY_") and hoy in f for f in os.listdir(bol)):
            print("El boletín de hoy ya existe; no se vuelve a generar.")
            return
    calib = json.load(open(os.path.join(CARPETA, "calibracion.json"), encoding="utf8"))
    tab_fuerte = calib["conjunto"]["prob_dia_fuerte_por_rango"]
    tab_inund = calib["conjunto"].get("prob_inundacion_por_rango", {})
    zfuerte = calib["zona"]["prob_dia_fuerte_por_rango"]
    zinund = calib["zona"]["prob_inundacion_por_rango"]
    pts, diss = puntos_parroquias()
    print("Consultando modelos...", flush=True)
    f = pronostico_modelos(pts, calib)
    print("Lluvia de los ultimos 7 dias (CBDMQ)...", flush=True)
    previa = lluvia_7_dias()
    try:
        pr = pd.read_excel(PRIORIDAD, sheet_name="prioridad_parroquias").set_index("parroquia")["prioridad"]
    except Exception:
        pr = pd.Series(dtype=str)

    diaria = f.groupby(["parroquia", "dia", "modelo"]).agg(total=("mm", "sum"), max_h=("mm", "max")).reset_index()
    conj = diaria.groupby(["parroquia", "dia"]).agg(lluvia_mm=("total", "mean"), max_1h_mm=("max_h", "mean"),
                                                   minimo_modelos=("total", "min"), maximo_modelos=("total", "max")).reset_index()
    umbrales = {m: calib[m]["umbral_dia_fuerte_mm"] for m in calib["conjunto"]["modelos"]}
    acuerdo = diaria.assign(fuerte=[t >= umbrales[m] for t, m in zip(diaria.total, diaria.modelo)]).groupby(["parroquia", "dia"]).fuerte.sum()
    conj = conj.join(acuerdo.rename("modelos_que_anuncian_fuerte"), on=["parroquia", "dia"])
    conj = conj.merge(pts, on="parroquia")
    # lluvia previa: estacion CBDMQ mas cercana a menos de 12 km
    def cercana(r):
        mejor = None
        for nombre, (tot, la, lo) in previa.items():
            dkm = 111 * np.hypot(r.lat - la, r.lon - lo)
            if dkm <= 12 and (mejor is None or dkm < mejor[0]):
                mejor = (dkm, tot, nombre)
        return mejor
    cer = conj.apply(cercana, axis=1)
    conj["lluvia_7_dias_mm"] = [c[1] if c else np.nan for c in cer]
    conj["estacion_7_dias"] = [c[2] if c else "" for c in cer]
    conj["prob_dia_fuerte_%"] = [rango_prob(v, tab_fuerte) for v in conj.lluvia_mm]
    conj["prob_inundacion_cerca_%"] = [rango_prob(v, tab_inund) for v in conj.lluvia_mm]
    conj["nivel"] = [nivel(m, a if pd.notna(a) else None) for m, a in zip(conj.lluvia_mm, conj.lluvia_7_dias_mm)]
    # resumen por administracion zonal (donde los modelos aciertan mejor)
    zona = conj.dropna(subset=["zona"]).groupby(["dia", "zona"]).agg(lluvia_mm=("lluvia_mm", "mean"), maxima_parroquia_mm=("lluvia_mm", "max"),
                                                                    lluvia_7_dias_mm=("lluvia_7_dias_mm", "max")).reset_index()
    zona["prob_aguacero_fuerte_en_la_zona_%"] = [rango_prob(v, zfuerte) for v in zona.lluvia_mm]
    zona["prob_inundacion_en_la_zona_%"] = [rango_prob(v, zinund) for v in zona.lluvia_mm]
    zona["nivel"] = [nivel(m, a if pd.notna(a) else None) for m, a in zip(zona.lluvia_mm, zona.lluvia_7_dias_mm)]
    zona = zona.round(1)
    conj["prioridad_historica"] = conj.parroquia.map(lambda p: pr.get(p, "")).fillna("")
    conj = conj.round({"lluvia_mm": 1, "max_1h_mm": 1, "minimo_modelos": 1, "maximo_modelos": 1})

    hoy = pd.Timestamp.now().normalize()
    os.makedirs(os.path.join(CARPETA, "boletines"), exist_ok=True)
    base = os.path.join(CARPETA, "boletines", f"boletin_{hoy:%Y-%m-%d}")
    # si el boletin del dia esta abierto (Excel o lector de PDF) se guarda con la hora para no fallar
    for ext in (".pdf", ".xlsx", ".png"):
        if os.path.exists(base + ext):
            try:
                open(base + ext, "a").close()
            except PermissionError:
                base += f"_{dt.datetime.now():%H%M}"
                break
    conj["parroquia"] = conj.parroquia.replace(NOMBRES)
    cols = ["dia", "parroquia", "zona", "nivel", "lluvia_mm", "max_1h_mm", "minimo_modelos", "maximo_modelos",
            "modelos_que_anuncian_fuerte", "prob_dia_fuerte_%", "prob_inundacion_cerca_%", "lluvia_7_dias_mm",
            "estacion_7_dias", "prioridad_historica"]
    orden = {n: i for i, n in enumerate(NIVELES)}
    conj["_o"] = conj.nivel.map(orden)
    tabla = conj.sort_values(["dia", "_o", "lluvia_mm"], ascending=[True, False, False])[cols]
    with pd.ExcelWriter(base + ".xlsx") as xw:
        pd.DataFrame({"Boletín de pronóstico de lluvia - CBDMQ": [
            f"Emitido: {dt.datetime.now():%Y-%m-%d %H:%M}",
            "Elaborado por: Diana Lozada Ramos",
            f"Modelos: {', '.join(calib[m]['nombre'] for m in calib['conjunto']['modelos'])}, corregidos con las estaciones del DMQ (2024-2026).",
            f"Nivel según la lluvia pronosticada corregida en el día: Verde < {CORTES_MM[0]} mm, Amarillo {CORTES_MM[0]}-{CORTES_MM[1]} mm, "
            f"Naranja {CORTES_MM[1]}-{CORTES_MM[2]} mm, Rojo ≥ {CORTES_MM[2]} mm. En 2024-2026, por zona, eso correspondió a 34 %, 55 % y 60 % "
            "de días con aguacero fuerte (≥10 mm en 1 h o ≥20 mm en el día) en alguna estación de la zona.",
            "Se sube un nivel si en los últimos 7 días llovieron más de 30 mm en la estación CBDMQ cercana (suelo cargado).",
            "Los modelos anticipan bien los días lluviosos en la ciudad, pero no el barrio exacto de un aguacero: "
            "confirmar con las estaciones en tiempo real (umbrales 10, 20 y 30 mm en una hora).",
        ]}).to_excel(xw, sheet_name="leer_primero", index=False)
        zona.sort_values(["dia", "lluvia_mm"], ascending=[True, False]).to_excel(xw, sheet_name="por_zona", index=False)
        for dia, g in tabla.groupby("dia"):
            g.drop(columns="dia").to_excel(xw, sheet_name=f"{dia:%d-%m}", index=False)
        f.pivot_table(index=["parroquia", "hora"], columns="modelo", values="mm").round(2).to_excel(xw, sheet_name="por_hora")

    # boletin PDF: mapa por dia y tabla de parroquias con mayor nivel
    nivel_de = {(r.parroquia, r.dia): r.nivel for r in conj.itertuples()}
    if diss == "GEO":
        geoms = [(n, partes) for n, partes, _ in json.load(open(GEO, encoding="utf8"))["parroquias"]]
    else:
        geoms = []
        with arcpy.da.SearchCursor(diss, ["PARROQUIA", "SHAPE@"], spatial_reference=WGS) as c:
            for nombre, g in c:
                geoms.append((nombre, [[(p.X, p.Y) for p in parte if p] for parte in g]))
    dias = sorted(conj.dia.unique())
    nombres_dia = ["Hoy", "Mañana", "Pasado mañana"]
    with PdfPages(base + ".pdf") as pdf:
        fig, axs = plt.subplots(1, len(dias), figsize=(16.5, 8.5))
        for ax, dia, nd in zip(np.atleast_1d(axs), dias, nombres_dia):
            for nombre, partes in geoms:
                col = COLORES.get(nivel_de.get((NOMBRES.get(nombre, nombre), dia)), "#ffffff")
                for pts_ in partes:
                    xs, ys = zip(*pts_)
                    ax.fill(xs, ys, color=col, lw=0); ax.plot(xs, ys, color="#5d6d7e", lw=0.3)
            ax.set_xlim(-78.65, -78.25); ax.set_ylim(-0.42, 0.02); ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])
            g = conj[conj.dia == dia]
            ax.set_title(f"{nd} {pd.Timestamp(dia):%d/%m}\nlluvia media {g.lluvia_mm.mean():.1f} mm, máxima {g.lluvia_mm.max():.1f} mm", fontsize=10)
        for n in NIVELES:
            np.atleast_1d(axs)[0].fill([], [], color=COLORES[n], label=n)
        np.atleast_1d(axs)[0].legend(fontsize=8, loc="lower left", title="Nivel")
        fig.suptitle(f"Pronóstico de lluvia por parroquia - DMQ   (emitido {dt.datetime.now():%d/%m/%Y %H:%M})", fontsize=13)
        fig.text(0.5, 0.02, f"Modelos {', '.join(calib[m]['nombre'] for m in calib['conjunto']['modelos'])} corregidos con estaciones CBDMQ, EPMAPS y REMMAQ. "
                 "Confirmar en tiempo real con las estaciones: 10 / 20 / 30 mm en una hora.  Elaborado por: Diana Lozada Ramos", ha="center", fontsize=8)
        pdf.savefig(fig); fig.savefig(base + ".png", dpi=150); plt.close(fig)

        fig, ax = plt.subplots(figsize=(11.7, 8.3)); ax.axis("off")
        zf = zona.sort_values(["dia", "lluvia_mm"], ascending=[True, False])
        filas_z = [[f"{pd.Timestamp(r.dia):%d/%m}", str(r.zona), r.nivel, f"{r.lluvia_mm:.1f}", f"{r.maxima_parroquia_mm:.1f}",
                    "" if pd.isna(r["prob_aguacero_fuerte_en_la_zona_%"]) else f"{r['prob_aguacero_fuerte_en_la_zona_%']:.0f}",
                    "" if pd.isna(r["prob_inundacion_en_la_zona_%"]) else f"{r['prob_inundacion_en_la_zona_%']:.0f}",
                    "" if pd.isna(r.lluvia_7_dias_mm) else f"{r.lluvia_7_dias_mm:.0f}"] for _, r in zf.iterrows()]
        tz = ax.table(cellText=filas_z, colLabels=["Día", "Administración\nzonal", "Nivel", "Lluvia media\n(mm)", "Parroquia más\nlluviosa (mm)",
                                                   "Prob. aguacero\nfuerte (%)", "Prob.\ninundación (%)", "Lluvia últimos\n7 días (mm)"],
                      loc="upper center", cellLoc="center")
        tz.auto_set_font_size(False); tz.set_fontsize(7.5); tz.scale(1, 1.25)
        for (i, j), cel in tz.get_celld().items():
            if i == 0:
                cel.set_facecolor("#1f4e79"); cel.set_text_props(color="w", weight="bold"); cel.set_height(cel.get_height() * 2)
            elif j == 2:
                cel.set_facecolor(COLORES.get(filas_z[i - 1][2], "w"))
        ax.set_title("Pronóstico por administración zonal", fontsize=12)
        pdf.savefig(fig); plt.close(fig)

        fig, ax = plt.subplots(figsize=(11.7, 8.3)); ax.axis("off")
        top = tabla[tabla.nivel != "Verde"].head(26)
        if top.empty:
            top = tabla.sort_values("lluvia_mm", ascending=False).head(20)
        filas = [[f"{pd.Timestamp(r.dia):%d/%m}", NOMBRES.get(r.parroquia, r.parroquia), str(r.zona or ""), r.nivel, f"{r.lluvia_mm:.1f}", f"{r.max_1h_mm:.1f}",
                  "" if pd.isna(r["prob_dia_fuerte_%"]) else f"{r['prob_dia_fuerte_%']:.0f}",
                  "" if pd.isna(r["prob_inundacion_cerca_%"]) else f"{r['prob_inundacion_cerca_%']:.0f}",
                  "" if pd.isna(r.lluvia_7_dias_mm) else f"{r.lluvia_7_dias_mm:.0f}", str(r.prioridad_historica)[4:]]
                 for _, r in top.iterrows()]
        t = ax.table(cellText=filas, colLabels=["Día", "Parroquia", "Adm. zonal", "Nivel", "Lluvia\n(mm)", "Máx. 1 h\n(mm)",
                                                 "Prob. día\nfuerte (%)", "Prob.\ninundación (%)", "Lluvia últimos\n7 días (mm)", "Prioridad\nhistórica"],
                     loc="upper center", cellLoc="center")
        t.auto_set_font_size(False); t.set_fontsize(7.5); t.scale(1, 1.35)
        for (i, j), cel in t.get_celld().items():
            if i == 0:
                cel.set_facecolor("#1f4e79"); cel.set_text_props(color="w", weight="bold"); cel.set_height(cel.get_height() * 2)
            elif j == 3:
                cel.set_facecolor(COLORES.get(filas[i - 1][3], "w"))
        ax.set_title("Parroquias con nivel amarillo o superior" if (tabla.nivel != "Verde").any() else "Sin alertas: parroquias con más lluvia pronosticada", fontsize=12)
        pdf.savefig(fig); plt.close(fig)

    print(zona.to_string(index=False))
    resumen = conj.groupby(["dia", "nivel"]).size().unstack(fill_value=0)
    print(resumen.to_string())
    print(tabla[tabla.nivel != "Verde"].head(15).to_string(index=False))
    print("Boletín:", base + ".pdf")
    # boletin visual por brigada distrital (una imagen por dia, estilo infografia)
    try:
        import boletin_visual as bv
        h = f.groupby(["parroquia", "hora"]).mm.mean().reset_index()
        txt = ", ".join(calib[m]["nombre"].split(" (")[0] for m in calib["conjunto"]["modelos"])
        print("Boletín visual:", bv.generar(h, pts, diss, previa, base, txt, NOMBRES))
    except Exception as e:
        print("No se pudo generar el boletín visual:", e)
    # boletin de lluvias y emergencias (PDF tipo EPMAPS), se envia junto con el pronostico
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(CARPETA), "boletin"))
        import boletin_diario
        boletin_diario.generar()
    except Exception as e:
        print("No se pudo generar el boletín de lluvias y emergencias:", e)
    # envio del boletin al grupo de Telegram
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(CARPETA), "alertas"))
        import enviar_pronostico
        print("Pronóstico enviado por Telegram a", len(enviar_pronostico.enviar()), "destino(s)")
    except Exception as e:
        print("No se pudo enviar el pronóstico por Telegram:", e)


if __name__ == "__main__":
    main()

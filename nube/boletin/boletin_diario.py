"""Boletin diario de lluvias y emergencias del CBDMQ (PDF), al estilo del boletin de EPMAPS.

Paginas:
  1. Portada y resumen en lenguaje simple
  2. Lluvia del mes hasta hoy por estacion comparada con lo normal a la misma fecha (y con el mes completo)
  3-5. Pronostico de hoy, manana y pasado manana por brigada distrital (imagenes de boletin_visual.py)
  6. Emergencias por lluvia en este mes en anios anteriores: por anio, causa, tipo de atencion, brigada y parroquia
  7. Emergencias del anio hasta el ultimo mes con datos, comparadas con anios anteriores (por tipo y causa)
  8. Lluvia y emergencias: cuantas emergencias hubo en dias con lluvias parecidas a las pronosticadas
  9. Imagen del satelite GOES (si esta disponible)
Se llama al final del pronostico diario (6h00). Necesita: normales_lluvia.json, emergencias.json, diario.js,
datos/capas.js y el Excel e imagenes del pronostico del dia.
"""
import datetime as dt
import glob
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

CARPETA = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(CARPETA)
SALIDA = os.path.join(CARPETA, "salidas")
CREDITO = "Elaborado por: Diana Lozada Ramos"
INICIO_NUMERACION = dt.date(2026, 10, 5)
AZUL, AZUL_MEDIO, VERDE, VERDE_CLARO, GRIS = "#1f3f73", "#2f86c8", "#2e8b6f", "#a8dcae", "#9aa7b4"
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
A4 = (8.27, 11.69)
plt.rcParams.update({"font.size": 8.5, "axes.spines.top": False, "axes.spines.right": False, "axes.titleweight": "bold",
                     "axes.titlesize": 10, "axes.titlecolor": AZUL})


def fmt(v, d=1):
    return f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def leer_js(ruta):
    return json.loads(open(ruta, encoding="utf8").read().split("=", 1)[1].rstrip(";\n"))


def reparar(s):
    return str(s).replace("Calder�n", "Calderón").replace("Manuela S�enz", "Manuela Sáenz")


# ---------------------------------------------------------------- datos
def lluvia_del_mes(hoy, capas):
    """Lluvia acumulada desde el dia 1 del mes hasta ahora: estaciones CBDMQ (LI-COR) y EPMAPS (telemetria)."""
    sys.path.insert(0, os.path.join(BASE, "visualizador"))
    import actualizar as act
    ini = dt.datetime(hoy.year, hoy.month, 1)
    ahora = dt.datetime.now()
    out = {}
    # EPMAPS: telemetria desde el dia 1
    try:
        tel = [e for e in capas["telemetria"] if "Hidro" not in e["tipo"]]
        datos = act.bajar_telemetria(tel, ini, ahora)
        for e in tel:
            for v in (datos.get(e["id"]) or {}).values():
                if v.get("var_nombre", "").lower().startswith("precip"):
                    s = act.serie(v)
                    s = s[s.index >= ini]
                    if len(s):
                        out[e["codigo"]] = {"nombre": e["nombre"], "red": "EPMAPS", "mm": round(float(s.sum()), 1)}
    except Exception as ex:
        print("Sin telemetria del mes:", str(ex)[:120])
    # CBDMQ: API LI-COR por tramos de 3 dias
    try:
        tok = os.environ.get("LICOR_TOKEN") or re.search(r"Token\s*:\s*(\S+)", open(os.path.join(BASE, "Api.txt"), encoding="utf8").read()).group(1)
        for nombre, sn in act.CBDMQ_SN.items():
            total, t = 0.0, ini + dt.timedelta(hours=5)  # hora de Quito -> UTC
            fin = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
            try:
                while t < fin:
                    q = urllib.parse.urlencode({"loggers": sn, "start_date_time": t.strftime("%Y-%m-%d %H:%M:%S"),
                                                "end_date_time": min(t + dt.timedelta(days=3), fin).strftime("%Y-%m-%d %H:%M:%S")})
                    for intento in range(4):
                        try:
                            d = json.load(urllib.request.urlopen(urllib.request.Request("https://api.licor.cloud/v1/data?" + q,
                                                                 headers={"Authorization": "Bearer " + tok}), timeout=120))
                            break
                        except Exception:
                            if intento == 3:
                                raise
                            import time
                            time.sleep(15 * (intento + 1))
                    total += sum(x["value"] for x in d["data"] if x["sensor_measurement_type"] == "Rain")
                    t += dt.timedelta(days=3)
                out["CBDMQ " + nombre] = {"nombre": "CBDMQ " + nombre, "red": "CBDMQ", "mm": round(total, 1), "estacion_cbdmq": nombre}
            except Exception:
                continue
    except Exception as ex:
        print("Sin datos CBDMQ del mes:", str(ex)[:120])
    return out


def emergencias():
    e = json.load(open(os.path.join(CARPETA, "emergencias.json"), encoding="utf8"))
    t = pd.DataFrame(e["filas"], columns=e["columnas"])
    t["fecha"] = pd.to_datetime(t.fecha)
    t["brigada"] = t.brigada.map(lambda b: reparar(b) if b else "Sin ubicación")
    return t, e


def pronostico_del_dia(hoy):
    """Lluvia pronosticada por parroquia para cada dia (Excel del boletin de pronostico)."""
    xl = sorted(glob.glob(os.path.join(BASE, "pronostico", "boletines", f"boletin_{hoy:%Y-%m-%d}*.xlsx")), key=os.path.getmtime)
    if not xl:
        return None
    libro = pd.ExcelFile(xl[-1])
    return {h: libro.parse(h) for h in libro.sheet_names if len(h) == 5 and h[2] == "-"}


# ---------------------------------------------------------------- paginas
def cabecera(fig, titulo, numero, hoy):
    fig.patches.append(plt.Rectangle((0, 0.955), 1, 0.045, transform=fig.transFigure, color=AZUL, zorder=0))
    fig.text(0.04, 0.977, "CBDMQ · Dirección de Gestión de Riesgos", color="white", fontsize=9, va="center", weight="bold")
    fig.text(0.96, 0.977, f"Boletín N° {numero} · {hoy.day} de {MESES[hoy.month - 1]} de {hoy.year}", color="white", fontsize=9, va="center", ha="right")
    fig.text(0.05, 0.925, titulo, fontsize=13, weight="bold", color=AZUL, va="center")
    fig.text(0.5, 0.012, CREDITO, ha="center", fontsize=7.5, color=GRIS)


def parrafos(fig, textos, y, x=0.06, ancho=95, tam=9.2, sep=0.012):
    import textwrap
    for t in textos:
        lineas = textwrap.wrap(t, ancho)
        for i, l in enumerate(lineas):
            fig.text(x, y, ("• " if i == 0 else "  ") + l, fontsize=tam, va="top", color="#1b2631")
            y -= 0.0185 * tam / 9.2
        y -= sep
    return y


def pagina_lluvia_mes(pdf, hoy, numero, mes, normales):
    fig = plt.figure(figsize=A4)
    cabecera(fig, f"4. Lluvia de {MESES[hoy.month - 1]} hasta hoy comparada con lo normal", numero, hoy)
    filas = []
    for clave, v in mes.items():
        cod = normales["cbdmq"].get(v.get("estacion_cbdmq"), {}).get("codigo") if v["red"] == "CBDMQ" else clave
        n = normales["estaciones"].get(cod, {}).get("meses", {}).get(str(hoy.month))
        if not n:
            continue
        # normal hasta ayer + la parte del dia de hoy que ya paso
        h = n["hasta_dia"]; d = min(hoy.day, 31)
        ayer = h[d - 2] if d >= 2 else 0.0
        normal_fecha = ayer + (h[d - 1] - ayer) * (hoy.hour + hoy.minute / 60) / 24
        filas.append({"nombre": v["nombre"], "codigo": clave, "red": v["red"], "mm": v["mm"], "normal_fecha": normal_fecha, "normal_mes": n["total"],
                      "ref": normales["cbdmq"].get(v.get("estacion_cbdmq"), {}).get("nombre_ref") if v["red"] == "CBDMQ" else None})
    if not filas:
        fig.text(0.5, 0.5, "No hay datos de lluvia del mes disponibles hoy.", ha="center")
        pdf.savefig(fig); plt.close(fig); return None
    t = pd.DataFrame(filas)
    repetidos = t.nombre.duplicated(keep=False)
    t.loc[repetidos, "nombre"] = t.nombre[repetidos] + " (" + t.codigo[repetidos] + ")"
    t = t.sort_values("nombre", ascending=False).reset_index(drop=True)
    ax = fig.add_axes([0.34, 0.09, 0.6, 0.79])
    y = np.arange(len(t))
    ax.barh(y + 0.2, t.normal_mes, height=0.38, color="#e3f4e6", edgecolor=VERDE_CLARO, label=f"Normal de {MESES[hoy.month - 1]} completo")
    ax.barh(y + 0.2, t.normal_fecha, height=0.38, color=VERDE_CLARO, label=f"Normal hasta el {hoy.day} de {MESES[hoy.month - 1]}")
    ax.barh(y - 0.2, t.mm, height=0.38, color=AZUL, label=f"Lluvia {hoy.year} hasta hoy")
    ax.set_yticks(y)
    ax.set_yticklabels([f"{r.nombre}" + (f" (ref. {r.ref})" if isinstance(r.ref, str) else "") for r in t.itertuples()], fontsize=6.6)
    for yy, r in zip(y, t.itertuples()):
        ax.text(r.mm + 1, yy - 0.2, fmt(r.mm, 0), va="center", fontsize=6, color=AZUL)
    ax.set_xlabel("Lluvia acumulada (mm)")
    ax.grid(axis="x", color="#e5e9ef"); ax.set_axisbelow(True)
    ax.legend(loc="lower right", fontsize=7, frameon=True)
    pct = 100 * t.mm.sum() / max(t.normal_fecha.sum(), 0.1)
    fig.text(0.06, 0.03, f"Normal: promedio de los años con datos completos (EPMAPS, {normales['anios'][0]}-{normales['anios'][1]}). Las estaciones CBDMQ se comparan\n"
             "con la estación EPMAPS más cercana (ref.). Al inicio del mes las diferencias con lo normal pueden ser grandes porque son pocos días.", fontsize=7, color=GRIS)
    pdf.savefig(fig); plt.close(fig)
    return {"t": t, "pct": pct}


def pagina_imagen(pdf, hoy, numero, titulo, ruta):
    fig = plt.figure(figsize=A4)
    cabecera(fig, titulo, numero, hoy)
    if ruta and os.path.exists(ruta):
        ax = fig.add_axes([0.04, 0.1, 0.92, 0.8]); ax.imshow(plt.imread(ruta)); ax.axis("off")
    else:
        fig.text(0.5, 0.5, "Imagen no disponible hoy.", ha="center")
    pdf.savefig(fig); plt.close(fig)


def barras_h(ax, serie, color, titulo, nota=None, maximo=10, nota_y=-0.16):
    s = serie.sort_values(ascending=True).tail(maximo)
    ax.barh(range(len(s)), s.values, color=color)
    ax.set_yticks(range(len(s))); ax.set_yticklabels([str(i)[:38] for i in s.index], fontsize=7)
    for i, v in enumerate(s.values):
        ax.text(v, i, f" {fmt(v, 0)}", va="center", fontsize=7)
    ax.set_title(titulo, loc="left")
    ax.grid(axis="x", color="#e5e9ef"); ax.set_axisbelow(True)
    if nota:
        ax.text(0, nota_y, nota, transform=ax.transAxes, fontsize=6.5, color=GRIS)


def pagina_emergencias_mes(pdf, hoy, numero, t):
    m = hoy.month
    del_mes = t[t.fecha.dt.month == m]
    anios = list(range(2018, hoy.year + (0 if hoy.month > t.fecha.max().month or hoy.year > t.fecha.max().year else 1)))
    por_anio = del_mes.groupby(del_mes.fecha.dt.year).size().reindex(anios, fill_value=0)
    fig = plt.figure(figsize=A4)
    cabecera(fig, f"6. Emergencias por lluvia en {MESES[m - 1]} de años anteriores", numero, hoy)
    ax = fig.add_axes([0.08, 0.68, 0.86, 0.2])
    ax.bar(por_anio.index.astype(str), por_anio.values, color=AZUL_MEDIO)
    prom = por_anio.mean()
    ax.axhline(prom, color=VERDE, ls="--", lw=1.2); ax.text(-0.45, prom, f"promedio {fmt(prom, 0)}", color=VERDE, va="bottom", ha="left", fontsize=7.5, weight="bold")
    for i, v in enumerate(por_anio.values):
        ax.text(i, v, str(v), ha="center", va="bottom", fontsize=7.5)
    ax.set_title(f"Emergencias atendidas en {MESES[m - 1]}, por año", loc="left")
    reciente = del_mes[del_mes.fecha.dt.year >= 2024]
    con_causa = reciente[reciente.causa != "Sin causa registrada"]
    barras_h(fig.add_axes([0.32, 0.44, 0.62, 0.16]), con_causa.causa.value_counts(), AZUL, f"Causas ({MESES[m - 1]} 2024 en adelante)",
             "La causa se registra de forma regular desde 2024.")
    barras_h(fig.add_axes([0.32, 0.3, 0.62, 0.07]), del_mes.tipo.value_counts(), VERDE, f"Tipo de atención ({MESES[m - 1]}, todos los años)",
             "Limpieza de obstáculos y rescates solo constan en las bases de ene-jun 2024 y ene-abr 2025.", nota_y=-0.75)
    barras_h(fig.add_axes([0.18, 0.05, 0.27, 0.17]), del_mes.brigada.value_counts(), AZUL_MEDIO, "Por brigada distrital", maximo=8)
    parr = del_mes.parroquia.dropna().map(reparar).value_counts().head(8)
    barras_h(fig.add_axes([0.66, 0.05, 0.28, 0.17]), parr, VERDE_CLARO, "Parroquias con más emergencias", maximo=8)
    pdf.savefig(fig); plt.close(fig)
    return {"por_anio": por_anio, "prom": prom, "causas": con_causa.causa.value_counts(), "brigadas": del_mes.brigada.value_counts()}


def pagina_emergencias_anio(pdf, hoy, numero, t, meta):
    ult = t.fecha.max()
    mes_ult = ult.month
    hasta = t[t.fecha.dt.month <= mes_ult]
    fig = plt.figure(figsize=A4)
    cabecera(fig, f"8. Emergencias de enero a {MESES[mes_ult - 1]}: comparación entre años", numero, hoy)
    ax = fig.add_axes([0.08, 0.62, 0.86, 0.26])
    tabla = hasta.groupby([hasta.fecha.dt.year, "tipo"]).size().unstack(fill_value=0)
    abajo = np.zeros(len(tabla))
    colores = [AZUL, VERDE, AZUL_MEDIO, VERDE_CLARO, GRIS]
    for i, c in enumerate(tabla.columns):
        ax.bar(tabla.index.astype(str), tabla[c].values, bottom=abajo, color=colores[i % len(colores)], label=c)
        abajo += tabla[c].values
    for i, v in enumerate(abajo):
        ax.text(i, v, str(int(v)), ha="center", va="bottom", fontsize=7.5)
    ax.legend(fontsize=7, loc="upper left")
    ax.set_title(f"Emergencias atendidas de enero a {MESES[mes_ult - 1]}, por año y tipo de atención", loc="left")
    ax.text(0, -0.13, "Limpieza de obstáculos y rescates solo constan en las bases de ene-jun 2024 y ene-abr 2025; en los demás años la base "
            "registra solo succión de agua.", transform=ax.transAxes, fontsize=6.5, color=GRIS)
    # causas por anio (desde 2024)
    ax2 = fig.add_axes([0.08, 0.3, 0.86, 0.24])
    rc = hasta[(hasta.fecha.dt.year >= 2024) & (hasta.causa != "Sin causa registrada")]
    tc = rc.groupby(["causa", rc.fecha.dt.year]).size().unstack(fill_value=0)
    tc = tc.loc[tc.sum(axis=1).sort_values(ascending=False).index[:7]]
    ancho = 0.8 / max(len(tc.columns), 1)
    for i, anio in enumerate(tc.columns):
        ax2.bar(np.arange(len(tc)) + i * ancho, tc[anio].values, width=ancho, color=[AZUL_MEDIO, VERDE, AZUL][i % 3], label=str(anio))
    ax2.set_xticks(np.arange(len(tc)) + ancho * (len(tc.columns) - 1) / 2)
    ax2.set_xticklabels([c.replace(" o ", "\no ").replace(" de ", "\nde ") for c in tc.index], fontsize=6.8)
    ax2.legend(fontsize=7); ax2.set_title(f"Causas de las emergencias, enero a {MESES[mes_ult - 1]} (desde 2024)", loc="left")
    # brigadas: anio actual vs promedio
    ax3 = fig.add_axes([0.3, 0.08, 0.64, 0.15])
    actual = hasta[hasta.fecha.dt.year == ult.year].brigada.value_counts()
    prev = hasta[hasta.fecha.dt.year < ult.year].groupby([hasta.fecha.dt.year, "brigada"]).size().unstack(fill_value=0).mean()
    idx = actual.add(prev, fill_value=0).sort_values().index[-8:]
    yy = np.arange(len(idx))
    ax3.barh(yy + 0.2, prev.reindex(idx, fill_value=0).values, height=0.38, color=VERDE_CLARO, label="Promedio de años anteriores")
    ax3.barh(yy - 0.2, actual.reindex(idx, fill_value=0).values, height=0.38, color=AZUL, label=str(ult.year))
    ax3.set_yticks(yy); ax3.set_yticklabels(idx, fontsize=7); ax3.legend(fontsize=7)
    ax3.set_title(f"Por brigada distrital: {ult.year} frente al promedio (enero a {MESES[mes_ult - 1]})", loc="left")
    fig.text(0.06, 0.03, f"Datos de emergencias disponibles hasta el {ult.day} de {MESES[ult.month - 1]} de {ult.year}. "
             "Se actualizan cuando se entrega una base nueva.", fontsize=7, color=GRIS)
    pdf.savefig(fig); plt.close(fig)
    return {"actual": int((hasta.fecha.dt.year == ult.year).sum()),
            "prom_prev": float(hasta[hasta.fecha.dt.year < ult.year].groupby(hasta.fecha.dt.year).size().mean()), "mes_ult": mes_ult, "anio": ult.year}


def dias_parecidos(t):
    """Emergencias por dia segun la lluvia media de las estaciones ese dia (2018 - ultimo dato)."""
    d = leer_js(os.path.join(CARPETA, "diario.js"))
    M = np.array([e["d"] for e in d["estaciones"]], dtype=float); M[M < 0] = np.nan
    fechas = pd.date_range(d["inicio"], periods=d["n_dias"], freq="D")
    media = pd.Series(np.nanmean(M, axis=0) / 10, index=fechas)
    n = t.groupby(t.fecha.dt.normalize()).size().reindex(fechas, fill_value=0)
    ok = media.notna() & (fechas <= t.fecha.max())
    cortes = [0, 1, 3, 6, 10, np.inf]
    etiquetas = ["menos de 1 mm", "1 a 3 mm", "3 a 6 mm", "6 a 10 mm", "más de 10 mm"]
    cat = pd.cut(media[ok], cortes, labels=etiquetas, right=False)
    res = pd.DataFrame({"dias": cat.value_counts().reindex(etiquetas),
                        "promedio": n[ok].groupby(cat).mean().reindex(etiquetas),
                        "con_emergencia": (n[ok] > 0).groupby(cat).mean().reindex(etiquetas)})
    return res, cortes, etiquetas


def pagina_lluvia_emergencias(pdf, hoy, numero, t, pron):
    res, cortes, etiquetas = dias_parecidos(t)
    fig = plt.figure(figsize=A4)
    cabecera(fig, "7. Lluvia y emergencias: ¿qué pasó en días parecidos?", numero, hoy)
    ax = fig.add_axes([0.1, 0.55, 0.82, 0.32])
    colores = ["#e3f4e6", VERDE_CLARO, "#5bbfa8", AZUL_MEDIO, AZUL]
    ax.bar(etiquetas, res.promedio.values, color=colores, edgecolor="#5d6d7e", lw=0.4)
    for i, (p, c, dd) in enumerate(zip(res.promedio, res.con_emergencia, res.dias)):
        ax.text(i, p, f"{fmt(p, 1)} por día\n{fmt(c * 10, 0)} de cada 10 días\ncon emergencias\n({int(dd)} días)", ha="center", va="bottom", fontsize=7)
    ax.set_ylabel("Emergencias por día (promedio)")
    ax.set_xlabel("Lluvia media del día en las estaciones del DMQ")
    ax.set_ylim(0, res.promedio.max() * 1.6)
    ax.set_title("Emergencias por lluvia según cuánto llovió en el día (2018 en adelante)", loc="left")
    textos = []
    previstos = []
    if pron:
        for k, (hoja, g) in enumerate(list(pron.items())[:3]):
            mm = float(g.lluvia_mm.mean())
            cat = etiquetas[np.searchsorted(cortes, mm, side="right") - 1]
            r = res.loc[cat]
            fecha = dt.datetime.strptime(f"{hoja}-{hoy.year}", "%d-%m-%Y")
            rot = ["Hoy", "Mañana", "Pasado mañana"][k]
            previstos.append((rot, fecha, mm, cat, r))
            textos.append(f"{rot} ({DIAS[fecha.weekday()]} {fecha.day}): se esperan en promedio {fmt(mm)} mm en el DMQ ({cat}). En días así hubo en promedio "
                          f"{fmt(r.promedio, 1)} emergencias por día y en {fmt(r.con_emergencia * 10, 0)} de cada 10 días hubo al menos una.")
    fig.text(0.06, 0.47, "Con el pronóstico de los próximos días:", fontsize=10, weight="bold", color=AZUL)
    parrafos(fig, textos or ["No hay pronóstico disponible hoy."], 0.44)
    fig.text(0.06, 0.06, "La lluvia media del día es el promedio de todas las estaciones con dato (CBDMQ, EPMAPS y REMMAQ). Un aguacero muy fuerte\n"
             "en un solo sector puede causar emergencias aunque el promedio del DMQ sea bajo.", fontsize=7, color=GRIS)
    pdf.savefig(fig); plt.close(fig)
    return previstos


def pagina_satelite(pdf, hoy, numero):
    img = None
    for url in ("https://cdn.star.nesdis.noaa.gov/GOES19/ABI/SECTOR/nsa/13/1800x1080.jpg",
                "https://cdn.star.nesdis.noaa.gov/GOES19/ABI/SECTOR/nsa/13/900x540.jpg"):
        try:
            img = plt.imread(io.BytesIO(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "cbdmq-boletin"}), timeout=60).read()), format="jpg")
            break
        except Exception:
            continue
    if img is None:
        return False
    fig = plt.figure(figsize=A4)
    cabecera(fig, "8. Imagen del satélite GOES (infrarrojo)", numero, hoy)
    h, w = img.shape[:2]
    ax = fig.add_axes([0.04, 0.12, 0.92, 0.32]); ax.imshow(img); ax.axis("off"); ax.set_title("Norte de Sudamérica", loc="left", fontsize=8)
    ax2 = fig.add_axes([0.1, 0.47, 0.8, 0.42]); ax2.imshow(img[int(h * 0.3):int(h * 0.85), int(w * 0.02):int(w * 0.42)]); ax2.axis("off")
    ax2.set_title("Acercamiento: Ecuador y Colombia", loc="left", fontsize=9)
    fig.text(0.06, 0.07, "Imagen más reciente del satélite GOES-19 (NOAA), canal infrarrojo, norte de Sudamérica. Las nubes más frías\n"
             "(colores más intensos) suelen ser las de tormenta. Ecuador está en el lado izquierdo de la imagen.", fontsize=8.5)
    pdf.savefig(fig); plt.close(fig)
    return True


def pct(v):
    return "—" if v is None else f"{fmt(100 * v, 0)} %"


def pagina_verificacion(pdf, hoy, numero):
    """Seccion 5: indicadores de desempeno del pronostico del dia anterior frente a la precipitacion observada."""
    import verificar_pronostico as vp
    ayer = (hoy - dt.timedelta(days=1)).date() if isinstance(hoy, dt.datetime) else hoy - dt.timedelta(days=1)
    v = vp.verificar(ayer)
    if not v:
        return None
    fig = plt.figure(figsize=A4)
    cabecera(fig, "5. Verificación del pronóstico del día anterior", numero, hoy)
    fig.text(0.05, 0.895, f"Evaluación del pronóstico de precipitación para el {DIAS[ayer.weekday()]} {ayer.day} de {MESES[ayer.month - 1]} "
             f"frente a lo registrado por {list(v['resultados'].values())[0]['ind']['estaciones']} estaciones (CBDMQ y EPMAPS).", fontsize=8.5)
    filas = [("Precipitación media pronosticada (mm)", lambda i: fmt(i["media_pron"])),
             ("Precipitación media observada (mm)", lambda i: fmt(i["media_obs"])),
             ("Sesgo de cantidad (pronosticado / observado)", lambda i: "—" if i["sesgo"] is None else fmt(i["sesgo"], 2)),
             ("Error medio absoluto (mm)", lambda i: fmt(i["EMA"])),
             ("Probabilidad de detección, POD (umbral 1 mm)", lambda i: pct(i["POD"])),
             ("Razón de falsas alarmas, FAR", lambda i: pct(i["FAR"])),
             ("Índice de éxito crítico, CSI", lambda i: pct(i["CSI"])),
             ("Acierto exacto de categoría de intensidad", lambda i: pct(i["acierto_cat"])),
             ("Acierto con tolerancia de una categoría", lambda i: pct(i["cerca_cat"])),
             ("Aciertos / falsas alarmas / no detectadas / secos correctos",
              lambda i: f"{i['aciertos']} / {i['falsas_alarmas']} / {i['no_detectadas']} / {i['correctos_secos']}")]
    columnas = list(v["resultados"].keys())
    celdas = [[n] + [f(v["resultados"][c]["ind"]) for c in columnas] for n, f in filas]
    celdas.append(["Hora del máximo: observada / pronosticada",
                   f"{v['hora_obs'] if v['hora_obs'] is not None else '—'}h00 / {v['hora_pron'] if v['hora_pron'] is not None else '—'}h00"] + [""] * (len(columnas) - 1))
    ax = fig.add_axes([0.05, 0.56, 0.9, 0.31]); ax.axis("off")
    tab = ax.table(cellText=celdas, colLabels=["Indicador"] + [f"Emitido {c}" for c in columnas], loc="upper center", cellLoc="center",
                   colWidths=[0.56] + [0.22] * len(columnas))
    tab.auto_set_font_size(False); tab.set_fontsize(7.8); tab.scale(1, 1.35)
    for (i, j), cel in tab.get_celld().items():
        if i == 0:
            cel.set_facecolor(AZUL); cel.set_text_props(color="white", weight="bold")
        elif j == 0:
            cel.set_text_props(ha="left"); cel._loc = "left"
        if i > 0 and i % 2 == 0:
            cel.set_facecolor("#f3f6fa")
    ax2 = fig.add_axes([0.03, 0.27, 0.94, 0.3]); ax2.imshow(plt.imread(v["png"])); ax2.axis("off")
    ind = (v["resultados"].get("mismo día") or list(v["resultados"].values())[0])["ind"]
    frases = []
    if ind["sesgo"] is not None:
        frases.append("El pronóstico " + ("sobreestimó" if ind["sesgo"] > 1.3 else ("subestimó" if ind["sesgo"] < 0.77 else "se aproximó a"))
                      + f" la cantidad de lluvia (en promedio anunció {fmt(ind['media_pron'])} mm y se registraron {fmt(ind['media_obs'])} mm).")
    if ind["POD"] is not None:
        frases.append(f"De las estaciones donde llovió (1 mm o más), el pronóstico había anunciado lluvia en el {pct(ind['POD'])}; "
                      f"de los sitios donde anunció lluvia, en el {pct(ind['FAR'])} no llegó a 1 mm.")
    if v["hora_obs"] is not None and v["hora_pron"] is not None:
        dif = abs(v["hora_obs"] - v["hora_pron"])
        frases.append(f"La hora de mayor lluvia {'coincidió' if dif <= 1 else 'se desfasó ' + str(dif) + ' horas'} "
                      f"(observada {v['hora_obs']}h00, pronosticada {v['hora_pron']}h00).")
    mo, mp = v["mayor_obs"], v["mayor_pron"]
    frases.append(f"La mayor lluvia se registró en {mo.estacion} ({reparar(mo.parroquia)}, {fmt(mo.medido_mm)} mm); "
                  f"el mayor valor pronosticado fue para {reparar(mp.parroquia)} ({fmt(mp.pronosticado_mm)} mm).")
    fig.text(0.06, 0.245, "Interpretación", fontsize=10, weight="bold", color=AZUL)
    parrafos(fig, frases, 0.22, tam=8.6, sep=0.006, ancho=110)
    fig.text(0.06, 0.035, "POD: proporción de estaciones con lluvia que el pronóstico anticipó. FAR: proporción de anuncios de lluvia que no se cumplieron. "
             "CSI: aciertos sobre\nel total de aciertos, falsas alarmas y no detectadas. Sesgo mayor que 1: el pronóstico exageró la cantidad. "
             "Categorías: <1, 1–5, 5–10, 10–20 y >20 mm.", fontsize=6.6, color=GRIS)
    pdf.savefig(fig); plt.close(fig)
    return f"Verificación del pronóstico de ayer: {' '.join(frases[:2])}"


def portada(pdf, hoy, numero, resumen):
    fig = plt.figure(figsize=A4)
    fig.patches.append(plt.Rectangle((0, 0.8), 1, 0.2, transform=fig.transFigure, color=AZUL, zorder=0))
    fig.text(0.06, 0.95, "Cuerpo de Bomberos del Distrito Metropolitano de Quito", color="white", fontsize=10)
    fig.text(0.06, 0.925, "Dirección de Gestión de Riesgos", color="#dbe7f5", fontsize=9)
    fig.text(0.06, 0.865, "Boletín de lluvias y emergencias", color="white", fontsize=22, weight="bold")
    fig.text(0.06, 0.825, f"Boletín N° {numero}  ·  {DIAS[hoy.weekday()]} {hoy.day} de {MESES[hoy.month - 1]} de {hoy.year}", color="white", fontsize=11)
    fig.text(0.06, 0.76, "Resumen", fontsize=14, weight="bold", color=AZUL)
    y = parrafos(fig, resumen, 0.73, tam=9.6, sep=0.014)
    fig.text(0.06, max(y - 0.02, 0.2), "Contenido", fontsize=12, weight="bold", color=AZUL)
    indice = ["1. Mapas de la lluvia pronosticada en el DMQ", "2. Pronóstico de lluvia por zona y periodo",
              "3. Pronóstico de hoy por brigada distrital", "4. Lluvia del mes comparada con lo normal",
              "5. Verificación del pronóstico del día anterior", "6. Emergencias de este mes en años anteriores",
              "7. Lluvia y emergencias en días parecidos", "8. Imagen del satélite GOES"]
    yy = max(y - 0.045, 0.17)
    for i in indice:
        fig.text(0.08, yy, i, fontsize=9); yy -= 0.022
    fig.text(0.06, 0.05, "Fuentes: estaciones CBDMQ (LI-COR) y EPMAPS (paraMH2O); modelos ICON, Météo-France y GFS corregidos con las estaciones\n"
             "del DMQ; base de emergencias del CBDMQ; satélite GOES (NOAA).", fontsize=7, color=GRIS)
    fig.text(0.5, 0.012, CREDITO, ha="center", fontsize=8, color=AZUL, weight="bold")
    pdf.savefig(fig); plt.close(fig)


# ---------------------------------------------------------------- principal
def generar(hoy=None):
    hoy = hoy or dt.datetime.now()
    numero = (hoy.date() - INICIO_NUMERACION).days + 1
    os.makedirs(SALIDA, exist_ok=True)
    capas = leer_js(os.path.join(BASE, "visualizador", "datos", "capas.js"))
    normales = json.load(open(os.path.join(CARPETA, "normales_lluvia.json"), encoding="utf8"))
    t, meta = emergencias()
    pron = pronostico_del_dia(hoy)
    mes = lluvia_del_mes(hoy, capas)
    pngs = sorted(glob.glob(os.path.join(BASE, "pronostico", "boletines", "pronostico_[123]_*.png")), key=os.path.getmtime)
    por_dia = {}
    for p in pngs:
        if os.path.getmtime(p) >= dt.datetime.combine(hoy.date(), dt.time()).timestamp():
            por_dia[os.path.basename(p)[11]] = p
    ruta = os.path.join(SALIDA, f"boletin_lluvias_emergencias_{hoy:%Y-%m-%d}.pdf")
    cuerpo = io.BytesIO()
    import secciones_epmaps as se
    textos_zonas, datos_zonas, texto_mapas = {}, {}, None
    r_an = None
    with PdfPages(cuerpo) as pdf:
        try:
            texto_mapas = se.pagina_mapas(pdf, hoy, numero, capas, MESES)
        except Exception as ex:
            print("Sin mapas de pronóstico:", str(ex)[:120])
        try:
            textos_zonas, datos_zonas = se.pagina_tabla_zonas(pdf, hoy, numero, se.estaciones(capas), MESES)
        except Exception as ex:
            print("Sin pronóstico por zona:", str(ex)[:120])
        pagina_imagen(pdf, hoy, numero, "3. Pronóstico de lluvia de hoy por brigada distrital", por_dia.get("1"))
        r_mes = pagina_lluvia_mes(pdf, hoy, numero, mes, normales)
        try:
            verif = pagina_verificacion(pdf, hoy, numero)
        except Exception as ex:
            verif = None
            print("Sin verificación del día anterior:", str(ex)[:120])
        r_em = pagina_emergencias_mes(pdf, hoy, numero, t)
        previstos = pagina_lluvia_emergencias(pdf, hoy, numero, t, pron)
        pagina_satelite(pdf, hoy, numero)
    # resumen (portada) con lo calculado
    resumen = []
    if r_mes:
        tm = r_mes["t"]; mas = tm.sort_values("mm").iloc[-1]
        estado = "más de lo normal" if r_mes["pct"] >= 115 else ("menos de lo normal" if r_mes["pct"] <= 85 else "cerca de lo normal")
        resumen.append(f"Lluvia del mes: hasta hoy ha llovido {estado} para esta fecha: las estaciones suman el {fmt(r_mes['pct'], 0)} % de lo normal "
                       f"a esta altura de {MESES[hoy.month - 1]}. La más lluviosa es {mas.nombre} con {fmt(mas.mm)} mm.")
    if previstos:
        hoy_p = previstos[0]
        g = list(pron.values())[0].sort_values("lluvia_mm", ascending=False).head(3)
        resumen.append(f"Pronóstico para hoy: lluvia media de {fmt(hoy_p[2])} mm en el DMQ; las parroquias con más lluvia esperada son "
                       + ", ".join(f"{reparar(r.parroquia)} ({fmt(r.lluvia_mm)} mm)" for r in g.itertuples()) + ".")
        resumen.append(f"En días con lluvias como las de hoy hubo en promedio {fmt(hoy_p[4].promedio, 1)} emergencias por día, y en "
                       f"{fmt(hoy_p[4].con_emergencia * 10, 0)} de cada 10 días hubo al menos una.")
    ciudad = {z: v for z, v in datos_zonas.items() if "Páramos" not in z}
    if ciudad:
        partes = [f"{z.replace(' de Quito', '').lower()} {fmt(v[0], 0)}–{fmt(v[1], 0)} mm" for z, v in ciudad.items()]
        z_max = max(ciudad.items(), key=lambda kv: kv[1][1])
        resumen.append("Lluvia esperada en los próximos 3 días: " + ", ".join(partes) +
                       f". El periodo con más lluvia sería {z_max[1][2]} del {z_max[1][3]:%d/%m}.")
    elif textos_zonas:
        resumen.append("No se espera lluvia importante en la ciudad en los próximos 3 días.")
    if verif:
        resumen.append(verif)
    if r_em:
        pa = r_em["por_anio"]; anio_max = int(pa.idxmax())
        causas = ", ".join(r_em["causas"].index[:3].str.lower()) if len(r_em["causas"]) else "sin causa registrada"
        resumen.append(f"Emergencias en {MESES[hoy.month - 1]}: en años anteriores hubo en promedio {fmt(r_em['prom'], 0)} emergencias por lluvia en este mes "
                       f"(la mayor cantidad fue {pa.max()} en {anio_max}). Las causas más comunes: {causas}. "
                       f"La brigada con más emergencias en este mes: {r_em['brigadas'].index[0]}.")
    if r_an:
        dif = 100 * (r_an["actual"] / r_an["prom_prev"] - 1) if r_an["prom_prev"] else 0
        resumen.append(f"En {r_an['anio']}, de enero a {MESES[r_an['mes_ult'] - 1]} se atendieron {r_an['actual']} emergencias por lluvia, "
                       f"{fmt(abs(dif), 0)} % {'más' if dif >= 0 else 'menos'} que el promedio de los años anteriores en el mismo período.")
    resumen.append(f"Los datos de emergencias llegan hasta el {meta['hasta'][8:]}/{meta['hasta'][5:7]}/{meta['hasta'][:4]}.")
    # se arma el PDF final: portada + paginas
    from matplotlib.backends.backend_pdf import PdfPages as PP
    with PP(ruta) as pdf:
        portada(pdf, hoy, numero, resumen)
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter()
    for r in (PdfReader(ruta), PdfReader(io.BytesIO(cuerpo.getvalue()))):
        for p in r.pages:
            w.add_page(p)
    with open(ruta + ".tmp", "wb") as f:
        w.write(f)
    os.replace(ruta + ".tmp", ruta)
    print("Boletín de lluvias y emergencias:", ruta)
    return ruta, resumen


if __name__ == "__main__":
    generar()

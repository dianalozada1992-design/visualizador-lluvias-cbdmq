"""Informe semanal de lluvias y emergencias del CBDMQ (PDF), cada lunes sobre la semana anterior (lunes a domingo).

Paginas:
  1. Lluvia de la semana por estacion comparada con lo normal
  2. Lluvia de cada dia en el DMQ y las intensidades mas altas de la semana
  3. Alertas enviadas por Telegram en la semana
  4. Verificacion semanal del pronostico (indicadores por dia y de la semana)
  5. Emergencias del anio: comparacion entre anios
  6. Red de estaciones y disponibilidad de datos en la semana
Uso: python informe_semanal.py [AAAA-MM-DD del lunes de la semana a evaluar]
"""
import datetime as dt
import io
import json
import os
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

CARPETA = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(CARPETA)
sys.path.insert(0, CARPETA)
import boletin_diario as bd  # noqa: E402
import verificar_pronostico as vp  # noqa: E402
import secciones_epmaps as se  # noqa: E402

A4 = bd.A4
AZUL, AZUL_MEDIO, VERDE, VERDE_CLARO, GRIS = bd.AZUL, bd.AZUL_MEDIO, bd.VERDE, bd.VERDE_CLARO, bd.GRIS
MESES, DIAS, fmt = bd.MESES, bd.DIAS, bd.fmt


def cabecera(fig, titulo, ini, fin):
    fig.patches.append(plt.Rectangle((0, 0.955), 1, 0.045, transform=fig.transFigure, color=AZUL, zorder=0))
    fig.text(0.04, 0.977, "CBDMQ · Dirección de Gestión de Riesgos", color="white", fontsize=9, va="center", weight="bold")
    fig.text(0.96, 0.977, f"Informe semanal · {ini:%d/%m} al {fin:%d/%m/%Y}", color="white", fontsize=9, va="center", ha="right")
    fig.text(0.05, 0.925, titulo, fontsize=13, weight="bold", color=AZUL, va="center")
    fig.text(0.5, 0.012, bd.CREDITO, ha="center", fontsize=7.5, color=GRIS)


def observaciones(ini, fin, capas):
    """Lluvia horaria de todas las estaciones (CBDMQ y EPMAPS) entre ini y fin."""
    obs = []
    dia = ini
    por_est = {}
    while dia <= fin:
        for o in vp.medido(dia, capas):
            r = por_est.setdefault(o["estacion"], {k: o[k] for k in ("estacion", "red", "lat", "lon")} | {"horaria": []})
            r["horaria"].append(o["horaria"])
        dia += dt.timedelta(days=1)
    for r in por_est.values():
        r["horaria"] = pd.concat(r["horaria"]).sort_index()
        obs.append(r)
    return obs


def generar(lunes=None):
    hoy = dt.date.today()
    ini = lunes or (hoy - dt.timedelta(days=hoy.weekday() + 7))   # lunes de la semana anterior
    fin = ini + dt.timedelta(days=6)
    dias = [ini + dt.timedelta(days=k) for k in range(7)]
    capas = bd.leer_js(os.path.join(BASE, "visualizador", "datos", "capas.js"))
    parr = [(f["properties"]["nombre"], f["properties"]["brigada"], f["geometry"]) for f in capas["parroquias"]["features"]]
    normales = json.load(open(os.path.join(CARPETA, "normales_lluvia.json"), encoding="utf8"))
    obs = observaciones(ini, fin, capas)
    for o in obs:
        p = next((p for p in parr if vp.dentro(o["lon"], o["lat"], p[2])), None)
        o["parroquia"] = bd.reparar(p[0]) if p else None
        d = o["horaria"].groupby(o["horaria"].index.date).sum()
        o["diaria"] = d.reindex(dias)
        o["semana"] = float(o["diaria"].sum()) if o["diaria"].notna().sum() >= 5 else None
        o["disponibilidad"] = float(o["horaria"].notna().sum() / (7 * 24))
    resumen = []
    os.makedirs(bd.SALIDA, exist_ok=True)
    ruta = os.path.join(bd.SALIDA, f"informe_semanal_{ini:%Y-%m-%d}.pdf")
    cuerpo = io.BytesIO()
    with PdfPages(cuerpo) as pdf:
        # ---------------------------------------------------------------- 1. lluvia de la semana vs normal
        filas = []
        for o in obs:
            if o["semana"] is None:
                continue
            cod = next((c for c, v in normales["estaciones"].items() if v["nombre"] == o["estacion"]), None)
            if o["red"] == "CBDMQ":
                cod = normales["cbdmq"].get(o["estacion"].replace("CBDMQ ", ""), {}).get("codigo")
            normal = None
            if cod in normales["estaciones"]:
                normal = 0.0
                for d in dias:
                    h = normales["estaciones"][cod]["meses"].get(str(d.month), {}).get("hasta_dia")
                    if h:
                        normal += h[d.day - 1] - (h[d.day - 2] if d.day >= 2 else 0)
            filas.append({"estacion": o["estacion"], "mm": o["semana"], "normal": normal})
        t = pd.DataFrame(filas).sort_values("estacion", ascending=False).reset_index(drop=True)
        fig = plt.figure(figsize=A4)
        cabecera(fig, "1. Lluvia de la semana comparada con lo normal", ini, fin)
        ax = fig.add_axes([0.32, 0.08, 0.62, 0.8])
        y = np.arange(len(t))
        ax.barh(y + 0.2, t.normal.fillna(0), 0.38, color=VERDE_CLARO, label="Normal para esta semana")
        ax.barh(y - 0.2, t.mm, 0.38, color=AZUL, label="Lluvia de la semana")
        ax.set_yticks(y); ax.set_yticklabels(t.estacion, fontsize=6.5)
        for yy, v in zip(y, t.mm):
            ax.text(v + 0.5, yy - 0.2, fmt(v, 0), va="center", fontsize=6)
        ax.set_xlabel("Lluvia (mm)"); ax.legend(loc="lower right", fontsize=7.5); ax.grid(axis="x", color="#e5e9ef"); ax.set_axisbelow(True)
        con_normal = t.dropna(subset=["normal"])
        pct = 100 * con_normal.mm.sum() / max(con_normal.normal.sum(), 0.1)
        mas = t.sort_values("mm").iloc[-1]
        resumen.append(f"Lluvia de la semana: las estaciones registraron el {fmt(pct, 0)} % de lo normal para estas fechas "
                       f"({'más' if pct >= 115 else ('menos' if pct <= 85 else 'cerca')} de lo normal). La más lluviosa fue {mas.estacion} con {fmt(mas.mm)} mm.")
        pdf.savefig(fig); plt.close(fig)

        # ---------------------------------------------------------------- 2. lluvia diaria e intensidades
        D = pd.DataFrame({o["estacion"]: o["diaria"] for o in obs if o["semana"] is not None})
        fig = plt.figure(figsize=A4)
        cabecera(fig, "2. Lluvia de cada día y las lluvias más intensas", ini, fin)
        ax = fig.add_axes([0.1, 0.6, 0.84, 0.27])
        x = np.arange(7)
        ax.bar(x - 0.2, D.mean(axis=1).values, 0.38, color=AZUL_MEDIO, label="Promedio de las estaciones")
        ax.bar(x + 0.2, D.max(axis=1).values, 0.38, color=AZUL, label="Estación con más lluvia")
        for i, (m, mx) in enumerate(zip(D.mean(axis=1), D.max(axis=1))):
            ax.text(i + 0.2, mx, f"{mx:.0f}", ha="center", va="bottom", fontsize=7.5)
        ax.set_xticks(x); ax.set_xticklabels([f"{DIAS[d.weekday()]}\n{d:%d/%m}" for d in dias], fontsize=8)
        ax.set_ylabel("Lluvia del día (mm)"); ax.legend(fontsize=8); ax.set_title("Lluvia de cada día en el DMQ", loc="left")
        intens = []
        for o in obs:
            h = o["horaria"]
            for ts, v in h[h >= 5].items():
                intens.append((v, ts, o["estacion"], o["parroquia"] or "fuera del DMQ"))
        intens = sorted(intens, reverse=True)[:12]
        ax2 = fig.add_axes([0.06, 0.12, 0.88, 0.38]); ax2.axis("off")
        if intens:
            tab = ax2.table(cellText=[[f"{DIAS[ts.weekday()]} {ts:%d/%m %H:00}", e, p, fmt(v)] for v, ts, e, p in intens],
                            colLabels=["Día y hora", "Estación", "Parroquia", "mm en 1 hora"], loc="upper center", cellLoc="center",
                            colWidths=[0.22, 0.32, 0.28, 0.16])
            tab.auto_set_font_size(False); tab.set_fontsize(8); tab.scale(1, 1.35)
            for (i, j), cel in tab.get_celld().items():
                if i == 0:
                    cel.set_facecolor(AZUL); cel.set_text_props(color="white", weight="bold")
            ax2.set_title("Lluvias más intensas de la semana (5 mm o más en una hora)", loc="left", color=AZUL, fontsize=10, weight="bold")
            v, ts, e, p = intens[0]
            resumen.append(f"La lluvia más intensa fue de {fmt(v)} mm en una hora en {e} ({p}), el {DIAS[ts.weekday()]} {ts:%d/%m} a las {ts:%H}h00.")
        else:
            ax2.text(0.5, 0.8, "No hubo lluvias de 5 mm o más en una hora durante la semana.", ha="center")
        dia_max = D.mean(axis=1).idxmax()
        resumen.append(f"El día más lluvioso fue el {DIAS[dia_max.weekday()]} {dia_max:%d/%m} (promedio de {fmt(D.mean(axis=1).max())} mm en las estaciones).")
        pdf.savefig(fig); plt.close(fig)

        # ---------------------------------------------------------------- 3. alertas enviadas
        hist = []
        ruta_hist = os.path.join(CARPETA, "historial_alertas.json")
        if os.path.exists(ruta_hist):
            hist = [h for h in json.load(open(ruta_hist, encoding="utf8")) if ini.isoformat() <= h["hora"][:10] <= fin.isoformat()]
        fig = plt.figure(figsize=A4)
        cabecera(fig, "3. Alertas enviadas por Telegram en la semana", ini, fin)
        nombres = {"alerta": "Lluvia fuerte o más", "crecida": "Río creciendo", "condiciones": "Puede llover en 2 horas", "aviso": "Está lloviendo"}
        if hist:
            H = pd.DataFrame(hist); H["dia"] = pd.to_datetime(H.hora).dt.date
            tabla = H.groupby(["dia", "tipo"]).size().unstack(fill_value=0).reindex(dias, fill_value=0)
            ax = fig.add_axes([0.1, 0.6, 0.84, 0.27]); abajo = np.zeros(7)
            for i, c in enumerate(tabla.columns):
                ax.bar(np.arange(7), tabla[c].values, bottom=abajo, color=[AZUL, VERDE, AZUL_MEDIO, VERDE_CLARO][i % 4], label=nombres.get(c, c))
                abajo += tabla[c].values
            ax.set_xticks(np.arange(7)); ax.set_xticklabels([f"{DIAS[d.weekday()]}\n{d:%d/%m}" for d in dias], fontsize=8)
            ax.legend(fontsize=8); ax.set_title("Situaciones avisadas por día", loc="left")
            top = H[H.tipo == "alerta"].sort_values("mm_1h", ascending=False).head(15)
            ax2 = fig.add_axes([0.06, 0.1, 0.88, 0.42]); ax2.axis("off")
            if len(top):
                tab = ax2.table(cellText=[[pd.Timestamp(r.hora).strftime("%d/%m %H:%M"), r.parroquia, f"nivel {r.nivel}", fmt(r.mm_1h)] for r in top.itertuples()],
                                colLabels=["Fecha y hora", "Parroquia", "Nivel", "mm en 1 hora"], loc="upper center", cellLoc="center")
                tab.auto_set_font_size(False); tab.set_fontsize(8); tab.scale(1, 1.3)
                for (i, j), cel in tab.get_celld().items():
                    if i == 0:
                        cel.set_facecolor(AZUL); cel.set_text_props(color="white", weight="bold")
                ax2.set_title("Alertas de lluvia fuerte enviadas", loc="left", color=AZUL, fontsize=10, weight="bold")
            resumen.append(f"Se enviaron {len(H)} avisos por Telegram en la semana: " +
                           ", ".join(f"{n} de «{nombres.get(k, k).lower()}»" for k, n in H.tipo.value_counts().items()) + ".")
        else:
            fig.text(0.5, 0.6, "No hay alertas registradas para esta semana.\n(El registro de alertas enviadas empezó el 07/10/2026.)", ha="center", fontsize=10)
        pdf.savefig(fig); plt.close(fig)

        # ---------------------------------------------------------------- 4. verificacion semanal
        filas, total_t = [], []
        for d in dias:
            pr, h, ruta_p = vp.pronostico(d, d)
            if pr is None:
                continue
            prono = {vp.simple(p): v for p, v in zip(pr.parroquia, pr.lluvia_mm)}
            tt = [{"medido_mm": o["diaria"].get(d), "pronosticado_mm": float(prono[vp.simple(o["parroquia"])])}
                  for o in obs if o["parroquia"] and vp.simple(o["parroquia"]) in prono and pd.notna(o["diaria"].get(d))]
            if not tt:
                continue
            tt = pd.DataFrame(tt)
            tt["cat_medida"] = tt.medido_mm.map(vp.categoria); tt["cat_pron"] = tt.pronosticado_mm.map(vp.categoria)
            ind = vp.indicadores(tt); total_t.append(tt)
            filas.append([f"{DIAS[d.weekday()]} {d:%d/%m}", fmt(ind["media_pron"]), fmt(ind["media_obs"]), "—" if ind["sesgo"] is None else fmt(ind["sesgo"], 2),
                          bd.pct(ind["POD"]), bd.pct(ind["FAR"]), bd.pct(ind["CSI"]), bd.pct(ind["cerca_cat"])])
        fig = plt.figure(figsize=A4)
        cabecera(fig, "4. Verificación semanal del pronóstico", ini, fin)
        if filas:
            T = pd.concat(total_t); ind = vp.indicadores(T)
            filas.append(["Semana", fmt(ind["media_pron"]), fmt(ind["media_obs"]), "—" if ind["sesgo"] is None else fmt(ind["sesgo"], 2),
                          bd.pct(ind["POD"]), bd.pct(ind["FAR"]), bd.pct(ind["CSI"]), bd.pct(ind["cerca_cat"])])
            ax = fig.add_axes([0.04, 0.5, 0.92, 0.38]); ax.axis("off")
            tab = ax.table(cellText=filas, colLabels=["Día", "Pronosticado\n(mm)", "Observado\n(mm)", "Sesgo", "POD", "FAR", "CSI", "Categoría\n±1"],
                           loc="upper center", cellLoc="center")
            tab.auto_set_font_size(False); tab.set_fontsize(8.5); tab.scale(1, 1.6)
            for (i, j), cel in tab.get_celld().items():
                if i == 0:
                    cel.set_facecolor(AZUL); cel.set_text_props(color="white", weight="bold")
                if i == len(filas):
                    cel.set_facecolor("#e9eff7"); cel.set_text_props(weight="bold")
            textos = [f"En la semana el pronóstico {'sobreestimó' if (ind['sesgo'] or 1) > 1.3 else ('subestimó' if (ind['sesgo'] or 1) < 0.77 else 'se aproximó a')} "
                      f"la lluvia (sesgo {fmt(ind['sesgo'] or 0, 2)}).",
                      f"Anticipó lluvia en el {bd.pct(ind['POD'])} de los casos en que llovió (1 mm o más); el {bd.pct(ind['FAR'])} de sus anuncios de lluvia no se cumplió."]
            bd.parrafos(fig, textos, 0.42, tam=9)
            fig.text(0.06, 0.06, "POD: probabilidad de detección. FAR: razón de falsas alarmas. CSI: índice de éxito crítico. Sesgo: pronosticado / observado. "
                     "Umbral de 1 mm por estación y día.", fontsize=7, color=GRIS)
            resumen.append("Verificación del pronóstico: " + " ".join(textos))
        else:
            fig.text(0.5, 0.6, "No hay pronósticos guardados para verificar esta semana.", ha="center")
        pdf.savefig(fig); plt.close(fig)

        # ---------------------------------------------------------------- 5. emergencias del anio
        t_em, meta = bd.emergencias()
        r_an = bd.pagina_emergencias_anio(pdf, dt.datetime.combine(fin, dt.time()), "semanal", t_em, meta)
        if r_an:
            dif = 100 * (r_an["actual"] / r_an["prom_prev"] - 1) if r_an["prom_prev"] else 0
            resumen.append(f"Emergencias: de enero a {MESES[r_an['mes_ult'] - 1]} de {r_an['anio']} se atendieron {r_an['actual']} emergencias por lluvia, "
                           f"{fmt(abs(dif), 0)} % {'más' if dif >= 0 else 'menos'} que el promedio de años anteriores (datos hasta el {meta['hasta'][8:]}/{meta['hasta'][5:7]}/{meta['hasta'][:4]}).")

        # ---------------------------------------------------------------- 6. red de estaciones y disponibilidad
        est = se.estaciones(capas)
        se.pagina_red(pdf, dt.datetime.combine(fin, dt.time()), "semanal", capas, est, MESES)
        disp = sorted([(o["disponibilidad"], o["estacion"]) for o in obs])
        bajas = [(d, e) for d, e in disp if d < 0.9]
        fig = plt.figure(figsize=A4)
        cabecera(fig, "6. Disponibilidad de datos de las estaciones en la semana", ini, fin)
        ax = fig.add_axes([0.32, 0.1, 0.62, 0.78])
        ax.barh(range(len(disp)), [100 * d for d, e in disp], color=[AZUL if d >= 0.9 else VERDE_CLARO for d, e in disp])
        ax.set_yticks(range(len(disp))); ax.set_yticklabels([e for d, e in disp], fontsize=6.3)
        ax.set_xlim(0, 100); ax.set_xlabel("Horas con datos (%)"); ax.axvline(90, color=GRIS, ls="--", lw=1)
        resumen.append(f"Red de estaciones: {len(obs)} estaciones enviaron datos; {len(bajas)} tuvieron menos del 90 % de horas con datos.")
        pdf.savefig(fig); plt.close(fig)

    # portada
    fig = plt.figure(figsize=A4)
    fig.patches.append(plt.Rectangle((0, 0.8), 1, 0.2, transform=fig.transFigure, color=AZUL, zorder=0))
    fig.text(0.06, 0.95, "Cuerpo de Bomberos del Distrito Metropolitano de Quito", color="white", fontsize=10)
    fig.text(0.06, 0.925, "Dirección de Gestión de Riesgos", color="#dbe7f5", fontsize=9)
    fig.text(0.06, 0.865, "Informe semanal de lluvias y emergencias", color="white", fontsize=20, weight="bold")
    fig.text(0.06, 0.825, f"Semana del {DIAS[ini.weekday()]} {ini:%d/%m} al {DIAS[fin.weekday()]} {fin:%d/%m/%Y}", color="white", fontsize=11)
    fig.text(0.06, 0.76, "Resumen de la semana", fontsize=14, weight="bold", color=AZUL)
    y = bd.parrafos(fig, resumen, 0.73, tam=9.4, sep=0.012)
    fig.text(0.06, max(y - 0.02, 0.2), "Contenido", fontsize=12, weight="bold", color=AZUL)
    yy = max(y - 0.045, 0.17)
    for i in ["1. Lluvia de la semana comparada con lo normal", "2. Lluvia de cada día y las lluvias más intensas", "3. Alertas enviadas por Telegram",
              "4. Verificación semanal del pronóstico", "5. Emergencias del año: comparación entre años", "6. Red de estaciones y disponibilidad de datos"]:
        fig.text(0.08, yy, i, fontsize=9); yy -= 0.022
    fig.text(0.5, 0.012, bd.CREDITO, ha="center", fontsize=8, color=AZUL, weight="bold")
    with PdfPages(ruta) as pdf:
        pdf.savefig(fig); plt.close(fig)
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter()
    for r in (PdfReader(ruta), PdfReader(io.BytesIO(cuerpo.getvalue()))):
        for p in r.pages:
            w.add_page(p)
    with open(ruta + ".tmp", "wb") as f:
        w.write(f)
    os.replace(ruta + ".tmp", ruta)
    print("Informe semanal:", ruta)
    return ruta, resumen


if __name__ == "__main__":
    generar(dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else None)

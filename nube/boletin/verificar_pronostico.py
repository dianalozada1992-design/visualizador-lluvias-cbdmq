"""Que tanto acerto el pronostico de un dia: compara la lluvia pronosticada por parroquia con la medida por las estaciones.

Uso: python verificar_pronostico.py 2026-10-05
Compara el pronostico emitido ese mismo dia (6h00) y el del dia anterior con la lluvia medida de 0h00 a 24h00 en las
estaciones CBDMQ (LI-COR) y EPMAPS (telemetria). Cada estacion se compara con la parroquia donde esta.
Resultado: verificacion_<fecha>.xlsx y verificacion_<fecha>.png en boletin/salidas.
"""
import datetime as dt
import glob
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

CARPETA = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(CARPETA)
sys.path.insert(0, os.path.join(BASE, "visualizador"))
sys.path.insert(0, os.path.join(BASE, "alertas"))
import actualizar as act  # noqa: E402
from alertas import dentro  # noqa: E402

CARPETAS_PRONOSTICO = [os.path.join(BASE, "pronostico", "boletines"),
                       os.path.join("C:" + os.sep, "Users", "dlozada", "Documents", "shapes", "visualizador-lluvias-cbdmq", "nube", "pronostico", "boletines")]
CATEGORIAS = [(0, 1, "menos de 1 mm"), (1, 5, "1 a 5 mm"), (5, 10, "5 a 10 mm"), (10, 20, "10 a 20 mm"), (20, 1e9, "más de 20 mm")]


def simple(s):
    s = "".join(c for c in unicodedata.normalize("NFD", str(s)) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z]", "", s.lower().replace("�", ""))


def categoria(mm):
    return next(i for i, (a, b, _) in enumerate(CATEGORIAS) if a <= mm < b)


def pronostico(fecha, emitido):
    hoja = fecha.strftime("%d-%m")
    for c in CARPETAS_PRONOSTICO:
        for ruta in sorted(glob.glob(os.path.join(c, f"boletin_{emitido:%Y-%m-%d}*.xlsx")), key=os.path.getmtime, reverse=True):
            x = pd.ExcelFile(ruta)
            if hoja in x.sheet_names:
                d = x.parse(hoja)
                h = x.parse("por_hora")
                h["parroquia"] = h.parroquia.ffill()
                h["mm"] = h[[c for c in h.columns if c not in ("parroquia", "hora")]].mean(axis=1)
                return d, h, ruta
    return None, None, None


def medido(fecha, capas):
    ini, fin = dt.datetime.combine(fecha, dt.time()), dt.datetime.combine(fecha, dt.time()) + dt.timedelta(days=1)
    out = []
    tel = [e for e in capas["telemetria"] if "Hidro" not in e["tipo"]]
    datos = act.bajar_telemetria(tel, ini, fin)
    for e in tel:
        for v in (datos.get(e["id"]) or {}).values():
            if v.get("var_nombre", "").lower().startswith("precip"):
                s = act.serie(v)
                s = s[(s.index >= ini) & (s.index < fin)]
                if len(s) >= 200:  # al menos 2/3 del dia con datos (cada 5 min)
                    out.append({"estacion": e["nombre"], "red": "EPMAPS", "lat": e["lat"], "lon": e["lon"], "mm": float(s.sum()),
                                "horaria": s.resample("h").sum()})
    tok = os.environ.get("LICOR_TOKEN") or re.search(r"Token\s*:\s*(\S+)", open(os.path.join(BASE, "Api.txt"), encoding="utf8").read()).group(1)
    coords = {c["nombre"]: c for c in capas["cbdmq"]}
    for nombre, sn in act.CBDMQ_SN.items():
        q = urllib.parse.urlencode({"loggers": sn, "start_date_time": (ini + dt.timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S"),
                                    "end_date_time": (fin + dt.timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")})
        try:
            d = json.load(urllib.request.urlopen(urllib.request.Request("https://api.licor.cloud/v1/data?" + q,
                                                                        headers={"Authorization": "Bearer " + tok}), timeout=60))
            s = pd.Series({pd.Timestamp(x["timestamp"].replace("Z", "")) - pd.Timedelta(hours=5): x["value"]
                           for x in d["data"] if x["sensor_measurement_type"] == "Rain"}).sort_index()
            if len(s) > 100:
                out.append({"estacion": "CBDMQ " + nombre, "red": "CBDMQ", "lat": coords[nombre]["lat"], "lon": coords[nombre]["lon"],
                            "mm": float(s.sum()), "horaria": s.resample("h").sum()})
        except Exception as ex:
            print("sin datos", nombre, ex)
    return out


def indicadores(t):
    """Indicadores de verificacion por estacion (umbral de 1 mm para 'llovio')."""
    llovio, anuncio = t.medido_mm >= 1, t.pronosticado_mm >= 1
    a = int((llovio & anuncio).sum()); f = int((~llovio & anuncio).sum()); m = int((llovio & ~anuncio).sum()); n = int((~llovio & ~anuncio).sum())
    media_o, media_p = float(t.medido_mm.mean()), float(t.pronosticado_mm.mean())
    return {"estaciones": len(t), "aciertos": a, "falsas_alarmas": f, "no_detectadas": m, "correctos_secos": n,
            "POD": a / (a + m) if a + m else None, "FAR": f / (a + f) if a + f else None, "CSI": a / (a + f + m) if a + f + m else None,
            "media_pron": media_p, "media_obs": media_o, "sesgo": media_p / media_o if media_o > 0.05 else None,
            "EMA": float((t.pronosticado_mm - t.medido_mm).abs().mean()),
            "acierto_cat": float((t.cat_medida == t.cat_pron).mean()), "cerca_cat": float(((t.cat_medida - t.cat_pron).abs() <= 1).mean())}


def verificar(fecha):
    """Compara el pronostico de 'fecha' (emitido ese dia y el dia anterior) con lo medido. Devuelve resultados y grafico."""
    capas = json.loads(open(os.path.join(BASE, "visualizador", "datos", "capas.js"), encoding="utf8").read().split("=", 1)[1].rstrip(";\n"))
    parr = [(f["properties"]["nombre"], f["properties"]["brigada"], f["geometry"]) for f in capas["parroquias"]["features"]]
    obs = medido(fecha, capas)
    for o in obs:
        p = next((p for p in parr if dentro(o["lon"], o["lat"], p[2])), None)
        o["parroquia"], o["brigada"] = (p[0], p[1]) if p else (None, None)
    obs = [o for o in obs if o["parroquia"]]
    resultados = {}
    for etiqueta, emitido in (("mismo día", fecha), ("un día antes", fecha - dt.timedelta(days=1))):
        d, h, ruta = pronostico(fecha, emitido)
        if d is None:
            continue
        prono = {simple(p): v for p, v in zip(d.parroquia, d.lluvia_mm)}
        filas = [{"estacion": o["estacion"], "red": o["red"], "parroquia": o["parroquia"], "brigada": o["brigada"],
                  "medido_mm": round(o["mm"], 1), "pronosticado_mm": round(float(prono[simple(o["parroquia"])]), 1)}
                 for o in obs if simple(o["parroquia"]) in prono]
        if not filas:
            continue
        t = pd.DataFrame(filas)
        t["cat_medida"] = t.medido_mm.map(categoria); t["cat_pron"] = t.pronosticado_mm.map(categoria)
        resultados[etiqueta] = {"tabla": t, "h": h, "ind": indicadores(t)}
    if not resultados:
        return None
    r = resultados.get("mismo día") or list(resultados.values())[0]
    t, h = r["tabla"], r["h"]
    por_brig = t.groupby("brigada")[["medido_mm", "pronosticado_mm"]].mean().round(1)
    obs_h = pd.concat([o["horaria"].rename(o["estacion"]) for o in obs], axis=1).mean(axis=1)
    pron_h = h.groupby("hora").mm.mean()
    pron_h.index = pd.to_datetime(pron_h.index)
    pron_h = pron_h[pron_h.index.normalize() == pd.Timestamp(fecha)]
    hora_obs = int(obs_h.idxmax().hour) if obs_h.max() > 0.02 else None
    hora_pron = int(pron_h.idxmax().hour) if len(pron_h) and pron_h.max() > 0.02 else None
    os.makedirs(os.path.join(CARPETA, "salidas"), exist_ok=True)
    fig, axs = plt.subplots(1, 3, figsize=(15, 5))
    ax = axs[0]
    lim = max(t.medido_mm.max(), t.pronosticado_mm.max()) * 1.1 + 1
    ax.scatter(t.pronosticado_mm, t.medido_mm, c=["#1f3f73" if x == "CBDMQ" else "#2f86c8" for x in t.red], s=28)
    ax.plot([0, lim], [0, lim], "--", color="#9aa7b4"); ax.set_xlim(0, lim); ax.set_ylim(0, lim)
    ax.set_xlabel("Precipitación pronosticada (mm)"); ax.set_ylabel("Precipitación observada (mm)")
    ax.set_title("Pronosticado vs observado por estación")
    ax = axs[1]
    yy = np.arange(len(por_brig))
    ax.barh(yy + 0.2, por_brig.pronosticado_mm, 0.38, color="#a8dcae", label="Pronosticado")
    ax.barh(yy - 0.2, por_brig.medido_mm, 0.38, color="#1f3f73", label="Observado")
    ax.set_yticks(yy); ax.set_yticklabels([str(b).replace("Calder\ufffdn", "Calderón").replace("Manuela S\ufffdenz", "Manuela Sáenz") for b in por_brig.index])
    ax.legend(); ax.set_title("Precipitación media por brigada (mm)")
    ax = axs[2]
    ax.bar(obs_h.index.hour, obs_h.values, color="#1f3f73", width=0.8, label="Observado (media de estaciones)")
    ax.plot(pron_h.index.hour, pron_h.values, "o-", color="#5bbfa8", label="Pronosticado (media de parroquias)")
    ax.set_xlabel("Hora local"); ax.set_ylabel("mm por hora"); ax.legend(fontsize=8); ax.set_title("Distribución horaria")
    fig.tight_layout()
    png = os.path.join(CARPETA, "salidas", f"verificacion_{fecha:%Y-%m-%d}.png")
    fig.savefig(png, dpi=130); plt.close(fig)
    with pd.ExcelWriter(os.path.join(CARPETA, "salidas", f"verificacion_{fecha:%Y-%m-%d}.xlsx")) as xw:
        for et, rr in resultados.items():
            rr["tabla"].drop(columns=["cat_medida", "cat_pron"]).sort_values("medido_mm", ascending=False).to_excel(xw, sheet_name=et.replace(" ", "_"), index=False)
        por_brig.to_excel(xw, sheet_name="por_brigada")
    mayor_obs = t.sort_values("medido_mm").iloc[-1]; mayor_pron = t.sort_values("pronosticado_mm").iloc[-1]
    return {"fecha": fecha, "resultados": resultados, "png": png, "hora_obs": hora_obs, "hora_pron": hora_pron,
            "mayor_obs": mayor_obs, "mayor_pron": mayor_pron, "por_brig": por_brig}


def main(fecha):
    v = verificar(fecha)
    if not v:
        print("No hay pronóstico guardado para", fecha); return
    for et, rr in v["resultados"].items():
        print(et, {k: (round(x, 2) if isinstance(x, float) else x) for k, x in rr["ind"].items()})
    print("hora del máximo: observada", v["hora_obs"], "pronosticada", v["hora_pron"]); print(v["png"])


if __name__ == "__main__":
    main(dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else dt.date.today() - dt.timedelta(days=1))

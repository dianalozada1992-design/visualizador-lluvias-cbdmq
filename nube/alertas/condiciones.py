"""Condiciones propicias para lluvia en las proximas 2 horas (estaciones CBDMQ + modelo GFS).

Aplica en vivo las reglas encontradas por analisis_condiciones_lluvia.py (guardadas en condiciones_lluvia.json):
  nivel 1 "propicias"      en el ultimo anio llovio 1 de cada 4 veces (lluvia >= 1 mm a menos de 15 km)
  nivel 2 "muy propicias"  llovio 4 de cada 10 veces
Lo usa visualizador/actualizar.py con los datos de cada estacion CBDMQ.
"""
import json
import os
import unicodedata
import urllib.parse
import urllib.request

import pandas as pd

CARPETA = os.path.dirname(os.path.abspath(__file__))
_CONF = None


def conf():
    global _CONF
    if _CONF is None:
        _CONF = json.load(open(os.path.join(CARPETA, "condiciones_lluvia.json"), encoding="utf8"))
    return _CONF


def sin_tildes(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def modelo_corto(estaciones, ahora):
    """Lluvia que anuncia el modelo GFS para las 2 horas siguientes y energia para tormentas (CAPE), por estacion."""
    q = urllib.parse.urlencode({"latitude": ",".join(f"{e['lat']:.4f}" for e in estaciones),
                                "longitude": ",".join(f"{e['lon']:.4f}" for e in estaciones),
                                "hourly": "precipitation,cape", "models": "gfs_seamless", "forecast_days": 2,
                                "timezone": "America/Guayaquil"})
    d = json.load(urllib.request.urlopen("https://api.open-meteo.com/v1/forecast?" + q, timeout=60))
    d = d if isinstance(d, list) else [d]
    hora = pd.Timestamp(ahora).floor("h")
    out = {}
    for e, r in zip(estaciones, d):
        h = pd.DataFrame({"mm": r["hourly"]["precipitation"], "cape": r["hourly"]["cape"]}, index=pd.to_datetime(r["hourly"]["time"]))
        sig = h.loc[hora + pd.Timedelta(hours=1): hora + pd.Timedelta(hours=2)]
        out[e["nombre"]] = {"mm_modelo_2h": round(float(sig.mm.sum()), 1), "cape": float(h.cape.get(hora, float("nan")))}
    return out


def evaluar(nombre, datos_licor, lluvia_1h, modelo, ahora):
    """datos_licor: lista de registros de la API LI-COR (ultimas horas). Devuelve dict con valores y nivel 0, 1 o 2."""
    c = conf()
    ahora = pd.Timestamp(ahora)
    if not (c["horas"][0] <= ahora.hour <= c["horas"][1]) or lluvia_1h is None or lluvia_1h >= 0.2 or modelo is None:
        return {"nivel": 0}
    def serie(tipo):
        s = pd.Series({pd.Timestamp(x["timestamp"].replace("Z", "")) - pd.Timedelta(hours=5): x["value"]
                       for x in datos_licor if x["sensor_measurement_type"] == tipo})
        return s.sort_index().resample("10min").mean() if len(s) else pd.Series(dtype=float)
    hr, t, td, rad = serie("RH"), serie("Temperature"), serie("Dew Point"), serie("Solar Radiation")
    if len(hr) < 8 or len(t) < 2 or len(td) < 2:
        return {"nivel": 0}
    hr_ahora = float(hr.iloc[-1]); dpd = float(t.iloc[-1] - td.iloc[-1])
    d_hr = float(hr.iloc[-1] - hr.iloc[-7])
    caida_sol = 0.0
    ref = c["radiacion_despejado"].get(sin_tildes(nombre))
    if ref and len(rad) >= 12:
        franja = rad.index.hour * 6 + rad.index.minute // 10
        despejado = pd.Series([ref[f] for f in franja], index=rad.index)
        indice = (rad / despejado).where(despejado > 150).clip(0, 1.3)
        sol = indice.iloc[-2:].mean()
        antes = indice.iloc[-12:-6].mean()
        if pd.notna(sol) and pd.notna(antes):
            caida_sol = float(antes - sol)
    valores = {"humedad": round(hr_ahora), "dif_rocio": round(dpd, 1), "cambio_humedad_1h": round(d_hr, 1),
               "caida_sol": round(caida_sol, 2), **modelo}
    def cumple(r):
        return (hr_ahora >= r["hr_min"] and dpd <= r["dpd_max"] and d_hr >= r["d_hr_1h_min"] and
                (modelo["cape"] or 0) >= r["cape_min"] and modelo["mm_modelo_2h"] >= r["mm_modelo_2h_min"] and caida_sol >= r["caida_sol_min"])
    nivel = 2 if c["muy_propicias"] and cumple(c["muy_propicias"]["regla"]) else (1 if cumple(c["propicias"]["regla"]) else 0)
    prob = c["muy_propicias" if nivel == 2 else "propicias"]["aciertos"]["prob_lluvia_si_aviso"] if nivel else None
    return {"nivel": nivel, "prob_historica": prob, **valores}

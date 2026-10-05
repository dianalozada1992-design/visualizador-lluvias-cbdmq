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


_CONF_P = None


def conf_paramh2o():
    """Reglas para las estaciones climatologicas de paraMH2O (analisis_condiciones_paramh2o.py), o None si no hay."""
    global _CONF_P
    if _CONF_P is None:
        ruta = os.path.join(CARPETA, "condiciones_paramh2o.json")
        _CONF_P = json.load(open(ruta, encoding="utf8")) if os.path.exists(ruta) else {}
    return _CONF_P or None


def punto_rocio(t, hr):
    import math
    a, b = 17.62, 243.12
    g = math.log(max(min(hr, 100), 1) / 100) + a * t / (b + t)
    return b * g / (a - g)


def evaluar_horario(codigo, hr, t, rad, lluvia_1h, modelo, ahora):
    """Estaciones de paraMH2O (telemetria cada 5 min): se usan promedios de la ultima hora y de la anterior,
    igual que en el analisis con datos horarios. hr, t, rad: series con indice de fecha (hora de Quito)."""
    c = conf_paramh2o()
    ahora = pd.Timestamp(ahora)
    if not c or not (c["horas"][0] <= ahora.hour <= c["horas"][1]) or lluvia_1h is None or lluvia_1h >= 0.2 or modelo is None:
        return {"nivel": 0}
    grupo = c["grupos"].get("paramo" if c["altura"].get(codigo, 0) >= c["altura_paramo_m"] else "ciudad_valles")
    if not grupo or not grupo.get("propicias"):
        return {"nivel": 0}
    h1, h2 = ahora - pd.Timedelta(hours=1), ahora - pd.Timedelta(hours=2)
    ult = lambda s: s[(s.index > h1) & (s.index <= ahora)].mean() if s is not None and len(s) else float("nan")
    ant = lambda s: s[(s.index > h2) & (s.index <= h1)].mean() if s is not None and len(s) else float("nan")
    hr1, hr0, t1 = ult(hr), ant(hr), ult(t)
    if not all(pd.notna([hr1, hr0, t1])):
        return {"nivel": 0}
    dpd = float(t1 - punto_rocio(t1, hr1))
    caida_sol = 0.0
    ref = c["radiacion_despejado"].get(codigo)
    if ref and rad is not None and len(rad):
        r1, r0 = ref[(ahora - pd.Timedelta(minutes=30)).hour], ref[(ahora - pd.Timedelta(minutes=90)).hour]
        if r1 > 150 and r0 > 150 and pd.notna(ult(rad)) and pd.notna(ant(rad)):
            caida_sol = float(min(ant(rad) / r0, 1.3) - min(ult(rad) / r1, 1.3))
    valores = {"humedad": round(float(hr1)), "dif_rocio": round(dpd, 1), "cambio_humedad_1h": round(float(hr1 - hr0), 1),
               "caida_sol": round(caida_sol, 2), **modelo}
    def cumple(r):
        return (hr1 >= r["hr_min"] and dpd <= r["dpd_max"] and hr1 - hr0 >= r["d_hr_1h_min"] and (modelo["cape"] or 0) >= r["cape_min"]
                and modelo["mm_modelo_2h"] >= r["mm_modelo_2h_min"] and caida_sol >= r["caida_sol_min"])
    nivel = 2 if grupo.get("muy_propicias") and cumple(grupo["muy_propicias"]["regla"]) else (1 if cumple(grupo["propicias"]["regla"]) else 0)
    prob = grupo["muy_propicias" if nivel == 2 else "propicias"]["aciertos"]["prob_lluvia_si_aviso"] if nivel else None
    return {"nivel": nivel, "prob_historica": prob, **valores}


def sin_tildes(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def modelo_corto(estaciones, ahora, clave="nombre", desfase_h=0):
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
        # desfase_h=1 para datos horarios (paraMH2O): la "hora" del analisis es la ultima hora completa
        base = hora - pd.Timedelta(hours=desfase_h)
        sig = h.loc[base + pd.Timedelta(hours=1): base + pd.Timedelta(hours=2)]
        out[e[clave]] = {"mm_modelo_2h": round(float(sig.mm.sum()), 1), "cape": float(h.cape.get(base, float("nan")))}
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

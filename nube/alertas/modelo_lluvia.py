"""Aviso preventivo de lluvia con el modelo de aprendizaje automatico (regresion logistica, modelo_lluvia.json).

Cada 10 minutos, para cada brigada que estuvo seca la ultima hora, calcula las mismas señales con las que aprendio el modelo
(humedad, temperatura, punto de rocio, sol, viento, lluvia en el resto del DMQ, pronostico GFS, tope de nube del GOES-19 y
cuanto se enfrio, hora y mes) y la probabilidad de que empiece a llover (1 mm o mas) en las proximas 2 horas.
Si pasa el umbral (opcion B "equilibrada", 0,80) se genera el aviso. Entrenamiento: alertas/ml/ (exportar_modelo.py).
"""
import datetime as dt
import json
import math
import os
import urllib.parse
import urllib.request

import numpy as np

CARPETA = os.path.dirname(os.path.abspath(__file__))
_M = {}


def modelo():
    if not _M:
        _M.update(json.load(open(os.path.join(CARPETA, "modelo_lluvia.json"), encoding="utf8")))
    return _M


def rocio(t, hr):
    a, b = 17.62, 243.12
    g = math.log(max(min(hr, 100), 1) / 100) + a * t / (b + t)
    return b * g / (a - g)


def probabilidad(señal):
    m = modelo()
    x = []
    for c in m["señales"]:
        v = señal.get(c)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            v = m["medianas"][c]
        elif c in m["log"]:
            v = math.log1p(max(v, 0))
        x.append(v)
    z = (np.array(x) - np.array(m["media"])) / np.array(m["desvio"])
    return float(1 / (1 + math.exp(-(m["pesos"][0] + float(np.dot(m["pesos"][1:], z))))))


def gfs(ahora):
    """Pronostico GFS de la hora actual y la siguiente en el centro de cada brigada (Open-Meteo)."""
    c = modelo()["centros_brigadas"]
    nombres = list(c)
    q = urllib.parse.urlencode({"latitude": ",".join(str(c[n][0]) for n in nombres), "longitude": ",".join(str(c[n][1]) for n in nombres),
                                "hourly": "precipitation,cape,cloud_cover,relative_humidity_2m", "models": "gfs_seamless",
                                "forecast_days": 2, "timezone": "America/Guayaquil"})
    d = json.load(urllib.request.urlopen("https://api.open-meteo.com/v1/forecast?" + q, timeout=60))
    d = d if isinstance(d, list) else [d]
    h0 = ahora.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:00")
    h1 = (ahora.replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:00")
    out = {}
    for n, r in zip(nombres, d):
        hh = r["hourly"]
        i0, i1 = hh["time"].index(h0), hh["time"].index(h1)
        out[n] = {"gfs_mm": hh["precipitation"][i0], "gfs_mm_sig": hh["precipitation"][i1], "cape": hh["cape"][i0],
                  "gfs_nubes": hh["cloud_cover"][i0], "gfs_hr": hh["relative_humidity_2m"][i0]}
    return out


def señales_por_brigada(salida, brigada_de, ahora):
    """Agrega por brigada las ventanas de la ultima hora (h1) y la anterior (h2) que deja actualizar.py en cada estacion."""
    m = modelo()
    usadas = set(m["estaciones"])
    est = []
    for e in salida.get("cbdmq", []) + salida.get("lluvia_epmaps", []):
        clave = ("CBDMQ:" + e["nombre"]) if e.get("red") == "CBDMQ" else ("EPMAPS:" + e.get("codigo", ""))
        if clave in usadas and e.get("ml") and e.get("lat") is not None:
            b = brigada_de(e["lat"], e["lon"])
            if b:
                est.append((clave, b, e))
    if not est:
        return {}
    lluvias = [e["ml"]["h1"].get("lluvia") for _, _, e in est if e["ml"]["h1"].get("lluvia") is not None]
    dmq = {"dmq_lloviendo": float(sum(1 for v in lluvias if v >= 0.2)), "dmq_max": float(max(lluvias)) if lluvias else 0.0}
    desp = m["rad_despejado"]
    hora_h1 = str(ahora.hour - 1 if ahora.hour > 0 else 23)
    hora_h2 = str(int(hora_h1) - 1 if int(hora_h1) > 0 else 23)
    porb = {}
    for clave, b, e in est:
        porb.setdefault(b, []).append((clave, e))
    salida_b = {}
    for b, lst in porb.items():
        def vals(v, ventana="h1", solo_cbdmq=False):
            return [e["ml"][ventana][v] for c, e in lst if e["ml"][ventana].get(v) is not None and (not solo_cbdmq or c.startswith("CBDMQ"))]

        def sol(ventana, hora):
            r = [min(max(e["ml"][ventana]["rad"] / desp[c][hora], 0), 1.3) for c, e in lst
                 if c in desp and e["ml"][ventana].get("rad") is not None and desp[c].get(hora, 0) > 100]
            return float(np.mean(r)) if r else None
        media = lambda xs: float(np.mean(xs)) if xs else None
        ll = vals("lluvia")
        dpd = [e["ml"]["h1"]["temp"] - rocio(e["ml"]["h1"]["temp"], e["ml"]["h1"]["hr"]) for c, e in lst
               if e["ml"]["h1"].get("temp") is not None and e["ml"]["h1"].get("hr") is not None]
        hr1, hr2, t1, t2 = media(vals("hr")), media(vals("hr", "h2")), media(vals("temp")), media(vals("temp", "h2"))
        s1, s2 = sol("h1", hora_h1), sol("h2", hora_h2)
        salida_b[b] = {"lluvia_prev": max(ll) if ll else None, "hr": hr1, "hr_max": max(vals("hr")) if vals("hr") else None,
                       "d_hr": hr1 - hr2 if hr1 is not None and hr2 is not None else None, "temp": t1,
                       "d_temp": t1 - t2 if t1 is not None and t2 is not None else None, "dpd_min": min(dpd) if dpd else None,
                       "sol": s1, "d_sol": s1 - s2 if s1 is not None and s2 is not None else None,
                       "viento": media(vals("viento", solo_cbdmq=True)), **dmq}
    return salida_b


def evaluar(salida, capas, brigada_de, sat_cand, ahora=None):
    """Devuelve los avisos (tipo "modelo") de las brigadas secas con probabilidad sobre el umbral."""
    ahora = ahora or dt.datetime.now()
    m = modelo()
    porb = señales_por_brigada(salida, brigada_de, ahora)
    if not porb:
        return [], {}
    pron = gfs(ahora)
    sat = salida.get("satelite") or {}
    tope_est, tope_prev = sat.get("estaciones") or {}, sat.get("estaciones_hace1h") or {}
    # tope de nube mas frio sobre las estaciones de cada brigada (por coordenadas), ahora y hace una hora
    topes, previos, frio_est = {}, {}, {}
    for c in sat_cand:
        b = brigada_de(c["lat"], c["lon"])
        v, p = tope_est.get(c["clave_sat"]), tope_prev.get(c["clave_sat"])
        if b and v is not None:
            topes[b] = min(topes.get(b, 99), v)
            frio_est.setdefault(b, []).append((v, c))
        if b and p is not None:
            previos[b] = min(previos.get(b, 99), p)
    probs, avisos = {}, []
    for b, s in porb.items():
        if s["lluvia_prev"] is None or s["lluvia_prev"] >= 0.2:
            continue  # solo se avisa en brigadas que estuvieron secas la ultima hora
        señal = dict(s, **pron.get(b, {}))
        señal["tope_min"] = topes.get(b)
        señal["enfriamiento"] = (previos[b] - topes[b]) if b in previos and b in topes else None
        señal["hora_s"], señal["hora_c"] = math.sin(2 * math.pi * ahora.hour / 24), math.cos(2 * math.pi * ahora.hour / 24)
        señal["mes_s"], señal["mes_c"] = math.sin(2 * math.pi * ahora.month / 12), math.cos(2 * math.pi * ahora.month / 12)
        p = probabilidad(señal)
        probs[b] = round(p, 3)
        if p < m["umbral"]:
            continue
        lst = sorted(frio_est.get(b, []), key=lambda x: x[0]) or [(None, c) for c in sat_cand if brigada_de(c["lat"], c["lon"]) == b]
        lst = [(v, c) for v, c in lst if c["parroquia"] != "Fuera del DMQ"]
        if not lst:
            continue
        parrs = list(dict.fromkeys(c["parroquia"] for _, c in lst))[:6]
        c0 = lst[0][1]
        avisos.append({"tipo": "modelo", "clave": "modelo:" + b, "nivel": 1, "parroquia": c0["parroquia"], "brigada": b, "parroquias": parrs,
                       "lat": c0["lat"], "lon": c0["lon"], "lugar": c0["lugar"], "mm_1h": 0, "prob": round(p, 2),
                       "texto": f"{', '.join(parrs)}: es probable que empiece a llover en las próximas 2 horas.",
                       # el indice del modelo no es una probabilidad calibrada (se entreno dando mas peso a los casos de lluvia): no se muestra
                       "detalle": "Modelo de aprendizaje automático con estaciones, satélite GOES-19 y pronóstico GFS."})
    return avisos, probs

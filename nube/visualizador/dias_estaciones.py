"""Datos hora por hora de un dia completo en cada estacion (pestaña Historico del visualizador).

Lluvia (suma de la hora), temperatura, humedad, radiacion y presion (promedio de la hora), viento (promedio)
y viento maximo (rafaga en las CBDMQ; mayor registro de 5 minutos en las EPMAPS). La bateria no se guarda.
Uso en la computadora: python dias_estaciones.py [AAAA-MM-DD]  -> datos/estaciones_dias.js (por defecto, ayer)
En la nube lo llama correr_actualizacion.py una vez al dia y se guardan los ultimos 7 dias.
"""
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

import pandas as pd

import actualizar as a

VARIABLES = ["lluvia", "temp", "hr", "viento", "viento_max", "rad", "presion"]
LICOR = {"Rain": "lluvia", "Temperature": "temp", "RH": "hr", "Wind speed": "viento", "Air Velocity": "viento",
         "Gust Speed": "viento_max", "Solar Radiation": "rad"}
EPMAPS = {"precip": "lluvia", "temperatura ambiente": "temp", "humedad relativa": "hr", "radiaci": "rad", "presi": "presion"}
DECIMALES = {"rad": 0, "hr": 0}


def horaria(s, var, dia):
    """Serie de 5 minutos -> 24 valores horarios del dia (None si en esa hora no hubo datos)."""
    s = s[(s.index >= dia) & (s.index < dia + dt.timedelta(days=1))].dropna()
    if s.empty:
        return None
    g = s.resample("h")
    h = g.sum() if var == "lluvia" else g.max() if var == "viento_max" else g.mean()
    h[g.count() == 0] = None
    h = h.reindex(pd.date_range(dia, periods=24, freq="h"))
    return [None if pd.isna(v) else round(float(v), DECIMALES.get(var, 1)) for v in h]


def estaciones_cbdmq(capas, dia):
    tok = os.environ.get("LICOR_TOKEN") or re.search(r"Token\s*:\s*(\S+)", open(os.path.join(a.BASE, "Api.txt"), encoding="utf8").read()).group(1)
    coords = {c["nombre"]: c for c in capas["cbdmq"]}
    ini, fin = dia + dt.timedelta(hours=5), dia + dt.timedelta(hours=29)  # hora local -> UTC
    out = []
    for nombre, sn in a.CBDMQ_SN.items():
        q = urllib.parse.urlencode({"loggers": sn, "start_date_time": ini.strftime("%Y-%m-%d %H:%M:%S"), "end_date_time": fin.strftime("%Y-%m-%d %H:%M:%S")})
        d = None
        for intento in range(3):
            try:
                d = json.load(urllib.request.urlopen(urllib.request.Request("https://api.licor.cloud/v1/data?" + q,
                                                                            headers={"Authorization": "Bearer " + tok}), timeout=60))
                break
            except Exception:
                time.sleep(10 * (intento + 1))
        if not d:
            continue
        series = {}
        for x in d["data"]:
            k = LICOR.get(x["sensor_measurement_type"])
            if k and x["value"] is not None and not (nombre in a.SIN_VIENTO and k.startswith("viento")):
                series.setdefault(k, {})[pd.Timestamp(x["timestamp"].replace("Z", "")) - pd.Timedelta(hours=5)] = x["value"]
        v = {k: horaria(pd.Series(s).sort_index(), k, dia) for k, s in series.items()}
        c = coords.get(nombre, {})
        out.append({"nombre": "CBDMQ " + nombre, "red": "CBDMQ", "tipo": "Meteorológica", "lat": c.get("lat"), "lon": c.get("lon"),
                    "v": {k: x for k, x in v.items() if x}})
    return out


def estaciones_epmaps(capas, dia):
    est = [e for e in capas["telemetria"] if "Hidro" not in e["tipo"]]
    todos = a.bajar_telemetria(est, dia, dia + dt.timedelta(days=1))
    out = []
    for e in est:
        data = todos.get(e["id"]) or {}
        v = {}
        for x in data.values():
            n, d = x.get("var_nombre", "").lower(), x.get("datos") or {}
            k = next((c for p, c in EPMAPS.items() if n.startswith(p)), None)
            if k and d.get("valor"):
                s = pd.Series(pd.to_numeric(d["valor"], errors="coerce"), index=pd.to_datetime(d["fecha"]))
                v[k] = horaria(s[~s.index.duplicated()].sort_index(), k, dia)
            # el viento llega sin fecha: el servicio lo entrega cada 5 minutos desde la hora de inicio de la consulta hasta ahora
            if n.startswith("viento") and d.get("velocidad"):
                s = pd.Series(pd.to_numeric(d["velocidad"], errors="coerce") * 3.6, index=pd.date_range(dia, periods=len(d["velocidad"]), freq="5min"))
                v["viento"], v["viento_max"] = horaria(s, "viento", dia), horaria(s, "viento_max", dia)
        v = {k: x for k, x in v.items() if x}
        if v:
            out.append({"nombre": e["codigo"] + " " + e["nombre"], "red": "EPMAPS", "tipo": e["tipo"], "lat": e["lat"], "lon": e["lon"], "v": v})
    return out


def dia_completo(capas, fecha):
    dia = pd.Timestamp(fecha).to_pydatetime()
    return {"estaciones": estaciones_cbdmq(capas, dia) + estaciones_epmaps(capas, dia),
            "generado": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}


def agregar(previo, capas, fecha, dias=7):
    """Agrega el dia a lo guardado y deja solo los ultimos 'dias'."""
    d = dict(previo.get("dias", {}))
    d[fecha] = dia_completo(capas, fecha)
    return {"dias": {k: d[k] for k in sorted(d)[-dias:]}}


def texto(datos):
    return "window.ESTACIONES_DIAS = " + json.dumps(datos, ensure_ascii=False, separators=(",", ":")) + ";\n"


if __name__ == "__main__":
    fecha = sys.argv[1] if len(sys.argv) > 1 else (dt.date.today() - dt.timedelta(days=1)).isoformat()
    capas = json.loads(open(os.path.join(a.CARPETA, "datos", "capas.js"), encoding="utf8").read().split("=", 1)[1].rstrip(";\n"))
    ruta = os.path.join(a.CARPETA, "datos", "estaciones_dias.js")
    try:
        previo = json.loads(open(ruta, encoding="utf8").read().split("=", 1)[1].rstrip(";\n"))
    except Exception:
        previo = {}
    datos = agregar(previo, capas, fecha)
    open(ruta, "w", encoding="utf8").write(texto(datos))
    print(fecha, len(datos["dias"][fecha]["estaciones"]), "estaciones")

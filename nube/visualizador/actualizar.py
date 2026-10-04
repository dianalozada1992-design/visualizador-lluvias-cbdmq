"""Actualiza los datos en vivo del visualizador (datos/tiempo_real.js).

  - Lluvia actual: telemetria paraMH2O (EPMAPS, 72 estaciones) y API LI-COR (8 estaciones CBDMQ)
  - Caudal y nivel de rios: telemetria de las estaciones hidrometricas del paraMH2O
  - Pronostico 72 h por parroquia y brigada (modelos corregidos, ver pronostico\\)
Correr con el Python de ArcGIS Pro. Pensado para correr cada 30 minutos.
"""
import datetime as dt
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import numpy as np
import pandas as pd

CARPETA = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(CARPETA)
sys.path.insert(0, os.path.join(BASE, "pronostico"))
B = "https://paramh2o.aguaquito.gob.ec"
CBDMQ_SN = {"Pifo": "22143392", "Guamaní": "22143393", "El Placer": "22143394", "El Tingo": "22143395",
            "Guayllabamba": "22143396", "San Antonio": "22143397", "Metropolitano": "22143398", "Checa": "22351557"}


def ahora():
    return dt.datetime.now()


# ---------------------------------------------------------------- telemetria paraMH2O
def sesion_telemetria():
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    h = op.open(B + "/telemetria/visualizar/", timeout=60).read().decode()
    return op, re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', h).group(1)


def consulta_telemetria(op, tok, est_id, inicio, fin):
    datos = urllib.parse.urlencode({"csrfmiddlewaretoken": tok, "estacion": est_id, "inicio": inicio.strftime("%Y-%m-%d"),
                                    "hora_inicio": inicio.strftime("%H:%M"), "fin": fin.strftime("%Y-%m-%d"), "hora_fin": fin.strftime("%H:%M")}).encode()
    req = urllib.request.Request(B + "/ajax/telemetria/consulta/", data=datos,
                                 headers={"Referer": B + "/telemetria/visualizar/", "X-Requested-With": "XMLHttpRequest", "X-CSRFToken": tok})
    j = json.loads(urllib.request.urlopen(req, timeout=90).read().decode()) if False else json.loads(op.open(req, timeout=90).read().decode())
    return j.get("data") if j.get("response") else None


def serie(v):
    s = pd.Series(pd.to_numeric(v["datos"]["valor"], errors="coerce"), index=pd.to_datetime(v["datos"]["fecha"]))
    return s[~s.index.duplicated()].sort_index().dropna()


def resumen_lluvia(s, t):
    if s.empty:
        return None
    hoy = t.replace(hour=0, minute=0, second=0, microsecond=0)
    ult = s.index.max()
    return {"ultimo_dato": ult.strftime("%Y-%m-%d %H:%M"), "retraso_min": int((t - ult).total_seconds() // 60),
            "lluvia_1h": round(float(s[s.index > t - dt.timedelta(hours=1)].sum()), 1),
            "lluvia_3h": round(float(s[s.index > t - dt.timedelta(hours=3)].sum()), 1),
            "lluvia_hoy": round(float(s[s.index >= hoy].sum()), 1),
            "lluvia_24h": round(float(s[s.index > t - dt.timedelta(hours=24)].sum()), 1),
            "horaria": [[k.strftime("%Y-%m-%d %H:00"), round(float(v), 1)] for k, v in s.resample("h").sum().tail(24).items()]}


def resumen_rio(s, t, umbral):
    if s.empty:
        return None
    ult = s.index.max()
    actual = float(s.iloc[-1])
    hace6 = s[s.index <= ult - dt.timedelta(hours=6)]
    base = float(hace6.iloc[-1]) if len(hace6) else float(s.iloc[0])
    cambio = (actual - base) / base * 100 if base else 0.0
    estado = "Creciendo" if cambio >= 15 else ("Bajando" if cambio <= -15 else "Estable")
    if umbral and actual >= umbral:
        estado = "Muy alto (sobre el umbral de crecida)"
    return {"ultimo_dato": ult.strftime("%Y-%m-%d %H:%M"), "retraso_min": int((t - ult).total_seconds() // 60),
            "actual": round(actual, 3), "hace_6h": round(base, 3), "cambio_6h_pct": round(cambio, 1),
            "max_24h": round(float(s[s.index > ult - dt.timedelta(hours=24)].max()), 3), "umbral": umbral, "estado": estado,
            "serie": [[k.strftime("%Y-%m-%d %H:%M"), round(float(v), 3)] for k, v in s.resample("30min").mean().dropna().tail(96).items()]}


def telemetria(capas, t):
    op, tok = sesion_telemetria()
    ini = (t - dt.timedelta(hours=30))
    lluvia, rios = [], []
    for e in capas["telemetria"]:
        try:
            data = consulta_telemetria(op, tok, e["id"], ini, t)
        except Exception:
            try:
                op, tok = sesion_telemetria()
                data = consulta_telemetria(op, tok, e["id"], ini, t)
            except Exception:
                data = None
        base = {"codigo": e["codigo"], "nombre": e["nombre"], "tipo": e["tipo"], "lat": e["lat"], "lon": e["lon"], "red": "EPMAPS"}
        if not data:
            if "Hidro" not in e["tipo"]:
                lluvia.append({**base, "sin_datos": True})
            continue
        for k, v in data.items():
            nombre_var = v.get("var_nombre", "")
            if nombre_var.lower().startswith("precip"):
                r = resumen_lluvia(serie(v), t)
                lluvia.append({**base, **(r or {"sin_datos": True})})
            elif nombre_var.lower().startswith(("caudal", "nivel")):
                var = "caudal" if nombre_var.lower().startswith("caudal") else "nivel"
                r = resumen_rio(serie(v), t, e.get("umbral_" + var))
                if r:
                    rios.append({**base, "variable": nombre_var, "unidad": v.get("var_unidad", ""), **r})
        time.sleep(0.3)
    return lluvia, rios


# ---------------------------------------------------------------- CBDMQ (LI-COR)
def cbdmq(capas, t):
    try:
        # en GitHub la clave viene de un "secreto"; en la computadora, de Api.txt
        tok = os.environ.get("LICOR_TOKEN") or re.search(r"Token\s*:\s*(\S+)", open(os.path.join(BASE, "Api.txt"), encoding="utf8").read()).group(1)
    except Exception:
        return []
    fin = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    ini = fin - dt.timedelta(hours=30)
    out = []
    coords = {c["nombre"]: c for c in capas["cbdmq"]}
    for nombre, sn in CBDMQ_SN.items():
        c = coords.get(nombre, {})
        base = {"codigo": "CBDMQ", "nombre": nombre, "tipo": "Meteorológica CBDMQ", "lat": c.get("lat"), "lon": c.get("lon"), "red": "CBDMQ"}
        try:
            q = urllib.parse.urlencode({"loggers": sn, "start_date_time": ini.strftime("%Y-%m-%d %H:%M:%S"), "end_date_time": fin.strftime("%Y-%m-%d %H:%M:%S")})
            # la API rechaza consultas si hay otras al mismo tiempo (por ejemplo el boletin diario): se reintenta
            for intento in range(4):
                try:
                    d = json.load(urllib.request.urlopen(urllib.request.Request("https://api.licor.cloud/v1/data?" + q,
                                                                                headers={"Authorization": "Bearer " + tok}), timeout=120))
                    break
                except Exception:
                    if intento == 3:
                        raise
                    time.sleep(20 * (intento + 1))
            s = pd.Series({pd.Timestamp(x["timestamp"].replace("Z", "")) - pd.Timedelta(hours=5): x["value"]
                           for x in d["data"] if x["sensor_measurement_type"] == "Rain"}).sort_index()
            temp = [x["value"] for x in d["data"] if x["sensor_measurement_type"] == "Temperature"]
            r = resumen_lluvia(s, t)
            out.append({**base, **(r or {"sin_datos": True}), "temperatura": round(temp[-1], 1) if temp else None})
        except Exception:
            out.append({**base, "sin_datos": True})
    # si una estacion fallo, se usa su ultimo dato bueno (marcado como anterior)
    try:
        previo = json.loads(open(os.path.join(CARPETA, "datos", "tiempo_real.js"), encoding="utf8").read().split("=", 1)[1].rstrip(";" + chr(10)))
        ant = {x["nombre"]: x for x in previo.get("cbdmq", []) if not x.get("sin_datos")}
        out = [({**ant[x["nombre"]], "dato_anterior": True} if x.get("sin_datos") and x["nombre"] in ant else x) for x in out]
    except Exception:
        pass
    return out


# ---------------------------------------------------------------- pronostico
def pronostico():
    import pronostico_diario as pdi
    import boletin_visual as bv
    calib = json.load(open(os.path.join(BASE, "pronostico", "calibracion.json"), encoding="utf8"))
    pts, diss = pdi.puntos_parroquias()
    f = pdi.pronostico_modelos(pts, calib)
    h = f.groupby(["parroquia", "hora"]).mm.mean().reset_index()
    pts["brigada"] = bv.brigada_de_parroquias(pts)
    dias = sorted(h.hora.dt.normalize().unique())
    nubes = bv.nubosidad(pts, len(dias))
    por_parroquia = {}
    for p, g in h.groupby("parroquia"):
        por_parroquia[p] = {pd.Timestamp(d).strftime("%Y-%m-%d"): round(float(g[g.hora.dt.normalize() == d].mm.sum()), 1) for d in dias}
    brig = {}
    for b, gp in pts.groupby("brigada"):
        hb = h[h.parroquia.isin(gp.parroquia)].groupby("hora").mm.mean()
        nb = nubes[nubes.parroquia.isin(gp.parroquia)].groupby("hora").nubes.mean() if len(nubes) else pd.Series(dtype=float)
        dd = {}
        for d in dias:
            dia = pd.Timestamp(d)
            per = []
            for nom, a, c in bv.PERIODOS:
                sel = (hb.index.normalize() == dia) & (hb.index.hour >= a) & (hb.index.hour < c)
                mm = float(hb[sel].sum())
                nub = float(nb[(nb.index.normalize() == dia) & (nb.index.hour >= a) & (nb.index.hour < c)].mean()) if len(nb) else np.nan
                per.append({"periodo": nom, "mm": round(mm, 1), "icono": bv.tipo_periodo(mm, nub), "noche": a >= 18 or c <= 6})
            tot = {p: por_parroquia[p][dia.strftime("%Y-%m-%d")] for p in gp.parroquia}
            top = sorted(tot.items(), key=lambda x: -x[1])[:3]
            dd[dia.strftime("%Y-%m-%d")] = {"media_mm": round(float(np.mean(list(tot.values()))), 1), "periodos": per,
                                             "mas_lluvia": [[pdi.NOMBRES.get(p, p), v] for p, v in top]}
        brig[b] = {"dias": dd, "horaria": [[k.strftime("%Y-%m-%d %H:00"), round(float(v), 2)] for k, v in hb.items()]}
    return {"dias": [pd.Timestamp(d).strftime("%Y-%m-%d") for d in dias], "por_parroquia": por_parroquia, "brigadas": brig,
            "modelos": [calib[m]["nombre"] for m in calib["conjunto"]["modelos"]]}


def main():
    t = ahora()
    capas = json.loads(open(os.path.join(CARPETA, "datos", "capas.js"), encoding="utf8").read().split("=", 1)[1].rstrip(";\n"))
    salida = {"actualizado": t.strftime("%Y-%m-%d %H:%M")}
    ruta = os.path.join(CARPETA, "datos", "tiempo_real.js")
    try:
        previo = json.loads(open(ruta, encoding="utf8").read().split("=", 1)[1].rstrip(";\n"))
    except Exception:
        previo = {}
    hace3h = (t - dt.timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
    for nombre, fn in [("cbdmq", lambda: cbdmq(capas, t)), ("telemetria", lambda: telemetria(capas, t)), ("pronostico", pronostico)]:
        # el pronostico cambia poco: se recalcula cada 3 horas (asi no se pasa el limite gratuito de Open-Meteo)
        if nombre == "pronostico" and previo.get("pronostico") and previo.get("pronostico_calculado", "") > hace3h:
            salida["pronostico"], salida["pronostico_calculado"] = previo["pronostico"], previo["pronostico_calculado"]
            continue
        try:
            r = fn()
            if nombre == "telemetria":
                salida["lluvia_epmaps"], salida["rios"] = r
            else:
                salida[nombre] = r
            if nombre == "pronostico":
                salida["pronostico_calculado"] = t.strftime("%Y-%m-%d %H:%M")
            print("OK", nombre, flush=True)
        except Exception as e:
            salida["error_" + nombre] = str(e)[:200]
            print("ERROR", nombre, e, flush=True)
    # estado del boletin diario de pronostico (para avisar en el visualizador si hoy no se genero)
    bol = os.path.join(BASE, "pronostico", "boletines")
    hoy = t.strftime("%Y-%m-%d")
    archivos = [f for f in os.listdir(bol) if f.startswith("pronostico_1_HOY_") and hoy in f] if os.path.isdir(bol) else []
    salida["boletin_hoy"] = ({"generado": True, "hora": dt.datetime.fromtimestamp(os.path.getmtime(os.path.join(bol, archivos[0]))).strftime("%H:%M"),
                             "archivo": archivos[0]} if archivos else {"generado": False})
    # se conserva lo anterior si una fuente fallo
    for k in ("cbdmq", "lluvia_epmaps", "rios", "pronostico"):
        if k not in salida and k in previo:
            salida[k] = previo[k]; salida.setdefault("fuentes_anteriores", []).append(k)
    # alertas por WhatsApp (lluvia de 2 mm, 10/20/30 mm en 1 hora y riesgo de crecida)
    try:
        sys.path.insert(0, os.path.join(BASE, "alertas"))
        import alertas
        salida["alertas"] = alertas.procesar(salida, capas)
        print("OK alertas:", len(salida["alertas"]["activas"]), "activas, mensajes enviados:", len(salida["alertas"]["enviadas"]), flush=True)
    except Exception as e:
        salida["error_alertas"] = str(e)[:200]
        print("ERROR alertas", e, flush=True)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf8") as f:
        f.write("window.TIEMPO_REAL = " + json.dumps(salida, ensure_ascii=False, separators=(",", ":"), default=str) + ";\n")
    os.replace(tmp, ruta)
    llueve = [x for x in salida.get("lluvia_epmaps", []) + salida.get("cbdmq", []) if x.get("lluvia_1h", 0) > 0]
    print("Actualizado", salida["actualizado"], "- estaciones con lluvia en la ultima hora:", len(llueve),
          "- rios:", len(salida.get("rios", [])))


if __name__ == "__main__":
    main()

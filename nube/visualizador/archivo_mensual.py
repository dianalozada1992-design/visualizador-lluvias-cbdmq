"""Archivo mensual de los datos de las estaciones (la nube lo completa cada dia con el dia anterior).

- CBDMQ (LI-COR): tal como llegan, cada 5 minutos, con todos los sensores (incluida la bateria). Sin redondear ni corregir.
- EPMAPS (paraMH2O): hora por hora (lluvia sumada; temperatura, humedad, radiacion y presion promediadas; viento promedio y maximo).
Cada mes queda en un Excel que se descarga desde la pestaña Historico (nivel 2).
Uso en la computadora: python archivo_mensual.py AAAA-MM-DD [AAAA-MM-DD ...]  (agrega esos dias y deja los Excel en datos/archivo/)
"""
import datetime as dt
import gzip
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

import pandas as pd

import actualizar as a

COLUMNAS_LICOR = {"Rain": "Lluvia (mm)", "Temperature": "Temperatura (°C)", "RH": "Humedad relativa (%)", "Dew Point": "Punto de rocío (°C)",
                  "Solar Radiation": "Radiación solar (W/m²)", "Wind speed": "Viento (km/h)", "Air Velocity": "Viento (km/h)",
                  "Gust Speed": "Ráfaga (km/h)", "Wind Direction": "Dirección del viento (°)", "Battery": "Batería (V)"}
COLUMNAS_EPMAPS = {"lluvia": "Lluvia (mm)", "temp": "Temperatura promedio (°C)", "hr": "Humedad relativa promedio (%)",
                   "viento": "Viento promedio (km/h)", "viento_max": "Viento máximo (km/h)", "rad": "Radiación solar promedio (W/m²)",
                   "presion": "Presión atmosférica promedio (hPa)"}
CLAVE = ["Estación", "Fecha y hora"]


# ---------------------------------------------------------------- datos de un dia
def cbdmq_crudo(fecha):
    """Todos los registros de las 8 estaciones CBDMQ en el dia (hora de Ecuador), tal como los entrega LI-COR."""
    tok = os.environ.get("LICOR_TOKEN") or re.search(r"Token\s*:\s*(\S+)", open(os.path.join(a.BASE, "Api.txt"), encoding="utf8").read()).group(1)
    dia = pd.Timestamp(fecha)
    ini, fin = dia + pd.Timedelta(hours=5), dia + pd.Timedelta(hours=29) - pd.Timedelta(seconds=1)  # hora local -> UTC
    tablas = []
    for nombre, sn in a.CBDMQ_SN.items():
        q = urllib.parse.urlencode({"loggers": sn, "start_date_time": ini.strftime("%Y-%m-%d %H:%M:%S"), "end_date_time": fin.strftime("%Y-%m-%d %H:%M:%S")})
        d = None
        for intento in range(4):
            try:
                d = json.load(urllib.request.urlopen(urllib.request.Request("https://api.licor.cloud/v1/data?" + q,
                                                                            headers={"Authorization": "Bearer " + tok}), timeout=90))
                break
            except Exception:
                time.sleep(10 * (intento + 1))
        if d is None:
            raise RuntimeError("LI-COR no respondio para " + nombre)
        if not d.get("data"):
            continue
        df = pd.DataFrame(d["data"])
        df["Fecha y hora"] = pd.to_datetime(df.timestamp.str.replace("Z", "")) - pd.Timedelta(hours=5)
        df["col"] = df.sensor_measurement_type.map(lambda x: COLUMNAS_LICOR.get(x, x))
        t = df.pivot_table(index="Fecha y hora", columns="col", values="value", aggfunc="first").reset_index()
        t.insert(0, "Estación", nombre)
        tablas.append(t)
    if not tablas:
        return pd.DataFrame(columns=CLAVE)
    t = pd.concat(tablas, ignore_index=True)
    orden = list(dict.fromkeys(COLUMNAS_LICOR.values()))
    return t[CLAVE + [c for c in orden if c in t] + sorted(c for c in t if c not in orden and c not in CLAVE)]


def epmaps_horario(dia_datos, fecha):
    """Filas hora por hora de las estaciones EPMAPS a partir de lo que calcula dias_estaciones.py."""
    filas = []
    horas = pd.date_range(fecha, periods=24, freq="h")
    for e in dia_datos["estaciones"]:
        if e["red"] != "EPMAPS":
            continue
        for h, hora in enumerate(horas):
            f = {"Estación": e["nombre"], "Fecha y hora": hora}
            for k, col in COLUMNAS_EPMAPS.items():
                f[col] = e["v"][k][h] if k in e["v"] else None
            f["Tipo de estación"] = e["tipo"]
            filas.append(f)
    return pd.DataFrame(filas)


# ---------------------------------------------------------------- guardar (nube: almacen KV; computadora: carpeta datos/archivo)
class Almacen:
    def __init__(self, kv=None):
        self.kv = kv
        self.carpeta = os.path.join(a.CARPETA, "datos", "archivo")
        # el almacen de Cloudflare tarda unos segundos en mostrar lo recien guardado: en una misma corrida se usa la copia en memoria
        self.memoria = {}

    def leer(self, clave):
        if clave in self.memoria:
            return self.memoria[clave]
        if self.kv:
            return self.kv.leer_bytes(clave)
        ruta = os.path.join(self.carpeta, clave)
        return open(ruta, "rb").read() if os.path.exists(ruta) else None

    def guardar(self, clave, datos, tipo):
        self.memoria[clave] = datos
        if self.kv:
            return self.kv.guardar_bytes(clave, datos, tipo)
        os.makedirs(self.carpeta, exist_ok=True)
        open(os.path.join(self.carpeta, clave), "wb").write(datos)


def indice(alm):
    b = alm.leer("archivo_indice")
    return json.loads(b.decode("utf8")) if b else {"meses": {}}


def archivado(alm, fecha):
    return fecha in indice(alm)["meses"].get(fecha[:7], {}).get("dias", [])


def unir(alm, clave, nuevo):
    """Agrega las filas nuevas al CSV comprimido del mes (si un dia se repite, quedan las filas nuevas)."""
    b = alm.leer(clave)
    if b:
        viejo = pd.read_csv(io.BytesIO(gzip.decompress(b)), parse_dates=["Fecha y hora"])
        nuevo = pd.concat([viejo, nuevo], ignore_index=True)
    nuevo = nuevo.drop_duplicates(CLAVE, keep="last").sort_values(CLAVE).reset_index(drop=True)
    alm.guardar(clave, gzip.compress(nuevo.to_csv(index=False).encode("utf8")), "application/gzip")
    return nuevo


LEAME_CBDMQ = [
    "Datos de las 8 estaciones meteorológicas del CBDMQ, tal como se registran (cada 5 minutos), sin corregir ni redondear.",
    "Fuente: plataforma LI-COR Cloud (sensores HOBO). Hora de Ecuador continental (UTC-5).",
    "Lluvia: milímetros caídos en cada intervalo de 5 minutos. Viento y ráfaga en km/h. Dirección del viento: grados desde el norte, de donde viene el viento.",
    "La estación Metropolitano tiene el sensor de viento sin funcionar (registra 0).",
    "'Accumulated Rain' es un valor que LI-COR entrega solo en algunos registros; se deja tal como llega (la lluvia de cada intervalo está en 'Lluvia (mm)').",
    "Una hoja por estación. Elaborado por: Diana Lozada Ramos - Dirección de Gestión de Riesgos, CBDMQ.",
]
LEAME_EPMAPS = [
    "Datos hora por hora de las estaciones pluviométricas y climatológicas de EPMAPS (red paraMH2O).",
    "Lluvia: suma de la hora. Temperatura, humedad, radiación y presión: promedio de la hora. Viento: promedio y máximo de los registros de la hora, en km/h.",
    "Hora de Ecuador continental. Cada fila es la hora que empieza (por ejemplo 14:00 = de 14h00 a 14h59). Vacío = la estación no midió esa variable o no envió datos.",
    "Fuente: plataforma pública paraMH2O (EPMAPS). Elaborado por: Diana Lozada Ramos - Dirección de Gestión de Riesgos, CBDMQ.",
]


def excel(df, leame, por_estacion):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame({"Información": leame}).to_excel(w, sheet_name="Léame", index=False)
        w.sheets["Léame"].column_dimensions["A"].width = 150
        grupos = df.groupby("Estación") if por_estacion else [("Datos horarios", df)]
        for nombre, g in grupos:
            hoja = re.sub(r"[\[\]:*?/\\]", "", str(nombre))[:31]
            g = g.dropna(axis=1, how="all") if por_estacion else g
            g.to_excel(w, sheet_name=hoja, index=False)
            ws = w.sheets[hoja]
            ws.freeze_panes = "C2"
            ws.auto_filter.ref = ws.dimensions
            for i, col in enumerate(g.columns, start=1):
                ws.column_dimensions[ws.cell(1, i).column_letter].width = max(12, min(30, len(str(col)) + 2))
            for c in ws["B"][1:]:
                c.number_format = "yyyy-mm-dd hh:mm"
    return buf.getvalue()


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def agregar_dia(alm, fecha, dia_datos):
    """Agrega un dia completo al archivo de su mes y rehace los dos Excel del mes."""
    mes = fecha[:7]
    c = unir(alm, f"archivo_cbdmq_{mes}", cbdmq_crudo(fecha))
    e = unir(alm, f"archivo_epmaps_{mes}", epmaps_horario(dia_datos, fecha))
    alm.guardar(f"excel_cbdmq_{mes}", excel(c, LEAME_CBDMQ, True), XLSX)
    alm.guardar(f"excel_epmaps_{mes}", excel(e, LEAME_EPMAPS, False), XLSX)
    ind = indice(alm)
    m = ind["meses"].setdefault(mes, {"dias": []})
    m["dias"] = sorted(set(m["dias"]) | {fecha})
    m["actualizado"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    m["filas_cbdmq"], m["filas_epmaps"] = len(c), len(e)
    alm.guardar("archivo_indice", json.dumps(ind).encode("utf8"), "application/json")
    return m


if __name__ == "__main__":
    import dias_estaciones
    capas = json.loads(open(os.path.join(a.CARPETA, "datos", "capas.js"), encoding="utf8").read().split("=", 1)[1].rstrip(";\n"))
    alm = Almacen()
    for f in sys.argv[1:]:
        print(f, agregar_dia(alm, f, dias_estaciones.dia_completo(capas, f)), flush=True)

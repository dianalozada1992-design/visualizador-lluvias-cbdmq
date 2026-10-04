"""Actualizacion en la nube (GitHub Actions, cada 10 minutos).

1. Baja del almacen privado lo que el programa necesita (capas, datos anteriores, contactos, estado de alertas).
2. Corre visualizador/actualizar.py: estaciones CBDMQ y EPMAPS, rios, pronostico y alertas de Telegram.
3. Sube al almacen los datos nuevos (los lee la pagina web) y el estado de las alertas.
"""
import datetime as dt
import json
import os
import sys

import kv

NUBE = os.path.dirname(os.path.abspath(__file__))
DATOS = os.path.join(NUBE, "visualizador", "datos")
ALERTAS = os.path.join(NUBE, "alertas")
BOLETINES = os.path.join(NUBE, "pronostico", "boletines")


def preparar():
    if not kv.bajar_a_archivo("capas", os.path.join(DATOS, "capas.js")):
        sys.exit("Falta subir las capas al almacen (herramientas/subir_datos.py)")
    kv.bajar_a_archivo("tiempo_real", os.path.join(DATOS, "tiempo_real.js"))
    kv.bajar_a_archivo("geo_pronostico", os.path.join(NUBE, "pronostico", "geo_pronostico.json"))
    kv.bajar_a_archivo("estado_alertas", os.path.join(ALERTAS, "estado_alertas.json"))
    if not kv.bajar_a_archivo("destinos", os.path.join(ALERTAS, "alertas_contactos.json")):
        json.dump({"destinos": []}, open(os.path.join(ALERTAS, "alertas_contactos.json"), "w", encoding="utf8"))
    # estado del boletin de hoy (lo deja correr_pronostico.py): se marca con un archivo vacio con su hora
    b = kv.leer("boletin_hoy")
    if b:
        b = json.loads(b)
        os.makedirs(BOLETINES, exist_ok=True)
        ruta = os.path.join(BOLETINES, b["archivo"])
        open(ruta, "w").close()
        os.utime(ruta, (b["ts"], b["ts"]))


def main():
    preparar()
    sys.path.insert(0, os.path.join(NUBE, "visualizador"))
    import actualizar
    actualizar.main()
    kv.subir_archivo("tiempo_real", os.path.join(DATOS, "tiempo_real.js"))
    estado = os.path.join(ALERTAS, "estado_alertas.json")
    if os.path.exists(estado):
        kv.subir_archivo("estado_alertas", estado)
    print("Datos subidos al almacen", dt.datetime.now().strftime("%Y-%m-%d %H:%M"))


if __name__ == "__main__":
    main()

"""Pronostico diario en la nube (GitHub Actions, 6h00 de Quito).

Genera el boletin (imagenes y PDF), lo envia al grupo de Telegram y deja anotado en el almacen
que el boletin de hoy ya se hizo (el visualizador lo muestra en la cabecera).
"""
import datetime as dt
import glob
import json
import os
import sys

import kv

NUBE = os.path.dirname(os.path.abspath(__file__))
ALERTAS = os.path.join(NUBE, "alertas")


def main():
    # si el boletin de hoy ya se hizo (por otro camino), no se repite
    b = kv.leer("boletin_hoy")
    if b and dt.date.today().strftime("%Y-%m-%d") in json.loads(b).get("archivo", ""):
        print("El boletín de hoy ya se generó; no se repite.")
        return
    kv.bajar_a_archivo("capas", os.path.join(NUBE, "visualizador", "datos", "capas.js"))
    if not kv.bajar_a_archivo("geo_pronostico", os.path.join(NUBE, "pronostico", "geo_pronostico.json")):
        sys.exit("Falta subir geo_pronostico al almacen (herramientas/subir_datos.py)")
    if not kv.bajar_a_archivo("destinos", os.path.join(ALERTAS, "alertas_contactos.json")):
        json.dump({"destinos": []}, open(os.path.join(ALERTAS, "alertas_contactos.json"), "w", encoding="utf8"))
    sys.path.insert(0, os.path.join(NUBE, "pronostico"))
    import pronostico_diario
    pronostico_diario.main()   # al final envia el boletin a Telegram (alertas/enviar_pronostico.py)
    hoy = dt.date.today().strftime("%Y-%m-%d")
    pngs = sorted(glob.glob(os.path.join(NUBE, "pronostico", "boletines", f"pronostico_1_HOY_*_{hoy}.png")))
    if pngs:
        kv.guardar("boletin_hoy", json.dumps({"archivo": os.path.basename(pngs[-1]), "ts": os.path.getmtime(pngs[-1])}))
        print("Boletín de hoy anotado en el almacén")
    else:
        sys.exit("No se generó el boletín de hoy")


if __name__ == "__main__":
    main()

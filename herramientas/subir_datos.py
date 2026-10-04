"""Sube al almacen privado de Cloudflare los datos que no van en el repositorio publico.

  capas           capas del visualizador (parroquias, brigadas, rios, estaciones)
  historico       emergencias por lluvia (pagina de nivel 2)
  diario          lluvia diaria 2018-2026 de todas las estaciones (pagina de nivel 2)
  geo_pronostico  puntos y formas de parroquias y brigadas para el pronostico
  destinos        personas y grupos de Telegram que reciben alertas (sin el token del bot)

Correr cuando cambien esos datos o cuando se registre alguien nuevo en Telegram:
    python subir_datos.py            (todo)
    python subir_datos.py destinos   (solo los contactos)
Necesita herramientas/cloudflare_local.json con {"account_id": "...", "api_token": "..."}.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nube"))
import kv  # noqa: E402

ORIGEN = os.path.join("D:" + os.sep, "Documentos", "Procesos_ de_Contratación", "estacionesmeteorologicas")
ARCHIVOS = {
    "capas": os.path.join(ORIGEN, "visualizador", "datos", "capas.js"),
    "historico": os.path.join(ORIGEN, "visualizador", "datos", "historico.js"),
    "diario": os.path.join(ORIGEN, "visualizador", "datos", "diario.js"),
    "geo_pronostico": os.path.join(ORIGEN, "pronostico", "geo_pronostico.json"),
}


def destinos():
    c = json.load(open(os.path.join(ORIGEN, "alertas", "alertas_contactos.json"), encoding="utf8"))
    return json.dumps({"destinos": c.get("destinos", [])}, ensure_ascii=False)  # el token del bot NO se sube


def main(claves):
    for clave in claves:
        if clave == "destinos":
            kv.guardar("destinos", destinos())
        else:
            kv.subir_archivo(clave, ARCHIVOS[clave])
        print("subido:", clave)


if __name__ == "__main__":
    main(sys.argv[1:] or list(ARCHIVOS) + ["destinos"])

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


def dia_anterior_estaciones(actualizar):
    """Datos hora por hora del dia anterior en cada estacion (pestaña Historico). Una sola vez al dia, despues de la 1h00."""
    ahora = dt.datetime.now()
    ayer = (ahora - dt.timedelta(days=1)).strftime("%Y-%m-%d")
    texto = kv.leer("estaciones_dias")
    previo = json.loads(texto.split("=", 1)[1].rstrip(";\n")) if texto else {}
    if ahora.hour < 1:
        return
    import dias_estaciones
    capas = json.loads(open(os.path.join(DATOS, "capas.js"), encoding="utf8").read().split("=", 1)[1].rstrip(";\n"))
    if ayer not in previo.get("dias", {}):
        previo = actualizar.con_limite(lambda: dias_estaciones.agregar(previo, capas, ayer), 240)
        kv.guardar("estaciones_dias", dias_estaciones.texto(previo))
        print("Dia anterior de las estaciones guardado:", ayer, len(previo["dias"][ayer]["estaciones"]), "estaciones")
    # archivo mensual: CBDMQ tal como llega (cada 5 minutos) y EPMAPS hora por hora, con su Excel para descargar
    import archivo_mensual
    alm = archivo_mensual.Almacen(kv)
    if not archivo_mensual.archivado(alm, ayer):
        m = actualizar.con_limite(lambda: archivo_mensual.agregar_dia(alm, ayer, previo["dias"][ayer]), 300)
        print("Archivo mensual al dia:", ayer, m)


def main():
    preparar()
    sys.path.insert(0, os.path.join(NUBE, "visualizador"))
    import actualizar
    actualizar.main()
    kv.subir_archivo("tiempo_real", os.path.join(DATOS, "tiempo_real.js"))
    # registro de alertas enviadas por Telegram (lo usa el informe semanal)
    try:
        tr = json.loads(open(os.path.join(DATOS, "tiempo_real.js"), encoding="utf8").read().split("=", 1)[1].rstrip(";\n"))
        nuevos = (tr.get("alertas") or {}).get("items_enviados") or []
        if nuevos:
            hist = json.loads(kv.leer("historial_alertas") or "[]") + nuevos
            limite = (dt.datetime.now() - dt.timedelta(days=60)).strftime("%Y-%m-%d")
            kv.guardar("historial_alertas", json.dumps([h for h in hist if h["hora"] >= limite], ensure_ascii=False))
    except Exception as e:
        print("No se pudo guardar el registro de alertas:", str(e)[:100])
    try:
        dia_anterior_estaciones(actualizar)
    except Exception as e:
        print("No se pudo guardar el dia anterior de las estaciones:", str(e)[:150])
    estado = os.path.join(ALERTAS, "estado_alertas.json")
    if os.path.exists(estado):
        kv.subir_archivo("estado_alertas", estado)
    print("Datos subidos al almacen", dt.datetime.now().strftime("%Y-%m-%d %H:%M"))


if __name__ == "__main__":
    main()

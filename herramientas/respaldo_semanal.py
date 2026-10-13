"""Respaldo semanal en la computadora del archivo mensual de las estaciones (Excel guardados en la nube).

Baja de Cloudflare (almacen lluvias_cbdmq) los Excel del mes en curso y del mes anterior (CBDMQ cada 5 minutos y
EPMAPS hora por hora) y los guarda en una carpeta por mes. Los meses que aun no estan en la computadora se bajan
todos (asi la primera vez queda la historia completa). Lo ejecuta la tarea de Windows "CBDMQ Respaldo estaciones"
los lunes a las 8h00. Uso manual: python respaldo_semanal.py
"""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nube"))
import kv  # noqa: E402

DESTINO = os.path.join("D:" + os.sep, "Documentos", "Procesos_ de_Contratación", "estacionesmeteorologicas", "respaldo_estaciones")
REGISTRO = os.path.join(DESTINO, "registro_respaldo.txt")


def anotar(texto):
    os.makedirs(DESTINO, exist_ok=True)
    with open(REGISTRO, "a", encoding="utf8") as f:
        f.write(f"{dt.datetime.now():%Y-%m-%d %H:%M} {texto}\n")
    print(texto, flush=True)


def main():
    indice = json.loads(kv.leer("archivo_indice") or '{"meses": {}}')["meses"]
    hoy = dt.date.today()
    recientes = {hoy.strftime("%Y-%m"), (hoy.replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m")}
    bajados = 0
    for mes, info in sorted(indice.items()):
        carpeta = os.path.join(DESTINO, mes)
        archivos = {f"excel_cbdmq_{mes}": f"Estaciones_CBDMQ_5min_{mes}.xlsx", f"excel_epmaps_{mes}": f"Estaciones_EPMAPS_horario_{mes}.xlsx"}
        faltan = any(not os.path.exists(os.path.join(carpeta, n)) for n in archivos.values())
        if mes not in recientes and not faltan:
            continue
        os.makedirs(carpeta, exist_ok=True)
        for clave, nombre in archivos.items():
            datos = kv.leer_bytes(clave)
            if datos:
                open(os.path.join(carpeta, nombre), "wb").write(datos)
                bajados += 1
        anotar(f"{mes}: respaldado ({len(info['dias'])} días, hasta el {info['dias'][-1]})")
    anotar(f"Respaldo terminado: {bajados} archivos en {DESTINO}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        anotar(f"ERROR en el respaldo: {str(e)[:200]}")
        raise

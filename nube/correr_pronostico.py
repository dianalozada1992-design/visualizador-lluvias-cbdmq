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


def guardar_emitido(fecha):
    """Guarda en el almacen el pronostico emitido hoy (por parroquia y por hora) para verificarlo manana."""
    import pandas as pd
    rutas = sorted(glob.glob(os.path.join(NUBE, "pronostico", "boletines", f"boletin_{fecha}*.xlsx")), key=os.path.getmtime)
    if not rutas:
        return
    x = pd.ExcelFile(rutas[-1])
    hojas = {h: x.parse(h)[["parroquia", "lluvia_mm"]].values.tolist() for h in x.sheet_names if len(h) == 5 and h[2] == "-"}
    ph = x.parse("por_hora")
    ph["parroquia"] = ph.parroquia.ffill()
    ph["mm"] = ph[[c for c in ph.columns if c not in ("parroquia", "hora")]].mean(axis=1).round(3)
    datos = {"hojas": hojas, "por_hora": [[p, str(h), m] for p, h, m in ph[["parroquia", "hora", "mm"]].values.tolist()]}
    kv.guardar(f"pronostico_emitido_{fecha}", json.dumps(datos, ensure_ascii=False))
    print("Pronóstico emitido guardado para la verificación de mañana")


def recuperar_emitidos(hoy):
    """Reconstruye los Excel de pronostico de los dos dias anteriores (para la verificacion del boletin)."""
    import pandas as pd
    for k in range(1, 9):
        fecha = (hoy - dt.timedelta(days=k)).strftime("%Y-%m-%d")
        texto = kv.leer(f"pronostico_emitido_{fecha}")
        if not texto:
            continue
        d = json.loads(texto)
        carpeta = os.path.join(NUBE, "pronostico", "boletines")
        os.makedirs(carpeta, exist_ok=True)
        with pd.ExcelWriter(os.path.join(carpeta, f"boletin_{fecha}.xlsx")) as xw:
            for h, filas in d["hojas"].items():
                pd.DataFrame(filas, columns=["parroquia", "lluvia_mm"]).to_excel(xw, sheet_name=h, index=False)
            pd.DataFrame(d["por_hora"], columns=["parroquia", "hora", "mm"]).to_excel(xw, sheet_name="por_hora", index=False)


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
    # datos para el boletin de lluvias y emergencias
    kv.bajar_a_archivo("emergencias", os.path.join(NUBE, "boletin", "emergencias.json"))
    kv.bajar_a_archivo("diario", os.path.join(NUBE, "boletin", "diario.js"))
    recuperar_emitidos(dt.date.today())
    sys.path.insert(0, os.path.join(NUBE, "pronostico"))
    import pronostico_diario
    pronostico_diario.main()   # al final envia el boletin a Telegram (alertas/enviar_pronostico.py)
    hoy = dt.date.today().strftime("%Y-%m-%d")
    guardar_emitido(hoy)
    pngs = sorted(glob.glob(os.path.join(NUBE, "pronostico", "boletines", f"pronostico_1_HOY_*_{hoy}.png")))
    if pngs:
        kv.guardar("boletin_hoy", json.dumps({"archivo": os.path.basename(pngs[-1]), "ts": os.path.getmtime(pngs[-1])}))
        print("Boletín de hoy anotado en el almacén")
    else:
        sys.exit("No se generó el boletín de hoy")
    # el PDF de lluvias y emergencias queda disponible en el visualizador (boletin/hoy)
    pdf = os.path.join(NUBE, "boletin", "salidas", f"boletin_lluvias_emergencias_{hoy}.pdf")
    if os.path.exists(pdf):
        kv.guardar_bytes("boletin_pdf", open(pdf, "rb").read(), "application/pdf")
        kv.guardar("boletin_pdf_fecha", hoy)
        print("Boletín de lluvias y emergencias guardado para el visualizador")
    # los lunes: informe semanal de la semana anterior
    if dt.date.today().weekday() == 0:
        informe_semanal()


def informe_semanal():
    try:
        kv.bajar_a_archivo("historial_alertas", os.path.join(NUBE, "boletin", "historial_alertas.json"))
        sys.path.insert(0, os.path.join(NUBE, "boletin"))
        sys.path.insert(0, os.path.join(NUBE, "alertas"))
        import informe_semanal as isem
        import alertas
        import enviar_pronostico as ep
        ruta, _ = isem.generar()
        kv.guardar_bytes("informe_semanal_pdf", open(ruta, "rb").read(), "application/pdf")
        kv.guardar("informe_semanal_fecha", os.path.basename(ruta)[16:26])
        token, destinos = alertas.destinos_activos()
        ini = dt.date.fromisoformat(os.path.basename(ruta)[16:26])
        for d in destinos:
            if d["_canal"] == "telegram" and "pronostico" in d.get("recibe", []):
                ep.llamar(token, "sendDocument", {"chat_id": d["chat_id"],
                          "caption": f"Informe semanal de lluvias y emergencias · semana del {ini:%d/%m} al {ini + dt.timedelta(days=6):%d/%m/%Y}"},
                          {"document": (os.path.basename(ruta), open(ruta, "rb").read(), "application/pdf")})
        print("Informe semanal enviado")
    except Exception as e:
        print("No se pudo generar el informe semanal:", str(e)[:200])


if __name__ == "__main__":
    main()

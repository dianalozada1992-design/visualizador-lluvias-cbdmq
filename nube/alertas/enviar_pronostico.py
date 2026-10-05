"""Envia el boletin de pronostico del dia a Telegram (imagenes de hoy, manana y pasado manana + PDF).

Lo llama pronostico_diario.py al terminar (6h00). Tambien se puede correr a mano para reenviar:
    python enviar_pronostico.py            (boletin de hoy)
    python enviar_pronostico.py --prueba   (solo muestra el resumen, no envia)
Lo reciben los destinos de alertas_contactos.json que tengan "pronostico" en "recibe".
"""
import datetime as dt
import glob
import json
import os
import sys
import uuid
import urllib.request

import pandas as pd

import alertas

CARPETA = os.path.dirname(os.path.abspath(__file__))
BOLETINES = os.path.join(os.path.dirname(CARPETA), "pronostico", "boletines")
CAPAS = os.path.join(os.path.dirname(CARPETA), "visualizador", "datos", "capas.js")
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def multipart(campos, archivos):
    """Arma el cuerpo de un envio con archivos (sin librerias externas)."""
    limite = uuid.uuid4().hex
    partes = []
    for k, v in campos.items():
        partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for k, (nombre, contenido, tipo) in archivos.items():
        partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="{k}"; filename="{nombre}"\r\n'
                      f'Content-Type: {tipo}\r\n\r\n'.encode() + contenido + b"\r\n")
    partes.append(f"--{limite}--\r\n".encode())
    return b"".join(partes), f"multipart/form-data; boundary={limite}"


def llamar(token, metodo, campos, archivos):
    cuerpo, tipo = multipart(campos, archivos)
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{metodo}", cuerpo, {"Content-Type": tipo})
    with urllib.request.urlopen(req, timeout=120) as r:
        resp = json.loads(r.read().decode("utf8"))
    if not resp.get("ok"):
        raise RuntimeError(resp.get("description", "error de Telegram"))


def archivos_del_dia(fecha):
    pngs = sorted(p for p in glob.glob(os.path.join(BOLETINES, "pronostico_[123]_*.png"))
                  if os.path.basename(p).count("_") >= 3 and os.path.getmtime(p) >= dt.datetime.combine(fecha, dt.time()).timestamp())
    # una imagen por dia (1 hoy, 2 manana, 3 pasado manana), la mas reciente
    por_dia = {}
    for p in pngs:
        k = os.path.basename(p)[11]
        if k not in por_dia or os.path.getmtime(p) > os.path.getmtime(por_dia[k]):
            por_dia[k] = p
    pdfs = sorted(glob.glob(os.path.join(BOLETINES, f"pronostico_3_dias_emitido_{fecha:%Y-%m-%d}*.pdf")), key=os.path.getmtime)
    completo = os.path.join(os.path.dirname(CARPETA), "boletin", "salidas", f"boletin_lluvias_emergencias_{fecha:%Y-%m-%d}.pdf")
    if os.path.exists(completo):
        pdfs.append(completo)
    return [por_dia[k] for k in sorted(por_dia)], (pdfs[-1] if pdfs else None)


def resumen(fecha):
    """Texto corto: las parroquias con mas lluvia pronosticada cada dia, con su brigada."""
    xlsx = sorted(glob.glob(os.path.join(BOLETINES, f"boletin_{fecha:%Y-%m-%d}*.xlsx")), key=os.path.getmtime)
    brigada = {}
    try:
        capas = json.loads(open(CAPAS, encoding="utf8").read().split("=", 1)[1].rstrip(";\n"))
        brigada = {f["properties"]["nombre"]: f["properties"]["brigada"] for f in capas["parroquias"]["features"]}
    except Exception:
        pass
    lineas = [f"*CBDMQ - Gestión de Riesgos*\n*Pronóstico de lluvia* emitido el {DIAS[fecha.weekday()]} {fecha:%d/%m/%Y}"]
    if xlsx:
        libro = pd.ExcelFile(xlsx[-1])
        hojas = [h for h in libro.sheet_names if len(h) == 5 and h[2] == "-"]
        for n, h in enumerate(hojas[:3]):
            g = libro.parse(h).sort_values("lluvia_mm", ascending=False)
            d = dt.datetime.strptime(f"{h}-{fecha.year}", "%d-%m-%Y")
            rotulo = ["HOY", "MAÑANA", "PASADO MAÑANA"][n] if n < 3 else ""
            top = [f"{r.parroquia} ({brigada.get(r.parroquia, '')}) {alertas.fmt(r.lluvia_mm)} mm".replace(" ()", "")
                   for r in g.head(3).itertuples() if r.lluvia_mm >= 1]
            lineas.append(f"*{rotulo}* {DIAS[d.weekday()]} {d:%d/%m}: " + ("; ".join(top) if top else "sin lluvia importante (menos de 1 mm)"))
    lineas.append("Confirmar en tiempo real con las estaciones (alertas de 10, 20 y 30 mm en una hora).\n" + alertas.CREDITO)
    return "\n\n".join(lineas)


def enviar(fecha=None, prueba=False):
    fecha = fecha or dt.date.today()
    pngs, pdf = archivos_del_dia(fecha)
    texto = resumen(fecha)
    if prueba:
        print(texto, "\nImagenes:", [os.path.basename(p) for p in pngs], "\nPDF:", pdf and os.path.basename(pdf))
        return []
    token, destinos = alertas.destinos_activos()
    destinos = [d for d in destinos if d["_canal"] == "telegram" and "pronostico" in d.get("recibe", [])]
    if not destinos:
        alertas.anotar("Pronóstico: no hay destinos de Telegram con 'pronostico' en recibe")
        return []
    enviados = []
    for d in destinos:
        try:
            if pngs:
                media, archivos = [], {}
                for i, p in enumerate(pngs):
                    item = {"type": "photo", "media": f"attach://foto{i}"}
                    if i == 0:
                        item.update(caption=alertas.a_html(texto)[:1024], parse_mode="HTML")
                    media.append(item)
                    archivos[f"foto{i}"] = (os.path.basename(p), open(p, "rb").read(), "image/png")
                llamar(token, "sendMediaGroup", {"chat_id": d["chat_id"], "media": json.dumps(media)}, archivos)
            else:
                alertas.enviar_telegram(token, d["chat_id"], texto + "\n\n(No se encontraron las imágenes del boletín de hoy)")
            if pdf:
                titulo = "Boletín de lluvias y emergencias (PDF)" if "lluvias_emergencias" in pdf else "Boletín completo en PDF"
                llamar(token, "sendDocument", {"chat_id": d["chat_id"], "caption": titulo},
                       {"document": (os.path.basename(pdf), open(pdf, "rb").read(), "application/pdf")})
            enviados.append(d["nombre"])
            alertas.anotar(f"Pronóstico enviado a {d['nombre']}")
        except Exception as e:
            alertas.anotar(f"ERROR enviando pronóstico a {d['nombre']}: {str(e)[:120]}")
            print("No se pudo enviar el pronóstico a un destino:", str(e)[:120])
    return enviados


if __name__ == "__main__":
    r = enviar(prueba="--prueba" in sys.argv)
    if "--prueba" not in sys.argv:
        print("Pronóstico enviado a:", ", ".join(r) or "nadie (revise alertas_contactos.json)")

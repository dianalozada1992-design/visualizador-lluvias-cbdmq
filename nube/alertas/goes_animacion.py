"""Animacion (GIF) de la ultima hora del satelite GOES-19 sobre el centro del Ecuador, para acompañar los avisos de tormenta por Telegram.

Cada cuadro es la banda 13 (temperatura del tope de las nubes): en gris las nubes bajas o el suelo, y en colores las
nubes altas; cuanto mas frio el tope, mas fuerte la tormenta (por debajo de -40 C suelen dar aguaceros).
Uso de prueba: python goes_animacion.py [AAAA-MM-DDTHH:MM hora local final] [cuadros]  -> alertas/animacion_prueba.gif
"""
import datetime as dt
import io
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib import patheffects  # noqa: E402
from matplotlib.colors import BoundaryNorm, ListedColormap  # noqa: E402
from PIL import Image  # noqa: E402

import goes_satelite as g  # noqa: E402

CARPETA = os.path.dirname(os.path.abspath(__file__))
REGION = {"lat_min": -2.6, "lat_max": 1.3, "lon_min": -80.6, "lon_max": -76.6}
CORTES = [-90, -70, -60, -50, -40, -30, -20, 60]
COLORES = ["#c39bff", "#7b3fa0", "#2b2f8f", "#1f5fae", "#2f86c8", "#8fd3e8"]
ETIQUETAS = ["< -70", "-70 a -60", "-60 a -50", "-50 a -40", "-40 a -30", "-30 a -20"]
CIUDADES = {"Quito": (-0.18, -78.47), "Esmeraldas": (0.96, -79.65), "Santo Domingo": (-0.25, -79.17), "Ibarra": (0.35, -78.12),
            "Latacunga": (-0.93, -78.62), "Ambato": (-1.25, -78.62), "Tena": (-0.99, -77.81), "Nueva Loja": (0.08, -76.89),
            "Portoviejo": (-1.05, -80.45), "Babahoyo": (-1.80, -79.53)}


def contornos():
    return json.load(open(os.path.join(CARPETA, "contornos_ecuador.json"), encoding="utf8"))


def dmq(ruta_capas=None):
    ruta_capas = ruta_capas or os.path.join(os.path.dirname(CARPETA), "visualizador", "datos", "capas.js")
    capas = json.loads(open(ruta_capas, encoding="utf8").read().split("=", 1)[1].rstrip(";\n"))
    lineas = []
    for f in capas["brigadas"]["features"]:
        geo = f["geometry"]
        for p in (geo["coordinates"] if geo["type"] == "MultiPolygon" else [geo["coordinates"]]):
            lineas.append(p[0])
    return lineas


def cuadro(img, cont, lineas_dmq, titulo):
    """Un cuadro de la animacion como imagen PIL."""
    fig = plt.figure(figsize=(5.6, 6.2), dpi=90)
    ax = fig.add_axes([0.02, 0.13, 0.96, 0.8])
    v = img["valor"]
    gris = np.ma.masked_where(v <= -20, v)
    frio = np.ma.masked_where(v > -20, v)
    ax.set_facecolor("#20262e")
    ax.pcolormesh(img["lon"], img["lat"], gris, cmap="Greys", vmin=-20, vmax=30, shading="auto")
    cmap = ListedColormap(COLORES)
    ax.pcolormesh(img["lon"], img["lat"], frio, cmap=cmap, norm=BoundaryNorm(CORTES[:-1], cmap.N), shading="auto")
    for l in cont["provincias"]:
        xs, ys = zip(*l); ax.plot(xs, ys, color="#c9d6e6", lw=0.35, alpha=0.7)
    for l in cont["paises"]:
        xs, ys = zip(*l); ax.plot(xs, ys, color="#ffffff", lw=0.9)
    for l in lineas_dmq:
        xs, ys = zip(*l); ax.plot(xs, ys, color="#a8dcae", lw=1.3)
    for n, (la, lo) in CIUDADES.items():
        if REGION["lat_min"] < la < REGION["lat_max"] and REGION["lon_min"] < lo < REGION["lon_max"]:
            ax.plot(lo, la, "o", ms=3 if n != "Quito" else 5, color="white")
            ax.text(lo + 0.05, la + 0.04, n, color="white", fontsize=7.5 if n != "Quito" else 10, weight="bold" if n == "Quito" else "normal",
                    path_effects=[patheffects.withStroke(linewidth=2.2, foreground="#14294B")])
    ax.set_xlim(REGION["lon_min"], REGION["lon_max"]); ax.set_ylim(REGION["lat_min"], REGION["lat_max"])
    ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])
    fig.text(0.03, 0.955, titulo, fontsize=11, weight="bold", color="#14294B")
    # leyenda
    for i, (c, e) in enumerate(zip(COLORES, ETIQUETAS)):
        x = 0.03 + i * 0.158
        fig.patches.append(plt.Rectangle((x, 0.075), 0.03, 0.022, color=c, transform=fig.transFigure))
        fig.text(x + 0.035, 0.078, e, fontsize=6.6, color="#14294B")
    fig.text(0.03, 0.035, "Tope de las nubes (°C): más frío = tormenta más fuerte · línea verde: DMQ\nFuente: NOAA GOES-19, banda 13 · Elaborado por: Ing. Diana Lozada",
             fontsize=6.6, color="#4A5A70")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="#F4F6F2"); plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def gif(imagenes, cont, lineas_dmq, ms=450):
    """imagenes: lista de recortes (dict de goes_satelite.leer) en orden de tiempo. Devuelve los bytes del GIF."""
    cuadros = [cuadro(i, cont, lineas_dmq, f"Satélite GOES-19 · {(i['hora'] - dt.timedelta(hours=5)):%d/%m %H:%M} (hora de Ecuador)") for i in imagenes]
    cuadros = [c.quantize(colors=128, method=Image.Quantize.MEDIANCUT) for c in cuadros]
    buf = io.BytesIO()
    duraciones = [ms] * (len(cuadros) - 1) + [ms * 4]
    cuadros[0].save(buf, format="GIF", save_all=True, append_images=cuadros[1:], duration=duraciones, loop=0, optimize=True)
    return buf.getvalue()


def ultimas(n=6, fin_utc=None):
    """Las n imagenes mas recientes (una cada 10 minutos) de la region, hasta fin_utc."""
    fin_utc = fin_utc or dt.datetime.utcnow()
    claves = []
    for h in range(0, 4):
        claves = g.archivos("c13", fin_utc - dt.timedelta(hours=h)) + claves
        claves = [k for k in claves if g.inicio_escaneo(k) <= fin_utc]
        if len(claves) >= n:
            break
    return claves[-n:]


if __name__ == "__main__":
    from concurrent.futures import ThreadPoolExecutor
    fin = dt.datetime.fromisoformat(sys.argv[1]) + dt.timedelta(hours=5) if len(sys.argv) > 1 else None
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    claves = ultimas(n, fin)
    with ThreadPoolExecutor(max_workers=4) as ex:
        imgs = list(ex.map(lambda k: g.leer("c13", k, REGION), claves))
    datos = gif(imgs, contornos(), dmq())
    ruta = os.path.join(CARPETA, "animacion_prueba.gif")
    open(ruta, "wb").write(datos)
    print(ruta, len(datos) // 1024, "kB,", len(imgs), "cuadros, descargado", sum(i["bajado_kb"] for i in imgs) // 1024, "MB")

"""Secciones del boletin al estilo del boletin de EPMAPS (lo usa boletin_diario.py).

  - Red de estaciones (mapa con las estaciones CBDMQ y EPMAPS y las brigadas distritales)
  - Pronostico de lluvia acumulada por zona y estacion en 8 periodos (manana, tarde y noche de 3 dias)
  - Mapas de la lluvia pronosticada en el DMQ para 4 periodos
El pronostico es el mismo del boletin diario: modelos ICON, Meteo-France y GFS (Open-Meteo) corregidos
con las estaciones del DMQ (pronostico/calibracion.json).
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap

CARPETA = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(CARPETA)
sys.path.insert(0, os.path.join(BASE, "alertas"))
from alertas import dentro  # noqa: E402

AZUL = "#1f3f73"
GRIS = "#9aa7b4"
# escala de lluvia de verde a azul (sin amarillo, naranja ni rojo)
CORTES = [0, 1, 3, 5, 10, 15, 20, 30, 50]
COLORES = ["#ffffff", "#e3f4e6", "#a8dcae", "#5bbfa8", "#3aa0c8", "#2f86c8", "#1f5fae", "#173f8f"]
NOMBRE_ZONA = {"Norte de Quito": "el norte de la ciudad", "Centro de Quito": "el centro de la ciudad", "Sur de Quito": "el sur de la ciudad",
               "Valles": "los valles", "Páramos y sistemas de agua (fuera del DMQ)": "los páramos y sistemas de agua"}
ZONAS = [("Norte de Quito", ["La Delicia", "Calderón", "Eugenio Espejo"]),
         ("Centro de Quito", ["Manuela Sáenz"]),
         ("Sur de Quito", ["Eloy Alfaro", "Quitumbe"]),
         ("Valles", ["Los Chillos", "Tumbaco"]),
         ("Páramos y sistemas de agua (fuera del DMQ)", [None])]
LUGARES = [("Quito", -0.20, -78.50), ("Calderón", -0.10, -78.42), ("Tumbaco", -0.21, -78.40), ("Conocoto", -0.29, -78.48),
           ("Nanegalito", 0.07, -78.68), ("Pifo", -0.23, -78.34), ("Guayllabamba", -0.06, -78.34), ("San Antonio", -0.01, -78.45),
           ("Lloa", -0.25, -78.58), ("Píntag", -0.37, -78.37)]


def reparar(s):
    return str(s).replace("Calder�n", "Calderón").replace("Manuela S�enz", "Manuela Sáenz")


def cabecera_simple(fig, titulo, numero, hoy, meses):
    fig.patches.append(plt.Rectangle((0, 0.955), 1, 0.045, transform=fig.transFigure, color=AZUL, zorder=0))
    fig.text(0.04, 0.977, "CBDMQ · Dirección de Gestión de Riesgos", color="white", fontsize=9, va="center", weight="bold")
    fig.text(0.96, 0.977, f"Boletín N° {numero} · {hoy.day} de {meses[hoy.month - 1]} de {hoy.year}", color="white", fontsize=9, va="center", ha="right")
    fig.text(0.05, 0.925, titulo, fontsize=13, weight="bold", color=AZUL, va="center")
    fig.text(0.5, 0.012, "Elaborado por: Diana Lozada Ramos", ha="center", fontsize=7.5, color=GRIS)


# ---------------------------------------------------------------- datos
def estaciones(capas):
    """Estaciones de lluvia CBDMQ y EPMAPS con su brigada (por ubicacion)."""
    parr = [(f["properties"]["nombre"], reparar(f["properties"]["brigada"]), f["geometry"]) for f in capas["parroquias"]["features"]]
    lista = [{"nombre": "CBDMQ " + e["nombre"], "red": "CBDMQ", "lat": e["lat"], "lon": e["lon"]} for e in capas["cbdmq"]]
    lista += [{"nombre": e["nombre"], "red": "EPMAPS", "lat": e["lat"], "lon": e["lon"]} for e in capas["telemetria"] if "Hidro" not in e["tipo"]]
    for e in lista:
        p = next((p for p in parr if dentro(e["lon"], e["lat"], p[2])), None)
        e["parroquia"], e["brigada"] = (reparar(p[0]), p[1]) if p else (None, None)
    return lista


def pronostico_puntos(puntos, dias=4):
    """Lluvia horaria corregida (promedio de los 3 modelos) en cada punto [(lat, lon)]: DataFrame horas x puntos."""
    calib = json.load(open(os.path.join(BASE, "pronostico", "calibracion.json"), encoding="utf8"))
    modelos = calib["conjunto"]["modelos"]
    total = None
    for m in modelos:
        cols = []
        for i in range(0, len(puntos), 50):
            g = puntos[i:i + 50]
            q = urllib.parse.urlencode({"latitude": ",".join(f"{la:.4f}" for la, lo in g), "longitude": ",".join(f"{lo:.4f}" for la, lo in g),
                                        "hourly": "precipitation", "models": m, "forecast_days": dias, "timezone": "America/Guayaquil"})
            for intento in range(4):
                try:
                    d = json.load(urllib.request.urlopen("https://api.open-meteo.com/v1/forecast?" + q, timeout=90))
                    break
                except Exception:
                    if intento == 3:
                        raise
                    time.sleep(10 * (intento + 1))
            d = d if isinstance(d, list) else [d]
            for r in d:
                cols.append(pd.Series(r["hourly"]["precipitation"], index=pd.to_datetime(r["hourly"]["time"]), dtype=float))
            time.sleep(1)
        sys.path.insert(0, os.path.join(BASE, "pronostico"))
        import pronostico_diario as pdi
        tabla = pdi.corregir_tabla(pd.concat(cols, axis=1).fillna(0), m, calib)
        total = tabla if total is None else total + tabla
    return total / len(modelos)


def periodos(hoy):
    """8 periodos desde las 7h00 de hoy: manana (7-13), tarde (13-19) y noche (19-7) de 3 dias."""
    d0 = pd.Timestamp(hoy.date())
    out = []
    for k in range(3):
        d = d0 + pd.Timedelta(days=k)
        out += [(d + pd.Timedelta(hours=7), d + pd.Timedelta(hours=13), "7:00–13:00"),
                (d + pd.Timedelta(hours=13), d + pd.Timedelta(hours=19), "13:00–19:00")]
        if k < 2:
            out.append((d + pd.Timedelta(hours=19), d + pd.Timedelta(hours=31), "19:00–7:00"))
    return out


def suma_periodo(serie, ini, fin):
    # la lluvia de Open-Meteo de cada hora es la caida en la hora anterior
    return float(serie[(serie.index > ini) & (serie.index <= fin)].sum())


# ---------------------------------------------------------------- paginas
def dibujar_contorno(ax, capas, grosor_brigada=1.4):
    for f in capas["parroquias"]["features"]:
        g = f["geometry"]
        polis = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for poli in polis:
            x, y = zip(*poli[0]); ax.plot(x, y, color="#b8c2cc", lw=0.35, zorder=3)
    for f in capas["brigadas"]["features"]:
        g = f["geometry"]
        polis = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for poli in polis:
            x, y = zip(*poli[0]); ax.plot(x, y, color=AZUL, lw=grosor_brigada, zorder=4)


def pagina_red(pdf, hoy, numero, capas, est, meses):
    fig = plt.figure(figsize=(8.27, 11.69))
    cabecera_simple(fig, "1. Red de estaciones meteorológicas", numero, hoy, meses)
    ax = fig.add_axes([0.06, 0.12, 0.88, 0.76])
    dibujar_contorno(ax, capas)
    for f in capas["brigadas"]["features"]:
        g = f["geometry"]; poli = (g["coordinates"][0] if g["type"] == "Polygon" else max(g["coordinates"], key=lambda p: len(p[0]))[0])
        x, y = np.array(poli).T
        ax.text(x.mean(), y.mean(), reparar(f["properties"]["nombre"]), fontsize=7.5, color=AZUL, ha="center", weight="bold", alpha=0.6, zorder=5)
    for red, color, marca, tam in (("EPMAPS", "#2f86c8", "o", 22), ("CBDMQ", "#1f3f73", "s", 46)):
        sel = [e for e in est if e["red"] == red]
        ax.scatter([e["lon"] for e in sel], [e["lat"] for e in sel], s=tam, c=color, marker=marca, edgecolor="white", lw=0.6, zorder=6,
                   label=f"{'Estaciones CBDMQ (LI-COR)' if red == 'CBDMQ' else 'Estaciones EPMAPS (telemetría)'}: {len(sel)}")
        if red == "CBDMQ":
            for e in sel:
                ax.annotate(e["nombre"].replace("CBDMQ ", ""), (e["lon"], e["lat"]), xytext=(4, 3), textcoords="offset points", fontsize=6.8, color=AZUL, zorder=7)
    ax.set_xlim(-78.9, -78.15); ax.set_ylim(-0.6, 0.2); ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    ax.legend(loc="lower left", fontsize=8, frameon=True)
    fig.text(0.06, 0.07, "El boletín usa las estaciones del CBDMQ (cada 5 minutos, API LI-COR) y la telemetría de EPMAPS (paraMH2O). "
             "Las líneas azules son\nlas brigadas distritales; las grises, las parroquias.", fontsize=8)
    pdf.savefig(fig); plt.close(fig)


def paginas_zonas(pdf, hoy, numero, est, meses):
    """Pronostico acumulado por periodo para las estaciones de cada zona (barras) y frase resumen."""
    pers = periodos(hoy)
    elegidas = []
    for zona, brigadas in ZONAS:
        sel = [e for e in est if e["brigada"] in brigadas] if brigadas != [None] else [e for e in est if e["brigada"] is None]
        sel = sorted(sel, key=lambda e: (e["red"] != "CBDMQ", e["nombre"]))[:7]
        elegidas.append((zona, sel))
    puntos = [(e["lat"], e["lon"]) for _, sel in elegidas for e in sel]
    tabla = pronostico_puntos(puntos)
    textos, datos = {}, {}
    k = 0
    for zona, sel in elegidas:
        if not sel:
            continue
        valores = []
        for e in sel:
            valores.append([suma_periodo(tabla.iloc[:, k], a, b) for a, b, _ in pers]); k += 1
        V = np.array(valores)
        fig = plt.figure(figsize=(8.27, 11.69))
        cabecera_simple(fig, f"3. Pronóstico de lluvia por periodo: {zona}", numero, hoy, meses)
        tope = max(10, float(np.ceil(V.max() * 1.25 / 5) * 5))
        alto = 0.76 / len(sel)
        for i, (e, fila) in enumerate(zip(sel, V)):
            alto = 0.72 / len(sel)
            ax = fig.add_axes([0.1, 0.86 - (i + 1) * alto + 0.012, 0.78, alto - 0.026])
            colores = [COLORES[np.searchsorted(CORTES, v, side="right") - 1] for v in fila]
            ax.bar(range(len(pers)), fila, color=colores, edgecolor="#2e6b5e", lw=0.5, width=0.8)
            for j, v in enumerate(fila):
                if v >= 0.5:
                    ax.text(j, v, f"{v:.0f}", ha="center", va="bottom", fontsize=7)
            ax.set_ylim(0, tope); ax.set_xlim(-0.6, len(pers) - 0.4)
            ax.grid(axis="y", color="#e5e9ef"); ax.set_axisbelow(True)
            ax.text(1.01, 0.5, e["nombre"], transform=ax.transAxes, rotation=270, va="center", fontsize=7.5, color=AZUL,
                    bbox=dict(facecolor="#e9eff7", edgecolor="#b8c2cc", boxstyle="square,pad=0.3"))
            ax.set_xticks(range(len(pers)))
            if i == len(sel) - 1:
                ax.set_xticklabels([f"{r}\n{a:%d/%m}" if j in (0, 3, 6) else r for j, (a, b, r) in enumerate(pers)], fontsize=6.5)
            else:
                ax.set_xticklabels([])
            ax.tick_params(axis="y", labelsize=7)
        fig.text(0.04, 0.48, "Lluvia pronosticada (mm)", rotation=90, va="center", fontsize=8)
        total = V.sum(axis=1)
        nombre_zona = NOMBRE_ZONA.get(zona, zona.lower())
        if total.max() < 1:
            txt = f"No se espera lluvia importante en {nombre_zona} durante los próximos 3 días (menos de 1 mm)."
        else:
            j = int(np.unravel_index(V.argmax(), V.shape)[1]); a, b, r = pers[j]
            txt = (f"Se espera lluvia en {nombre_zona}, entre {total.min():.0f} y {total.max():.0f} mm en total durante los próximos 3 días. "
                   f"El periodo con más lluvia sería {r} del {a:%d/%m}.")
        textos[zona] = txt
        if total.max() >= 1:
            datos[zona] = (float(total.min()), float(total.max()), r, a)
        import textwrap
        fig.text(0.06, 0.075, "\n".join(textwrap.wrap(txt, 105)), fontsize=9.5, va="top")
        pdf.savefig(fig); plt.close(fig)
    return textos, datos


def pagina_mapas(pdf, hoy, numero, capas, meses):
    """Mapas de la lluvia pronosticada en una malla sobre el DMQ para 4 periodos."""
    lats = np.round(np.arange(-0.6, 0.2001, 0.04), 3)
    lons = np.round(np.arange(-78.9, -78.1499, 0.04), 3)
    puntos = [(la, lo) for la in lats for lo in lons]
    tabla = pronostico_puntos(puntos)
    d0 = pd.Timestamp(hoy.date())
    paneles = [("Hoy, tarde (13:00–19:00)", d0 + pd.Timedelta(hours=13), d0 + pd.Timedelta(hours=19)),
               ("Hoy, noche (19:00–7:00)", d0 + pd.Timedelta(hours=19), d0 + pd.Timedelta(hours=31)),
               ("Mañana, tarde (13:00–19:00)", d0 + pd.Timedelta(hours=37), d0 + pd.Timedelta(hours=43)),
               ("Pasado mañana, tarde (13:00–19:00)", d0 + pd.Timedelta(hours=61), d0 + pd.Timedelta(hours=67))]
    cmap = ListedColormap(COLORES); norma = BoundaryNorm(CORTES, cmap.N)
    fig = plt.figure(figsize=(8.27, 11.69))
    cabecera_simple(fig, "4. Mapas de la lluvia pronosticada en el DMQ", numero, hoy, meses)
    resumen = []
    for i, (titulo, a, b) in enumerate(paneles):
        Z = np.array([suma_periodo(tabla.iloc[:, k], a, b) for k in range(len(puntos))]).reshape(len(lats), len(lons))
        ax = fig.add_axes([0.05 + (i % 2) * 0.47, 0.5 - (i // 2) * 0.38, 0.43, 0.36])
        im = ax.pcolormesh(lons, lats, Z, cmap=cmap, norm=norma, shading="nearest", zorder=1)
        dibujar_contorno(ax, capas, grosor_brigada=0.8)
        for nombre, la, lo in LUGARES:
            ax.plot(lo, la, "k.", ms=2.5, zorder=6); ax.text(lo + 0.01, la + 0.008, nombre, fontsize=5.8, zorder=6)
        ax.set_xlim(lons[0], lons[-1]); ax.set_ylim(lats[0], lats[-1]); ax.set_aspect("equal")
        ax.set_xticks([]); ax.set_yticks([])
        ax.set_title(f"{titulo}  ·  {a:%d/%m}", fontsize=8.5, color=AZUL, loc="left")
        resumen.append((titulo, a, float(Z.max())))
    cax = fig.add_axes([0.15, 0.115, 0.7, 0.014])
    cb = fig.colorbar(im, cax=cax, orientation="horizontal", ticks=CORTES)
    cb.set_label("Lluvia pronosticada en el periodo (mm)", fontsize=8); cb.ax.tick_params(labelsize=7)
    fuertes = [f"{t.split(' (')[0].lower()} ({m:.0f} mm)" for t, a, m in resumen if m >= 5]
    txt = ("Según los modelos corregidos, la lluvia más importante se espera en: " + ", ".join(fuertes) + ". Los colores más azules indican más lluvia."
           if fuertes else "Los modelos no anuncian lluvias importantes (más de 5 mm) en estos periodos.")
    import textwrap
    fig.text(0.06, 0.065, "\n".join(textwrap.wrap(txt, 110)), fontsize=8.5, va="top")
    pdf.savefig(fig); plt.close(fig)
    return txt

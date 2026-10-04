"""Boletin visual de pronostico de lluvia por brigada distrital (estilo infografia).

Una imagen cuadrada por dia (hoy, manana, pasado manana) con:
  - mapa de parroquias coloreado de verde a azul segun la lluvia esperada
  - tarjetas por brigada distrital con iconos de madrugada, manana, tarde y noche
  - parroquias con mas lluvia en cada brigada
  - escala de colores e iconografia
Se llama desde pronostico_diario.py; tambien se puede correr solo.
"""
import os
import json
import time
import urllib.parse
import urllib.request
import datetime as dt
import numpy as np
import pandas as pd
try:
    import arcpy  # en la computadora; en GitHub se usa geo_pronostico.json
except ImportError:
    arcpy = None
import matplotlib
import matplotlib.path
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Ellipse, FancyBboxPatch, Polygon, Rectangle
from matplotlib.backends.backend_pdf import PdfPages

CARPETA = os.path.dirname(os.path.abspath(__file__))
BRIGADAS = r"C:\Users\dlozada\Documents\shapes\Cobertura_Brigadas_2026_lim_DMQ_2025\Cobertura_Brigadas_2026_lim_DMQ_2025.shp"
WGS = arcpy.SpatialReference(4326) if arcpy else None
GEO = os.path.join(CARPETA, "geo_pronostico.json")
AZUL_CBDMQ = "#1f3f73"
FONDO_TARJETA = "#e9eff7"
# escala de lluvia diaria (mm): de verde a azul
CLASES = [(0, 1, "#e3f4e6", "Sin lluvia o muy poca", "menos de 1 mm"),
          (1, 5, "#a8dcae", "Lluvia ligera", "1 a 5 mm"),
          (5, 10, "#5bbfa8", "Lluvia moderada", "5 a 10 mm"),
          (10, 20, "#2f86c8", "Lluvia fuerte", "10 a 20 mm"),
          (20, 9999, "#173f8f", "Lluvia muy fuerte", "más de 20 mm")]
PERIODOS = [("Madrugada", 0, 6), ("Mañana", 6, 12), ("Tarde", 12, 18), ("Noche", 18, 24)]
DIAS_SEM = ["LUNES", "MARTES", "MIÉRCOLES", "JUEVES", "VIERNES", "SÁBADO", "DOMINGO"]
MESES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]
SOL, NUBE, NUBE_OSC, BORDE, GOTA = "#f2c230", "#dfe3e8", "#9ea7b1", "#7d8792", "#2b78c2"


def color_lluvia(mm):
    for a, b, c, _, _ in CLASES:
        if a <= mm < b:
            return c
    return CLASES[-1][2]


# ---------------------------------------------------------------- iconos
def _nube(ax, x, y, s, color=NUBE, z=5):
    for dx, dy, r in [(-0.32, 0, 0.28), (0, 0.16, 0.36), (0.34, 0.02, 0.27)]:
        ax.add_patch(Circle((x + dx * s, y + dy * s), r * s, fc=color, ec=BORDE, lw=1.1, zorder=z))
    ax.add_patch(Rectangle((x - 0.32 * s, y - 0.28 * s), 0.66 * s, 0.3 * s, fc=color, ec="none", zorder=z + 0.1))
    ax.plot([x - 0.32 * s, x + 0.34 * s], [y - 0.28 * s, y - 0.28 * s], color=BORDE, lw=1.1, zorder=z + 0.2)


def _sol(ax, x, y, s, z=4):
    for a in np.linspace(0, 2 * np.pi, 9)[:-1]:
        ax.plot([x + 0.42 * s * np.cos(a), x + 0.6 * s * np.cos(a)], [y + 0.42 * s * np.sin(a), y + 0.6 * s * np.sin(a)],
                color=SOL, lw=2.2 * s / 0.06, solid_capstyle="round", zorder=z)
    ax.add_patch(Circle((x, y), 0.32 * s, fc=SOL, ec="none", zorder=z))


def _luna(ax, x, y, s, z=4, fondo=FONDO_TARJETA):
    ax.add_patch(Circle((x, y), 0.36 * s, fc=SOL, ec="none", zorder=z))
    ax.add_patch(Circle((x + 0.18 * s, y + 0.1 * s), 0.32 * s, fc=fondo, ec="none", zorder=z + 0.05))


def _gotas(ax, x, y, s, n, z=6):
    for i in range(n):
        xx = x + (i - (n - 1) / 2) * 0.2 * s
        ax.add_patch(Ellipse((xx, y - 0.45 * s), 0.08 * s, 0.13 * s, fc=GOTA, ec="none", zorder=z))


def _lineas(ax, x, y, s, n, z=6):
    for i in range(n):
        xx = x + (i - (n - 1) / 2) * 0.14 * s
        ax.plot([xx, xx - 0.08 * s], [y - 0.35 * s, y - 0.58 * s], color=GOTA, lw=1.6 * s / 0.06, zorder=z)


def _rayo(ax, x, y, s, z=7):
    pts = [(0, 0), (-0.1, -0.22), (0.0, -0.2), (-0.08, -0.42), (0.14, -0.14), (0.03, -0.16), (0.1, 0)]
    ax.add_patch(Polygon([(x + px * s, y - 0.25 * s + py * s) for px, py in pts], fc=SOL, ec="#8c6d00", lw=0.8, zorder=z))


def icono(ax, x, y, s, tipo, noche=False, fondo=FONDO_TARJETA):
    astro = (lambda: _luna(ax, x - 0.18 * s, y + 0.18 * s, s * 0.8, fondo=fondo)) if noche else (lambda: _sol(ax, x - 0.18 * s, y + 0.18 * s, s * 0.8))
    if tipo == "despejado":
        (_luna(ax, x, y, s, fondo=fondo) if noche else _sol(ax, x, y, s))
    elif tipo == "parcial":
        astro(); _nube(ax, x + 0.08 * s, y - 0.08 * s, s * 0.75)
    elif tipo == "nublado":
        _nube(ax, x + 0.15 * s, y + 0.12 * s, s * 0.6, NUBE_OSC, z=5); _nube(ax, x - 0.05 * s, y - 0.05 * s, s * 0.8, z=6)
    elif tipo == "aislada":
        astro(); _nube(ax, x + 0.08 * s, y - 0.05 * s, s * 0.75); _gotas(ax, x + 0.08 * s, y, s * 0.8, 2)
    elif tipo == "lluvia":
        _nube(ax, x, y, s * 0.85); _gotas(ax, x, y, s * 0.9, 3)
    elif tipo == "chubasco":
        _nube(ax, x, y, s * 0.85, NUBE_OSC); _lineas(ax, x, y, s, 4)
    elif tipo == "tormenta":
        _nube(ax, x, y, s * 0.85, NUBE_OSC); _lineas(ax, x - 0.05 * s, y, s, 3); _rayo(ax, x + 0.16 * s, y, s * 0.9)


ICONOS_LEYENDA = [("despejado", "Despejado"), ("parcial", "Parcialmente\nnublado"), ("nublado", "Nublado"),
                  ("aislada", "Lluvia aislada"), ("lluvia", "Lluvia"), ("chubasco", "Chubasco\nfuerte"), ("tormenta", "Tormenta")]


def tipo_periodo(mm, nubes):
    if mm >= 6:
        return "tormenta"
    if mm >= 3:
        return "chubasco"
    if mm >= 1:
        return "lluvia"
    if mm >= 0.2:
        return "aislada"
    if nubes is None or np.isnan(nubes):
        return "parcial"
    return "despejado" if nubes < 35 else ("parcial" if nubes < 75 else "nublado")


# ---------------------------------------------------------------- datos
def nubosidad(pts, dias):
    """Nubosidad por hora (modelo ICON) en cada parroquia, para elegir el icono cuando no llueve."""
    salida = []
    for i in range(0, len(pts), 25):
        g = pts.iloc[i:i + 25]
        q = urllib.parse.urlencode({"latitude": ",".join(f"{x:.4f}" for x in g.lat), "longitude": ",".join(f"{x:.4f}" for x in g.lon),
                                    "hourly": "cloud_cover", "models": "icon_seamless", "forecast_days": dias, "timezone": "America/Guayaquil"})
        for intento in range(4):
            try:
                d = json.load(urllib.request.urlopen("https://api.open-meteo.com/v1/forecast?" + q, timeout=120))
                break
            except Exception:
                time.sleep(10)
        else:
            return pd.DataFrame(columns=["parroquia", "hora", "nubes"])
        d = d if isinstance(d, list) else [d]
        for p, r in zip(g.parroquia, d):
            salida.append(pd.DataFrame({"parroquia": p, "hora": pd.to_datetime(r["hourly"]["time"]), "nubes": r["hourly"]["cloud_cover"]}))
    return pd.concat(salida, ignore_index=True)


def brigada_de_parroquias(pts):
    if arcpy is None:
        b = {p["parroquia"]: p["brigada"] for p in json.load(open(GEO, encoding="utf8"))["puntos"]}
        return [b.get(p) for p in pts.parroquia]
    fc = arcpy.management.CreateFeatureclass("memory", "pb", "POINT", spatial_reference=WGS)[0]
    arcpy.management.AddField(fc, "idx", "LONG")
    with arcpy.da.InsertCursor(fc, ["SHAPE@XY", "idx"]) as cur:
        for i, r in pts.reset_index(drop=True).iterrows():
            cur.insertRow([(r.lon, r.lat), i])
    j = arcpy.analysis.SpatialJoin(fc, BRIGADAS, "memory/pbj", match_option="CLOSEST")[0]
    b = {i: x for i, x in arcpy.da.SearchCursor(j, ["idx", "Brigada"])}
    return [b.get(i) for i in range(len(pts))]


def geometrias(capa, campo):
    if arcpy is None:
        g = json.load(open(GEO, encoding="utf8"))["brigadas" if campo == "Brigada" else "parroquias"]
        return [(n, [[tuple(x) for x in p] for p in partes], tuple(lp) if lp else None) for n, partes, lp in g]
    out = []
    with arcpy.da.SearchCursor(capa, [campo, "SHAPE@"], spatial_reference=WGS) as c:
        for nombre, g in c:
            out.append((nombre, [[(p.X, p.Y) for p in parte if p] for parte in g], (g.labelPoint.X, g.labelPoint.Y) if g.spatialReference.type == "Geographic" else None))
    return out


# ---------------------------------------------------------------- dibujo
def dibujar_dia(dia, h, nubes, pts, geo_parr, geo_brig, previa_brig, nombres, salida_png, modelos_txt, rotulo=""):
    """h: lluvia horaria corregida (conjunto) por parroquia; nubes: nubosidad horaria."""
    d0 = pd.Timestamp(dia)
    hd = h[h.hora.dt.normalize() == d0]
    tot = hd.groupby("parroquia").mm.sum()
    nb = nubes[nubes.hora.dt.normalize() == d0] if len(nubes) else nubes
    fig = plt.figure(figsize=(20, 20), dpi=100)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    ax.add_patch(Rectangle((0, 0.915), 1, 0.085, fc=AZUL_CBDMQ, ec="none"))
    ax.text(0.5, 0.968, "PRONÓSTICO DE LLUVIA", ha="center", va="center", fontsize=46, color="white", weight="bold")
    ax.text(0.5, 0.932, "Distrito Metropolitano de Quito  ·  por brigada distrital del CBDMQ", ha="center", va="center", fontsize=20, color="#dbe7f5")
    ax.text(0.04, 0.885, "QUITO", fontsize=34, weight="bold", color=AZUL_CBDMQ, va="center")
    fecha = f"{DIAS_SEM[d0.weekday()]}, {d0.day:02d} DE {MESES[d0.month - 1]} DE {d0.year}"
    if rotulo:
        ax.text(0.225, 0.885, rotulo, fontsize=26, weight="bold", color="white", ha="left", va="center",
                bbox=dict(boxstyle="round,pad=0.35", fc="#2f86c8", ec="none"))
    ax.text(0.715, 0.885, fecha, fontsize=22, weight="bold", color=AZUL_CBDMQ, ha="center", va="center")

    # mapa
    am = fig.add_axes([0.015, 0.215, 0.42, 0.645]); am.axis("off")
    for nombre, partes, _ in geo_parr:
        c = color_lluvia(tot.get(nombre, 0.0))
        for pp in partes:
            xs, ys = zip(*pp)
            am.fill(xs, ys, color=c, lw=0, zorder=1); am.plot(xs, ys, color="white", lw=0.4, zorder=2)
    for nombre, partes, cen in geo_brig:
        for pp in partes:
            xs, ys = zip(*pp)
            am.plot(xs, ys, color=AZUL_CBDMQ, lw=1.8, zorder=3)
    todos = [pt for _, partes, _ in geo_brig for pp in partes for pt in pp]
    xs_, ys_ = zip(*todos)
    am.set_xlim(min(xs_) - 0.01, max(xs_) + 0.01); am.set_ylim(min(ys_) - 0.01, max(ys_) + 0.01)
    am.set_aspect("equal", adjustable="box")
    fig.canvas.draw()
    a_fig = am.transData + fig.transFigure.inverted()
    # capa superior transparente para iconos y nombres sobre el mapa
    sup = fig.add_axes([0, 0, 1, 1], zorder=20); sup.set_xlim(0, 1); sup.set_ylim(0, 1); sup.axis("off"); sup.patch.set_alpha(0)
    ax.text(0.225, 0.857, "Lluvia esperada por parroquia", ha="center", fontsize=16, weight="bold", color=AZUL_CBDMQ)
    # posicion de cada brigada: centro de sus parroquias; si choca con otra se prueba alrededor
    lugares = {}
    centros = pts.dropna(subset=["brigada"]).groupby("brigada")[["lon", "lat"]].median()
    for nombre, c in centros.sort_values("lat", ascending=False).iterrows():
        fx, fy = a_fig.transform((c.lon, c.lat))
        for _ in range(20):
            otros = [o for o in lugares.values() if abs(o[0] - fx) < 0.052 and abs(o[1] - fy) < 0.046]
            if not otros:
                break
            ox, oy = otros[0]
            vx, vy = fx - ox, fy - oy
            n = max(np.hypot(vx, vy), 1e-6)
            fx, fy = fx + 0.012 * vx / n, fy + 0.012 * vy / n
        lugares[nombre] = (fx, fy)
    for nombre, partes, cen in geo_brig:
        if nombre not in lugares:
            continue
        ps = pts[pts.brigada == nombre].parroquia
        mm_b = hd[hd.parroquia.isin(ps)].groupby("hora").mm.mean()
        tarde = mm_b[(mm_b.index.hour >= 12)].sum()
        nub = nb[nb.parroquia.isin(ps)].nubes.mean() if len(nb) else np.nan
        tipo = tipo_periodo(mm_b.sum() / 2, nub)
        # coordenadas del mapa -> ejes de la figura
        fx, fy = lugares[nombre]
        icono(sup, fx, fy + 0.011, 0.026, tipo, fondo="white")
        sup.text(fx, fy - 0.016, nombres.get(nombre, nombre), ha="center", fontsize=11.5, weight="bold", color=AZUL_CBDMQ,
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.75), zorder=10)

    # tarjetas por brigada
    orden = ["Calderón", "La Delicia", "Eugenio Espejo", "Tumbaco", "Manuela Sáenz", "Eloy Alfaro", "Quitumbe", "Los Chillos"]
    brig = [b for b in orden if b in set(pts.brigada)] + [b for b in sorted(set(pts.brigada.dropna())) if b not in orden]
    x0, x1, ytop, alto = 0.445, 0.988, 0.86, 0.0795
    for k, b in enumerate(brig):
        y = ytop - (k + 1) * alto
        ax.add_patch(FancyBboxPatch((x0 + 0.03, y + 0.004), x1 - x0 - 0.03, alto - 0.008, boxstyle="round,pad=0.002,rounding_size=0.008",
                                    fc=FONDO_TARJETA, ec="#b8c4d3", lw=1.2))
        ax.text(x0 + 0.014, y + alto / 2, nombres.get(b, b), rotation=90, ha="center", va="center", fontsize=13.5, weight="bold", color=AZUL_CBDMQ)
        ps = pts[pts.brigada == b].parroquia
        tb = tot[tot.index.isin(ps)]
        media = tb.mean() if len(tb) else 0
        ax.add_patch(FancyBboxPatch((x0 + 0.042, y + 0.022), 0.075, alto - 0.04, boxstyle="round,pad=0.002,rounding_size=0.006",
                                    fc=color_lluvia(media), ec="none"))
        ax.text(x0 + 0.0795, y + alto / 2 + 0.012, f"{media:.0f} mm", ha="center", va="center", fontsize=19, weight="bold",
                color="white" if media >= 5 else AZUL_CBDMQ)
        ax.text(x0 + 0.0795, y + alto / 2 - 0.011, "en el día", ha="center", va="center", fontsize=10.5,
                color="white" if media >= 5 else AZUL_CBDMQ)
        hb = hd[hd.parroquia.isin(ps)].groupby("hora").mm.mean()
        for j, (nom_p, a, c) in enumerate(PERIODOS):
            cx = x0 + 0.16 + j * 0.072
            ax.text(cx, y + alto - 0.016, nom_p, ha="center", fontsize=11, color="#34495e")
            mm_p = hb[(hb.index.hour >= a) & (hb.index.hour < c)].sum()
            nub = nb[nb.parroquia.isin(ps) & (nb.hora.dt.hour >= a) & (nb.hora.dt.hour < c)].nubes.mean() if len(nb) else np.nan
            icono(ax, cx, y + alto / 2 + 0.001, 0.032, tipo_periodo(mm_p, nub), noche=(a >= 18 or c <= 6))
            ax.text(cx, y + 0.009, f"{mm_p:.1f} mm", ha="center", fontsize=10, color="#34495e", weight="bold")
        top = tb.sort_values(ascending=False).head(3)
        txt = "Más lluvia en:\n" + "\n".join(f"{nombres.get(p, p)}  {v:.0f} mm" for p, v in top.items()) if len(top) else ""
        ax.text(x0 + 0.432, y + alto / 2 + 0.002, txt, ha="left", va="center", fontsize=10.5, color="#1b2631", linespacing=1.3)
        pv = previa_brig.get(b)
        if pv is not None and pv > 30:
            ax.text(x0 + 0.0795, y + 0.008, f"7 días: {pv:.0f} mm", ha="center", fontsize=9, color=GOTA, weight="bold")

    # escala de colores
    ax.text(0.04, 0.188, "¿QUÉ SIGNIFICA CADA COLOR?  (lluvia esperada en el día)", fontsize=17, weight="bold", color=AZUL_CBDMQ)
    ancho = 0.184
    for i, (a, b_, c, nombre, rango) in enumerate(CLASES):
        xx = 0.04 + i * ancho
        ax.add_patch(Rectangle((xx, 0.142), ancho - 0.006, 0.032, fc=c, ec="none"))
        ax.text(xx + (ancho - 0.006) / 2, 0.158, rango, ha="center", va="center", fontsize=13, weight="bold",
                color="white" if a >= 5 else AZUL_CBDMQ)
        ax.text(xx + (ancho - 0.006) / 2, 0.128, nombre, ha="center", va="center", fontsize=12.5, color="#1b2631")
    # iconografia
    ax.add_patch(FancyBboxPatch((0.04, 0.03), 0.914, 0.078, boxstyle="round,pad=0.002,rounding_size=0.008", fc=FONDO_TARJETA, ec="#b8c4d3"))
    ax.text(0.05, 0.1, "ICONOGRAFÍA", fontsize=12, weight="bold", color=AZUL_CBDMQ, va="center")
    for i, (t, nom_i) in enumerate(ICONOS_LEYENDA):
        cx = 0.12 + i * 0.123
        icono(ax, cx, 0.073, 0.036, t)
        ax.text(cx, 0.042, nom_i, ha="center", va="center", fontsize=11, color="#1b2631")
    ax.text(0.5, 0.012, f"Pronóstico con modelos {modelos_txt}, corregidos con 115 estaciones (CBDMQ, EPMAPS, REMMAQ). "
            f"Emitido {dt.datetime.now():%d/%m/%Y %H:%M}.  Confirmar en tiempo real con las estaciones: 10 / 20 / 30 mm en una hora.  "
            "Dirección de Gestión de Riesgos - CBDMQ", ha="center", fontsize=10, color="#5d6d7e")
    ax.text(0.945, 0.1, "Elaborado por: Diana Lozada Ramos", ha="right", va="center", fontsize=13, color=AZUL_CBDMQ, weight="bold")
    try:
        fig.savefig(salida_png, dpi=100)
    except PermissionError:   # la imagen anterior esta abierta: se guarda con la hora
        fig.savefig(salida_png.replace(".png", f"_{dt.datetime.now():%H%M}.png"), dpi=100)
    return fig


def generar(h, pts, diss, previa, base, modelos_txt, nombres):
    """h: lluvia horaria corregida por parroquia (columnas parroquia, hora, mm)."""
    pts = pts.copy()
    pts["brigada"] = brigada_de_parroquias(pts)
    dias = sorted(h.hora.dt.normalize().unique())
    nubes = nubosidad(pts, len(dias))
    geo_parr = geometrias(diss, "PARROQUIA")
    geo_brig = geometrias(BRIGADAS, "Brigada")
    # lluvia de los ultimos 7 dias por brigada (maximo entre sus estaciones CBDMQ)
    previa_brig = {}
    for nombre, (tot_, la, lo) in previa.items():
        for b, partes, _ in geo_brig:
            for pp in partes:
                if matplotlib.path.Path(pp).contains_point((lo, la)):
                    previa_brig[b] = max(previa_brig.get(b, 0), tot_)
    nombres = {**nombres, "Calder�n": "Calderón", "Manuela S�enz": "Manuela Sáenz"}
    pngs = []
    with PdfPages(os.path.join(os.path.dirname(base), f"pronostico_3_dias_emitido_{pd.Timestamp.now():%Y-%m-%d}.pdf")) as pdf:
        hoy = pd.Timestamp.now().normalize()
        carpeta = os.path.dirname(base)
        for i, dia in enumerate(dias):
            d = pd.Timestamp(dia)
            dif = (d - hoy).days
            rotulo = {0: "HOY", 1: "MAÑANA", 2: "PASADO MAÑANA"}.get(dif, "")
            nombre_dia = DIAS_SEM[d.weekday()].lower().replace("á", "a").replace("é", "e")
            png = os.path.join(carpeta, f"pronostico_{i + 1}_{rotulo.replace(' ', '_') or 'dia'}_{nombre_dia}_{d:%Y-%m-%d}.png")
            fig = dibujar_dia(dia, h, nubes, pts, geo_parr, geo_brig, previa_brig, nombres, png, modelos_txt, rotulo)
            pdf.savefig(fig); plt.close(fig)
            pngs.append(png)
    return pngs


if __name__ == "__main__":
    import pronostico_diario as pdi
    calib = json.load(open(os.path.join(CARPETA, "calibracion.json"), encoding="utf8"))
    pts, diss = pdi.puntos_parroquias()
    f = pdi.pronostico_modelos(pts, calib)
    h = f.groupby(["parroquia", "hora"]).mm.mean().reset_index()
    previa = pdi.lluvia_7_dias()
    base = os.path.join(CARPETA, "boletines", f"boletin_{pd.Timestamp.now():%Y-%m-%d}")
    txt = ", ".join(calib[m]["nombre"].split(" (")[0] for m in calib["conjunto"]["modelos"])
    print(generar(h, pts, diss, previa, base, txt, pdi.NOMBRES))

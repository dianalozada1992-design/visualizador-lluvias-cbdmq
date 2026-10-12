"""Lectura del satelite GOES-19 (NOAA) sobre el DMQ, para anticipar aguaceros.

Fuente abierta: archivos NetCDF de la NOAA en Amazon (bucket publico noaa-goes19), cada 10 minutos (disco completo).
Solo se descarga el recorte del DMQ y alrededores (lecturas parciales del archivo), no los 24 MB del disco completo.
  - Banda 13 (10,3 um, infrarrojo): temperatura del tope de las nubes. Una nube de tormenta tiene el tope muy frio
    (por debajo de -40 C) y se enfria rapido mientras crece.
  - Producto RRQPE: lluvia estimada por el satelite (mm/h).
Uso de prueba: python goes_satelite.py   (lee la imagen mas reciente y resume lo que hay sobre el DMQ)
"""
import datetime as dt
import io
import re
import urllib.request

import h5py
import numpy as np

BUCKET = "https://noaa-goes19.s3.amazonaws.com"
# zona de vigilancia: el DMQ con un margen de ~50 km para ver las nubes que se acercan
ZONA = {"lat_min": -0.85, "lat_max": 0.55, "lon_min": -79.25, "lon_max": -77.85}
PRODUCTOS = {"c13": ("ABI-L2-CMIPF", "M6C13_G19", "CMI"), "lluvia": ("ABI-L2-RRQPEF", "M6_G19", "RRQPE")}


class ArchivoRemoto(io.RawIOBase):
    """Archivo en internet que se lee por partes (pedidos HTTP con rango), en bloques de 512 kB guardados en memoria."""
    BLOQUE = 512 * 1024

    def __init__(self, url):
        self.url, self.pos, self.bloques, self.bajado = url, 0, {}, 0
        r = urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=30)
        self.tam = int(r.headers["Content-Length"])

    def _bloque(self, i):
        if i not in self.bloques:
            a = i * self.BLOQUE
            b = min(a + self.BLOQUE, self.tam) - 1
            req = urllib.request.Request(self.url, headers={"Range": f"bytes={a}-{b}"})
            for intento in range(3):
                try:
                    self.bloques[i] = urllib.request.urlopen(req, timeout=60).read()
                    break
                except Exception:
                    if intento == 2:
                        raise
            self.bajado += len(self.bloques[i])
        return self.bloques[i]

    def readable(self):
        return True

    def seekable(self):
        return True

    def seek(self, pos, desde=0):
        self.pos = pos if desde == 0 else self.pos + pos if desde == 1 else self.tam + pos
        return self.pos

    def tell(self):
        return self.pos

    def readinto(self, b):
        n = min(len(b), self.tam - self.pos)
        if n <= 0:
            return 0
        sal, p = bytearray(), self.pos
        while len(sal) < n:
            i, off = divmod(p, self.BLOQUE)
            d = self._bloque(i)[off:off + n - len(sal)]
            sal += d
            p += len(d)
        b[:n] = sal
        self.pos += n
        return n


def archivos(producto, hora_utc):
    """Lista los archivos de una hora (UTC) de un producto, del mas antiguo al mas reciente."""
    carpeta, clave, _ = PRODUCTOS[producto]
    pref = f"{carpeta}/{hora_utc:%Y}/{hora_utc.timetuple().tm_yday:03d}/{hora_utc:%H}/OR_{carpeta}-{clave}"
    xml = urllib.request.urlopen(f"{BUCKET}/?list-type=2&prefix={pref}", timeout=30).read().decode()
    return sorted(re.findall(r"<Key>([^<]+)</Key>", xml))


def inicio_escaneo(clave):
    """Hora (UTC) en que empezo la imagen, sacada del nombre del archivo (_sAAAADDDHHMMSSs)."""
    s = re.search(r"_s(\d{4})(\d{3})(\d{2})(\d{2})(\d{2})", clave).groups()
    return dt.datetime(int(s[0]), 1, 1) + dt.timedelta(days=int(s[1]) - 1, hours=int(s[2]), minutes=int(s[3]), seconds=int(s[4]))


def latlon_a_xy(lat, lon, p):
    """Latitud/longitud -> angulos de barrido del satelite (proyeccion geoestacionaria fija de GOES)."""
    req, rpol, H, lon0 = p["semi_major_axis"], p["semi_minor_axis"], p["perspective_point_height"] + p["semi_major_axis"], np.radians(p["longitude_of_projection_origin"])
    la, lo = np.radians(lat), np.radians(lon)
    e = np.sqrt((req ** 2 - rpol ** 2) / req ** 2)
    lac = np.arctan((rpol ** 2 / req ** 2) * np.tan(la))
    rc = rpol / np.sqrt(1 - e ** 2 * np.cos(lac) ** 2)
    sx = H - rc * np.cos(lac) * np.cos(lo - lon0)
    sy = -rc * np.cos(lac) * np.sin(lo - lon0)
    sz = rc * np.sin(lac)
    return np.arcsin(-sy / np.sqrt(sx ** 2 + sy ** 2 + sz ** 2)), np.arctan(sz / sx)


def xy_a_latlon(x, y, p):
    req, rpol, H, lon0 = p["semi_major_axis"], p["semi_minor_axis"], p["perspective_point_height"] + p["semi_major_axis"], np.radians(p["longitude_of_projection_origin"])
    x, y = np.meshgrid(x, y)
    a = np.sin(x) ** 2 + np.cos(x) ** 2 * (np.cos(y) ** 2 + (req ** 2 / rpol ** 2) * np.sin(y) ** 2)
    b = -2 * H * np.cos(x) * np.cos(y)
    c = H ** 2 - req ** 2
    with np.errstate(invalid="ignore"):
        rs = (-b - np.sqrt(b ** 2 - 4 * a * c)) / (2 * a)
    sx, sy, sz = rs * np.cos(x) * np.cos(y), -rs * np.sin(x), rs * np.cos(x) * np.sin(y)
    lat = np.degrees(np.arctan((req ** 2 / rpol ** 2) * (sz / np.sqrt((H - sx) ** 2 + sy ** 2))))
    lon = np.degrees(lon0 - np.arctan(sy / (H - sx)))
    return lat, lon


def leer(producto, clave, zona=ZONA):
    """Recorte de la zona: dict con 'valor' (matriz), 'lat', 'lon', 'hora' (UTC) y bytes descargados."""
    var = PRODUCTOS[producto][2]
    remoto = ArchivoRemoto(f"{BUCKET}/{clave}")
    with h5py.File(remoto, "r") as f:
        p = {k: float(np.ravel(v)[0]) for k, v in f["goes_imager_projection"].attrs.items()
             if k in ("semi_major_axis", "semi_minor_axis", "perspective_point_height", "longitude_of_projection_origin")}
        x = f["x"][:] * f["x"].attrs["scale_factor"][0] + f["x"].attrs["add_offset"][0]
        y = f["y"][:] * f["y"].attrs["scale_factor"][0] + f["y"].attrs["add_offset"][0]
        x1, y1 = latlon_a_xy(zona["lat_max"], zona["lon_min"], p)
        x2, y2 = latlon_a_xy(zona["lat_min"], zona["lon_max"], p)
        ix = np.where((x >= min(x1, x2)) & (x <= max(x1, x2)))[0]
        iy = np.where((y >= min(y1, y2)) & (y <= max(y1, y2)))[0]
        d = f[var]
        crudo = d[iy[0]:iy[-1] + 1, ix[0]:ix[-1] + 1].astype(float)
        relleno = d.attrs.get("_FillValue", [None])[0]
        valor = crudo * d.attrs.get("scale_factor", [1])[0] + d.attrs.get("add_offset", [0])[0]
        if relleno is not None:
            valor[crudo == relleno] = np.nan
        lat, lon = xy_a_latlon(x[ix], y[iy], p)
    if producto == "c13":
        valor = valor - 273.15  # kelvin -> grados C
    return {"valor": valor, "lat": lat, "lon": lon, "hora": inicio_escaneo(clave), "bajado_kb": remoto.bajado // 1024}


def ultima(producto, ahora_utc=None):
    ahora_utc = ahora_utc or dt.datetime.utcnow()
    for h in (0, 1):
        lista = archivos(producto, ahora_utc - dt.timedelta(hours=h))
        if lista:
            return lista[-1]
    return None


if __name__ == "__main__":
    import time
    for prod in ("c13", "lluvia"):
        t0 = time.time()
        clave = ultima(prod)
        r = leer(prod, clave)
        v = r["valor"]
        hora_local = r["hora"] - dt.timedelta(hours=5)
        print(f"{prod}: imagen de las {hora_local:%H:%M} (hora de Ecuador), recorte {v.shape}, descargado {r['bajado_kb']} kB en {time.time() - t0:.1f} s")
        if prod == "c13":
            print(f"   tope de nube mas frio: {np.nanmin(v):.1f} C; pixeles por debajo de -40 C: {(v < -40).sum()} de {v.size}")
        else:
            print(f"   lluvia estimada maxima: {np.nanmax(v):.1f} mm/h; pixeles con lluvia (>0,5 mm/h): {(v > 0.5).sum()}")

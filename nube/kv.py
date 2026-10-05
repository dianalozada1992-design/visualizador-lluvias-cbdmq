"""Almacen privado de datos en Cloudflare (Workers KV).

Ahi se guardan los datos que no deben quedar en el repositorio publico: capas internas (brigadas),
historico de emergencias, contactos de Telegram, datos en vivo y estado de las alertas.
La pagina web los lee a traves de functions/ (protegida con registro por Cloudflare Access).

Credenciales: variables CLOUDFLARE_API_TOKEN y CLOUDFLARE_ACCOUNT_ID (secretos de GitHub) o, en la
computadora, el archivo herramientas/cloudflare_local.json (no se sube al repositorio).
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

TITULO = "lluvias_cbdmq"
API = "https://api.cloudflare.com/client/v4"
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def credenciales():
    tok, cuenta = os.environ.get("CLOUDFLARE_API_TOKEN"), os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    if not (tok and cuenta):
        local = os.path.join(_RAIZ, "herramientas", "cloudflare_local.json")
        c = json.load(open(local, encoding="utf8"))
        tok, cuenta = c["api_token"], c["account_id"]
    return tok.strip(), cuenta.strip()


def _pedir(metodo, ruta, datos=None, tipo="application/json"):
    tok, cuenta = credenciales()
    req = urllib.request.Request(f"{API}/accounts/{cuenta}{ruta}", data=datos, method=metodo,
                                 headers={"Authorization": "Bearer " + tok, "Content-Type": tipo})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def id_almacen():
    """Busca el almacen por su nombre; si no existe lo crea."""
    lista = json.loads(_pedir("GET", "/storage/kv/namespaces?per_page=100"))["result"]
    for n in lista:
        if n["title"] == TITULO:
            return n["id"]
    return json.loads(_pedir("POST", "/storage/kv/namespaces", json.dumps({"title": TITULO}).encode()))["result"]["id"]


_ID = None


def _ns():
    global _ID
    _ID = _ID or id_almacen()
    return f"/storage/kv/namespaces/{_ID}/values/"


def leer(clave):
    """Devuelve el texto guardado, o None si no existe."""
    try:
        return _pedir("GET", _ns() + urllib.parse.quote(clave)).decode("utf8")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def guardar(clave, texto):
    _pedir("PUT", _ns() + urllib.parse.quote(clave), texto.encode("utf8"), "text/plain; charset=utf-8")


def guardar_bytes(clave, datos, tipo="application/octet-stream"):
    _pedir("PUT", _ns() + urllib.parse.quote(clave), datos, tipo)


def bajar_a_archivo(clave, ruta):
    texto = leer(clave)
    if texto is None:
        return False
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    open(ruta, "w", encoding="utf8").write(texto)
    return True


def subir_archivo(clave, ruta):
    guardar(clave, open(ruta, encoding="utf8").read())


if __name__ == "__main__":
    print("Almacen:", TITULO, id_almacen())

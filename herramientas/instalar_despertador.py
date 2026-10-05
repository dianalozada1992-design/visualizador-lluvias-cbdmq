"""Instala (o actualiza) el "despertador" en Cloudflare Workers: lanza los procesos de GitHub a la hora exacta.

Necesita:
  - herramientas/cloudflare_local.json con un token de Cloudflare que tenga tambien el permiso
    "Workers Scripts: Edit"
  - herramientas/github_local.json con {"token": "..."}: token de GitHub (fine-grained) con permiso
    "Actions: Read and write" sobre el repositorio visualizador-lluvias-cbdmq
Ninguno de los dos archivos se sube al repositorio. Uso: python instalar_despertador.py
"""
import json
import os
import urllib.error
import urllib.request
import uuid

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
NOMBRE = "despertador-lluvias-cbdmq"
HORARIOS = ["*/10 * * * *", "0 11 * * *"]


def pedir(metodo, ruta, datos=None, tipo="application/json"):
    c = json.load(open(os.path.join(AQUI, "cloudflare_local.json"), encoding="utf8"))
    req = urllib.request.Request(f"https://api.cloudflare.com/client/v4/accounts/{c['account_id']}{ruta}", data=datos, method=metodo,
                                 headers={"Authorization": "Bearer " + c["api_token"].strip(), "Content-Type": tipo})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Cloudflare respondio {e.code}: {e.read().decode('utf8', 'replace')[:300]}")


def main():
    gh = json.load(open(os.path.join(AQUI, "github_local.json"), encoding="utf8"))["token"].strip()
    codigo = open(os.path.join(RAIZ, "despertador", "despertador.js"), encoding="utf8").read()
    meta = {"main_module": "despertador.js", "compatibility_date": "2025-01-01",
            "bindings": [{"type": "secret_text", "name": "GITHUB_TOKEN", "text": gh}]}
    limite = uuid.uuid4().hex
    cuerpo = (f'--{limite}\r\nContent-Disposition: form-data; name="metadata"\r\nContent-Type: application/json\r\n\r\n'
              f'{json.dumps(meta)}\r\n--{limite}\r\nContent-Disposition: form-data; name="despertador.js"; filename="despertador.js"\r\n'
              f'Content-Type: application/javascript+module\r\n\r\n{codigo}\r\n--{limite}--\r\n').encode("utf8")
    pedir("PUT", f"/workers/scripts/{NOMBRE}", cuerpo, f"multipart/form-data; boundary={limite}")
    print("Despertador instalado:", NOMBRE)
    pedir("PUT", f"/workers/scripts/{NOMBRE}/schedules", json.dumps([{"cron": h} for h in HORARIOS]).encode())
    print("Horarios:", ", ".join(HORARIOS), "(UTC; 11h00 UTC = 6h00 en Quito)")


if __name__ == "__main__":
    main()

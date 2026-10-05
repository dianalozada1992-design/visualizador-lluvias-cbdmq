"""Alertas de lluvia y crecida por WhatsApp (CallMeBot).

Lo llama actualizar.py del visualizador cada vez que trae datos nuevos. Revisa:
  - aviso "esta lloviendo": 2 mm o mas en la ultima hora en una estacion
  - alerta por lluvia intensa: 10 / 20 / 30 mm en una hora (niveles 1, 2 y 3)
  - riesgo de crecida: lluvia promedio de las estaciones de cada microcuenca en 3 y 24 horas,
    indicando hacia que rios baja el agua; y estaciones de rios que estan creciendo
Para no repetir mensajes, solo avisa cuando algo es nuevo, sube de nivel o sigue activo despues
de unas horas (estado_alertas.json). Los umbrales se cambian en alertas_config.json y las
personas que reciben en alertas_contactos.json.
Prueba sin enviar:  python alertas.py   (o --simular para inventar lluvia fuerte)
"""
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

CARPETA = os.path.dirname(os.path.abspath(__file__))
REGISTRO = os.path.join(CARPETA, "registro_alertas.log")
CREDITO = "Elaborado por: Diana Lozada Ramos"


def leer(nombre, defecto=None):
    ruta = os.path.join(CARPETA, nombre)
    if not os.path.exists(ruta):
        return defecto
    return json.load(open(ruta, encoding="utf8"))


def anotar(texto):
    with open(REGISTRO, "a", encoding="utf8") as f:
        f.write(dt.datetime.now().strftime("%Y-%m-%d %H:%M") + " " + texto + "\n")


def dentro(lon, lat, geom):
    """Punto dentro de poligono (GeoJSON Polygon o MultiPolygon)."""
    if not geom:
        return False
    polis = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    for poli in polis:
        aden = False
        for k, anillo in enumerate(poli):
            j = len(anillo) - 1
            c = False
            for i in range(len(anillo)):
                xi, yi = anillo[i][0], anillo[i][1]
                xj, yj = anillo[j][0], anillo[j][1]
                if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
                    c = not c
                j = i
            if k == 0:
                aden = c
            elif c:
                aden = False  # dentro de un hueco
        if aden:
            return True
    return False


def fmt(v):
    return f"{v:.1f}".replace(".", ",")


def ubicar(e, capas, cuencas):
    parr = next((f["properties"] for f in capas["parroquias"]["features"] if dentro(e["lon"], e["lat"], f["geometry"])), None)
    cue = next((c for c in cuencas if dentro(e["lon"], e["lat"], c["geometria"])), None)
    return parr, cue


def evaluar(salida, capas, cfg, cuencas):
    """Devuelve la lista de situaciones activas ahora (sin decidir aun si se envian)."""
    activas = []
    estaciones = []
    for e in salida.get("cbdmq", []) + salida.get("lluvia_epmaps", []):
        if e.get("sin_datos") or e.get("dato_anterior") or e.get("lat") is None:
            continue
        if e.get("retraso_min", 9999) > cfg["dato_maximo_atraso_min"]:
            continue
        parr, cue = ubicar(e, capas, cuencas)
        nombre = ("CBDMQ " if e.get("red") == "CBDMQ" else "") + e["nombre"]
        lugar = f'{parr["nombre"]}, brigada {parr["brigada"]}' if parr else "fuera de las parroquias del DMQ"
        estaciones.append({**e, "_nombre": nombre, "_lugar": lugar, "_cuenca": cue["id"] if cue else None})
        mm = e.get("lluvia_1h", 0) or 0
        nivel = sum(mm >= u for u in cfg["alerta_lluvia_1h_mm"])
        if nivel:
            activas.append({"tipo": "alerta", "clave": "alerta:" + nombre, "nivel": nivel, "estacion": nombre, "lugar": lugar,
                            "mm_1h": mm, "texto": f"{nombre} ({lugar}): {fmt(mm)} mm en la última hora"})
        elif mm >= cfg["aviso_lluvia_1h_mm"]:
            activas.append({"tipo": "aviso", "clave": "aviso:" + nombre, "nivel": 1, "estacion": nombre, "lugar": lugar,
                            "mm_1h": mm, "texto": f"{nombre} ({lugar}): {fmt(mm)} mm"})
        # condiciones propicias para lluvia en las 2 horas siguientes (solo estaciones CBDMQ, ver condiciones.py)
        cond = e.get("condiciones") or {}
        if cond.get("nivel"):
            p = cond.get("prob_historica") or (0.4 if cond["nivel"] == 2 else 0.25)
            veces = f"{max(1, round(p * 10))} de cada 10"
            senales = [f"humedad {cond['humedad']} %", f"faltan {fmt(cond['dif_rocio'])} °C para que el aire se sature"]
            if cond.get("caida_sol", 0) >= 0.1:
                senales.append("el sol se nubló de golpe")
            senales.append(f"el modelo anuncia {fmt(cond['mm_modelo_2h'])} mm")
            activas.append({"tipo": "condiciones", "clave": "condiciones:" + nombre, "nivel": cond["nivel"], "estacion": nombre,
                            "lugar": lugar, "mm_1h": 0,
                            "texto": (f"{'MUY PROPICIAS' if cond['nivel'] == 2 else 'Propicias'} - zona de {nombre} ({lugar}) y alrededores "
                                      f"(15 km): {', '.join(senales)}. En condiciones así llovió {veces} veces.")})
    # riesgo de crecida por microcuenca
    niveles = list(cfg["crecida_promedio_microcuenca_mm"].items())
    for c in cuencas:
        est = [e for e in estaciones if e["_cuenca"] == c["id"]]
        if not est:
            continue
        p3 = sum(e.get("lluvia_3h", 0) or 0 for e in est) / len(est)
        p24 = sum(e.get("lluvia_24h", 0) or 0 for e in est) / len(est)
        nivel, nombre_nivel = 0, None
        for k, (nn, u) in enumerate(niveles, 1):
            if p3 >= u["3h"] or p24 >= u["24h"]:
                nivel, nombre_nivel = k, nn
        if not nivel:
            continue
        # se muestra el recorrido hasta el Guayllabamba (despues sale del DMQ)
        rec = []
        for r in c["aguas_abajo"]:
            rec.append(r)
            if "Guayllabamba" in r or "Alambi" in r:
                break
        abajo = " → ".join(rec) if rec else "sale del DMQ"
        mayor = max(est, key=lambda e: e.get("lluvia_3h", 0) or 0)
        n_est = f"{len(est)} estaciones" if len(est) > 1 else "1 estación"
        activas.append({"tipo": "crecida", "clave": "crecida:" + c["rio"], "nivel": nivel, "nivel_nombre": nombre_nivel,
                        "rio": c["rio"], "lluvia_3h": round(p3, 1), "lluvia_24h": round(p24, 1), "aguas_abajo": c["aguas_abajo"],
                        "brigadas": c["brigadas"], "parroquias": c["parroquias"],
                        "texto": (f"{nombre_nivel.upper()} - {c['rio']}: lluvia promedio {fmt(p3)} mm en 3 h y {fmt(p24)} mm en 24 h "
                                  f"({n_est}; la mayor, {mayor['_nombre']}). El agua baja hacia: {abajo}. "
                                  f"Brigadas: {', '.join(c['brigadas'][:4])}.")})
    # estaciones de rios (caudal o nivel) creciendo fuerte o sobre el umbral; una linea por estacion
    vistos = set()
    for r in sorted(salida.get("rios", []), key=lambda r: -abs(r.get("cambio_6h_pct", 0))):
        if r["nombre"] in vistos:
            continue
        if r.get("retraso_min", 9999) > cfg["dato_maximo_atraso_min"]:
            continue
        alto = r.get("estado", "").startswith("Muy alto")
        if alto or (r.get("estado") == "Creciendo" and r.get("cambio_6h_pct", 0) >= 30):
            vistos.add(r["nombre"])
            signo = "+" if r["cambio_6h_pct"] >= 0 else ""
            var = (r.get("variable") or "").split(" ")[0].lower()
            activas.append({"tipo": "crecida", "clave": "rio:" + r["nombre"], "nivel": 3 if alto else 1, "rio": r["nombre"],
                            "texto": f"Estación de río {r['nombre']}: {r['estado'].lower()} ({var} {signo}{fmt(r['cambio_6h_pct'])} % en 6 h)"})
    return activas


def decidir(activas, estado, cfg, ahora):
    """Elige que se envia: lo nuevo, lo que subio de nivel o lo que sigue activo despues de unas horas."""
    enviar, nuevo_estado = [], {}
    for a in activas:
        prev = estado.get(a["clave"])
        repetir = prev and (ahora - dt.datetime.fromisoformat(prev["hora"])).total_seconds() >= cfg["repetir_aviso_cada_horas"] * 3600
        if not prev or a["nivel"] > prev["nivel"] or repetir:
            enviar.append(a)
            nuevo_estado[a["clave"]] = {"nivel": a["nivel"], "hora": ahora.isoformat(timespec="minutes")}
        else:
            nuevo_estado[a["clave"]] = prev
    return enviar, nuevo_estado


def armar_mensaje(items, ahora, cfg):
    u = cfg["alerta_lluvia_1h_mm"]
    partes = [f"*CBDMQ - Gestión de Riesgos*\n*Alerta de lluvias* {ahora.strftime('%d/%m/%Y %H:%M')}"]
    for nivel in (3, 2, 1):
        al = sorted([i for i in items if i["tipo"] == "alerta" and i["nivel"] == nivel], key=lambda i: -i["mm_1h"])
        if al:
            partes.append(f"🔵 *ALERTA NIVEL {nivel}* ({u[nivel - 1]} mm o más en 1 hora)\n" + "\n".join("• " + i["texto"] for i in al))
    cr = sorted([i for i in items if i["tipo"] == "crecida"], key=lambda i: -i["nivel"])
    if cr:
        partes.append("🌊 *RIESGO DE CRECIDA DE RÍOS*\n" + "\n".join("• " + i["texto"] for i in cr))
    co = sorted([i for i in items if i["tipo"] == "condiciones"], key=lambda i: -i["nivel"])
    if co:
        partes.append("🌥️ *Condiciones propicias para lluvia en las próximas 2 horas*\n" + "\n".join("• " + i["texto"] for i in co))
    av = sorted([i for i in items if i["tipo"] == "aviso"], key=lambda i: -i["mm_1h"])
    if av:
        txt = f"🟢 *Aviso: está lloviendo* ({cfg['aviso_lluvia_1h_mm']} mm o más en 1 hora)\n" + "\n".join("• " + i["texto"] for i in av[:15])
        if len(av) > 15:
            txt += f"\n• y {len(av) - 15} estaciones más"
        partes.append(txt)
    partes.append("Más detalle en el visualizador de lluvias.\n" + CREDITO)
    return "\n\n".join(partes)


def enviar_whatsapp(contacto, texto):
    url = ("https://api.callmebot.com/whatsapp.php?phone=" + urllib.parse.quote(contacto["telefono"]) +
           "&text=" + urllib.parse.quote(texto) + "&apikey=" + urllib.parse.quote(str(contacto["apikey"])))
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "CBDMQ-alertas"}), timeout=40) as r:
        resp = r.read().decode("utf8", "replace")
        if r.status != 200 or "ERROR" in resp.upper():
            raise RuntimeError(resp[:150])


def a_html(texto):
    """Pasa el formato *negrita* de los mensajes al formato de Telegram."""
    texto = texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"\*([^*\n]+)\*", r"<b>\1</b>", texto)


def enviar_telegram(token, chat_id, texto):
    # Telegram acepta hasta 4096 caracteres por mensaje: se parte por secciones si hace falta
    trozos, actual = [], ""
    for parte in texto.split("\n\n"):
        if actual and len(actual) + len(parte) > 3800:
            trozos.append(actual)
            actual = ""
        actual = (actual + "\n\n" + parte) if actual else parte
    trozos.append(actual)
    for trozo in trozos:
        datos = urllib.parse.urlencode({"chat_id": chat_id, "text": a_html(trozo), "parse_mode": "HTML",
                                        "disable_web_page_preview": "true"}).encode()
        try:
            with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", datos, timeout=40) as r:
                resp = json.loads(r.read().decode("utf8"))
        except urllib.error.HTTPError as e:
            resp = json.loads(e.read().decode("utf8", "replace") or "{}")
            nuevo = (resp.get("parameters") or {}).get("migrate_to_chat_id")
            if nuevo:  # el grupo paso a "supergrupo" y cambio de codigo: se actualiza y se reintenta
                actualizar_chat_id(chat_id, nuevo)
                return enviar_telegram(token, nuevo, texto)
        if not resp.get("ok"):
            raise RuntimeError(resp.get("description", "error de Telegram"))


def actualizar_chat_id(viejo, nuevo):
    ruta = os.path.join(CARPETA, "alertas_contactos.json")
    conf = json.load(open(ruta, encoding="utf8"))
    for d in conf.get("destinos", []):
        if str(d.get("chat_id")) == str(viejo):
            d["chat_id"] = str(nuevo)
    json.dump(conf, open(ruta, "w", encoding="utf8"), ensure_ascii=False, indent=2)
    anotar(f"Grupo actualizado a supergrupo: nuevo codigo {nuevo}")


def destinos_activos():
    """Personas o grupos que reciben: por Telegram (chat_id) o por WhatsApp (telefono + apikey)."""
    conf = leer("alertas_contactos.json", {}) or {}
    token = os.environ.get("TELEGRAM_TOKEN") or str(conf.get("telegram_token", ""))  # en GitHub viene de un "secreto"
    token = token if token and not token.startswith("PONER") else None
    lista = []
    for c in conf.get("destinos", []) + conf.get("contactos", []):
        if not c.get("activo"):
            continue
        if c.get("chat_id") and token:
            lista.append({**c, "_canal": "telegram"})
        elif c.get("apikey") and not str(c["apikey"]).startswith("PONER"):
            lista.append({**c, "_canal": "whatsapp"})
    return token, lista


def enviar(c, token, texto):
    if c["_canal"] == "telegram":
        enviar_telegram(token, c["chat_id"], texto)
    else:
        enviar_whatsapp(c, texto)


def procesar(salida, capas, prueba=False):
    cfg = leer("alertas_config.json")
    cuencas = leer("cuencas.json", [])
    ahora = dt.datetime.now()
    activas = evaluar(salida, capas, cfg, cuencas)
    estado = leer("estado_alertas.json", {})
    items, nuevo_estado = decidir(activas, estado, cfg, ahora)
    # por Telegram solo van las condiciones "muy propicias"; las "propicias" se ven en el visualizador
    items = [i for i in items if not (i["tipo"] == "condiciones" and i["nivel"] < cfg.get("condiciones_nivel_minimo_telegram", 2))]
    resumen = {"hora": ahora.strftime("%Y-%m-%d %H:%M"), "activas": activas, "enviadas": [], "error_envio": None}
    if items:
        resumen["mensaje"] = armar_mensaje(items, ahora, cfg)
        token, destinos = destinos_activos()
        if not destinos:
            anotar(f"{len(items)} avisos nuevos, pero no hay destinos activos en alertas_contactos.json")
        for c in destinos:
            mios = [i for i in items if i["tipo"] in c.get("recibe", ["aviso", "alerta", "crecida", "condiciones"])]
            if not mios:
                continue
            texto = armar_mensaje(mios, ahora, cfg)
            if prueba or not cfg.get("enviar_mensajes", True):
                print("--- mensaje para", c["nombre"], "---\n" + texto)
                continue
            for intento in range(3):
                try:
                    enviar(c, token, texto)
                    resumen["enviadas"].append(c["nombre"])
                    anotar(f"Enviado a {c['nombre']} ({c['_canal']}): {len(mios)} avisos")
                    break
                except Exception as ex:
                    if intento == 2:
                        resumen["error_envio"] = f"{c['nombre']}: {str(ex)[:120]}"
                        anotar(f"ERROR enviando a {c['nombre']}: {str(ex)[:120]}")
                    time.sleep(5)
            time.sleep(1)
    if not prueba:
        json.dump(nuevo_estado, open(os.path.join(CARPETA, "estado_alertas.json"), "w", encoding="utf8"), ensure_ascii=False, indent=1)
    return resumen


if __name__ == "__main__":
    vis = os.path.join(os.path.dirname(CARPETA), "visualizador", "datos")
    leer_js = lambda n: json.loads(open(os.path.join(vis, n), encoding="utf8").read().split("=", 1)[1].rstrip(";\n"))
    tr, capas = leer_js("tiempo_real.js"), leer_js("capas.js")
    if "--simular" in sys.argv:  # inventa lluvia fuerte para ver como queda el mensaje
        for e, (m1, m3, m24) in zip(tr["cbdmq"], [(24, 30, 45), (12, 18, 30), (3, 5, 8), (31, 40, 55)]):
            e.update(lluvia_1h=m1, lluvia_3h=m3, lluvia_24h=m24, retraso_min=5, dato_anterior=False, sin_datos=False)
    r = procesar(tr, capas, prueba=True)
    print(f"{len(r['activas'])} situaciones activas")
    print(r.get("mensaje", "(nada nuevo que avisar)"))

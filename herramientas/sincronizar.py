"""Copia el programa desde las carpetas de trabajo (D:) al proyecto de GitHub.

Copia solo codigo y archivos publicos. Los datos internos (capas con brigadas, emergencias, contactos)
NO se copian: se suben al almacen privado con subir_datos.py.
Ademas separa la pagina en dos: sitio/index.html (nivel 1, monitoreo) y sitio/historico/ (nivel 2).
Uso: python sincronizar.py   (con cualquier Python 3)
"""
import os
import re
import shutil

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIGEN = os.path.join("D:" + os.sep, "Documentos", "Procesos_ de_Contratación", "estacionesmeteorologicas")

CODIGO = {
    "visualizador/actualizar.py": "nube/visualizador/actualizar.py",
    "pronostico/pronostico_diario.py": "nube/pronostico/pronostico_diario.py",
    "pronostico/boletin_visual.py": "nube/pronostico/boletin_visual.py",
    "pronostico/calibracion.json": "nube/pronostico/calibracion.json",
    "pronostico/centros_poblados.json": "nube/pronostico/centros_poblados.json",
    "alertas/alertas.py": "nube/alertas/alertas.py",
    "alertas/enviar_pronostico.py": "nube/alertas/enviar_pronostico.py",
    "alertas/alertas_config.json": "nube/alertas/alertas_config.json",
    "alertas/cuencas.json": "nube/alertas/cuencas.json",
    "alertas/condiciones.py": "nube/alertas/condiciones.py",
    "alertas/condiciones_lluvia.json": "nube/alertas/condiciones_lluvia.json",
    "alertas/condiciones_paramh2o.json": "nube/alertas/condiciones_paramh2o.json",
    "boletin/boletin_diario.py": "nube/boletin/boletin_diario.py",
    "boletin/normales_lluvia.json": "nube/boletin/normales_lluvia.json",
    "boletin/secciones_epmaps.py": "nube/boletin/secciones_epmaps.py",
    "boletin/verificar_pronostico.py": "nube/boletin/verificar_pronostico.py",
    "boletin/informe_semanal.py": "nube/boletin/informe_semanal.py",
    "visualizador/estilo.css": "sitio/estilo.css",
    "visualizador/comun.js": "sitio/comun.js",
    "visualizador/app.js": "sitio/app.js",
    "visualizador/app_historico.js": "sitio/app_historico.js",
}


def copiar():
    for o, d in CODIGO.items():
        dest = os.path.join(RAIZ, d)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(os.path.join(ORIGEN, o), dest)
        print("copiado", d)


def quitar(html, patron):
    nuevo, n = re.subn(patron, "", html, flags=re.S)
    assert n, "no se encontro: " + patron[:60]
    return nuevo


def paginas():
    html = open(os.path.join(ORIGEN, "visualizador", "index.html"), encoding="utf8").read()
    html = html.replace('<meta charset="utf-8">', '<meta charset="utf-8">\n<meta name="robots" content="noindex, nofollow">')
    boton_m = '<button class="pestana activa" data-pagina="monitoreo">Monitoreo y pronóstico</button>'
    boton_h = '<button class="pestana" data-pagina="historico">Histórico: lluvias y emergencias</button>'
    assert boton_m in html and boton_h in html
    # ---- nivel 1: monitoreo
    m = quitar(html, r'\s*<!-- =+ PAGINA 2: HISTORICO =+ -->\s*<main id="historico".*?</main>')
    m = quitar(m, r'\s*<script src="datos/historico\.js"></script>')
    m = quitar(m, r'\s*<script src="datos/diario\.js"></script>')
    m = quitar(m, r'\s*<script src="app_historico\.js[^"]*"></script>')
    m = m.replace(boton_h, '<a class="pestana" href="historico/">Histórico: lluvias y emergencias</a>')
    enlace = ('<a class="enlace-boletin" href="{0}boletin/hoy" target="_blank">📄 Boletín de hoy (PDF)</a>\n    '
              '<a class="enlace-boletin" href="{0}informe/semana" target="_blank">📊 Informe semanal (PDF)</a>\n    ')
    m = m.replace('<span id="sesion"', enlace.format("") + '<span id="sesion"', 1)
    os.makedirs(os.path.join(RAIZ, "sitio", "historico"), exist_ok=True)
    open(os.path.join(RAIZ, "sitio", "index.html"), "w", encoding="utf8").write(m)
    # ---- nivel 2: historico (en /historico/, protegido aparte)
    h = quitar(html, r'\s*<!-- =+ PAGINA 1: MONITOREO =+ -->\s*<main id="monitoreo".*?</main>')
    h = quitar(h, r'\s*<script src="app\.js[^"]*"></script>')
    h = h.replace('<main id="historico" class="pagina">', '<main id="historico" class="pagina activa">')
    h = h.replace(boton_m, '<a class="pestana" href="../">Monitoreo y pronóstico</a>')
    h = h.replace(boton_h, '<button class="pestana activa">Histórico: lluvias y emergencias</button>')
    h = h.replace('href="estilo.css', 'href="../estilo.css').replace('src="comun.js', 'src="../comun.js')
    h = h.replace('src="app_historico.js', 'src="../app_historico.js').replace('src="datos/capas.js"', 'src="../datos/capas.js"')
    h = h.replace('<span id="actualizado">Cargando datos…</span>', '<span id="actualizado">Datos históricos 2018 – 2026</span>')
    h = h.replace('<span id="sesion"', enlace.format("../") + '<span id="sesion"', 1)
    open(os.path.join(RAIZ, "sitio", "historico", "index.html"), "w", encoding="utf8").write(h)
    print("paginas: sitio/index.html (nivel 1) y sitio/historico/index.html (nivel 2)")


if __name__ == "__main__":
    copiar()
    paginas()

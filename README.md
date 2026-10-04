# Visualizador de lluvias, ríos y emergencias – CBDMQ

Dirección de Gestión de Riesgos del Cuerpo de Bomberos del Distrito Metropolitano de Quito.
Elaborado por: **Diana Lozada Ramos**.

Este repositorio contiene **solo el programa**. No contiene claves ni datos internos: las claves están
en los *secretos* de GitHub y los datos internos (coberturas de brigadas, emergencias, contactos de
Telegram) en un almacén privado de Cloudflare.

## Qué hace

| Proceso | Cuándo | Qué hace |
|---|---|---|
| `Actualizar datos y alertas` | cada 10 minutos | Lluvia de las estaciones CBDMQ (LI-COR) y EPMAPS, caudal y nivel de ríos, pronóstico por parroquia y alertas por Telegram (10/20/30 mm en una hora y riesgo de crecida por microcuenca). |
| `Pronóstico diario` | 6h00 de Quito | Boletín de pronóstico (hoy, mañana y pasado mañana) por brigada distrital; se envía al grupo de Telegram. |
| `Publicar página` | al cambiar el diseño | Publica la página en Cloudflare Pages. |

GitHub a veces retrasa unos minutos las tareas programadas.

## Acceso a la página (registro por niveles)

La página está protegida con **Cloudflare Access**: cada persona entra con su correo y un código que
le llega en ese momento. Solo entran los correos autorizados.

* **Nivel 1 – Operativo**: monitoreo en vivo, ríos, pronóstico y alertas activas (dirección principal).
* **Nivel 2 – Completo**: además, el histórico de lluvias y emergencias (`/historico/`).

Los usuarios se agregan o quitan en Cloudflare → Zero Trust → Access → Access Groups.

## Carpetas

* `sitio/` página web (nivel 1 en la raíz, nivel 2 en `historico/`).
* `functions/` entrega los datos del almacén privado a la página (solo a usuarios autorizados).
* `nube/` programas que corren en GitHub (copias de las carpetas de trabajo en la computadora).
* `herramientas/` se usan desde la computadora:
  * `sincronizar.py` copia el programa desde las carpetas de trabajo a este repositorio.
  * `subir_datos.py` sube al almacén privado las capas, el histórico y los contactos de Telegram
    (por ejemplo, después de registrar a alguien nuevo con `registrar_telegram.bat`).

## Secretos necesarios (GitHub → Settings → Secrets and variables → Actions)

`CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `LICOR_TOKEN`, `TELEGRAM_TOKEN`.

## Fuentes

Estaciones CBDMQ (LI-COR), EPMAPS (paraMH2O y telemetría), REMMAQ (Secretaría de Ambiente), modelos
ICON, Météo-France y GFS (Open-Meteo) corregidos con las estaciones del DMQ, ríos de OpenStreetMap y
microcuencas del DMQ.

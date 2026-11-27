# STK-01B — Dependencias y compatibilidad

## Versiones y alcance

La referencia de `main` es `19e9dc4829ac63d05177eb589144457af1954e9a`. El objetivo verificado es CPython 3.11 con Django 5.2 LTS.

| Componente | Antes | Después y motivo |
| --- | --- | --- |
| Django | `>=5.2.8`; el entorno tenía 5.2.19 | **5.2.19**, última versión estable de la serie en PyPI al verificarla el 27 de noviembre de 2026 |
| Ejecución y pruebas | 62 paquetes instalados en Linux; 25 dependencias directas con límites mínimos | Las mismas 62 versiones en Linux con Python 3.11.18, fijadas con hashes SHA-256. Se incluyeron las dependencias condicionales del resolvedor |
| pip | 24.0 en la imagen Docker base; 26.3 en el `venv` nuevo de Codex | **26.3** con hash, para corregir los avisos del instalador de la imagen base |
| setuptools | 79.0.1 en el `venv` limpio y la imagen base | **84.2.1** con hash, para corregir los avisos de la herramienta de instalación |
| Python en `render.yaml` | 3.11.0 | **3.11.18**, mismo parche probado localmente y en Docker |
| Bootstrap | 5.3.0 | **5.3.9**, actualización de parche de la serie 5.3 con SRI |
| SortableJS y ZXing | CDN con `@latest` | **1.15.7** y **0.23.0**, los tags estables observados en npm, con SRI |
| Bootstrap Icons y Chart.js | 1.11.0 y 4.4.0 | Versiones conservadas y verificación SRI agregada |

Las dependencias directas están en [requirements.in](../../requirements.in). El bloqueo [requirements.txt](../../requirements.txt) contiene las versiones exactas y hashes de las distribuciones, incluidas las transitivas. Se mantuvo un único conjunto para aplicación y pruebas porque CI y Codex comparten el flujo existente. El [bloqueo de instalación](../../requirements-bootstrap.txt) separa pip y setuptools para actualizar ambas herramientas antes de instalar la aplicación. El trabajo independiente de lint de CI queda fuera de estos bloqueos.

Se conservaron OpenCV, Pillow, pytesseract, pdf2image, Celery, Redis y django-redis. La aplicación usa OpenCV para imágenes y pdf2image para convertir PDF con Poppler. Se agregó `libgl1` a Docker porque la distribución de OpenCV enlaza con `libGL.so.1`. Se podrá evaluar `opencv-python-headless` tras verificar equivalencia del OCR. Retirar Celery, Redis o sus clientes requeriría revisar por separado las tareas, el broker y la caché.

## Seguridad

Se usó `pip-audit 2.10.1` con el servicio oficial de PyPI. Los avisos con identificadores duplicados se contaron una sola vez.

| Instalación consultada | Resultado |
| --- | --- |
| Entorno Codex original | 62 paquetes de aplicación, 0 avisos |
| Instalación limpia con las herramientas iniciales de `venv` | 2 avisos distintos en setuptools 79.0.1: CVE-2026-59890 y GHSA-xmj3-9gf7-h52w |
| pip 24.0 de la imagen Docker base | 6 CVE en PyPI: CVE-2025-8869, CVE-2026-1703, CVE-2026-3219, CVE-2026-6357, CVE-2026-8643 y CVE-2026-13346 |
| Instalación final en Linux | 64 paquetes incluidos pip y setuptools, 0 avisos, 0 paquetes omitidos |

También se consultaron en PyPI las tres entradas condicionales que no se cargaron en Linux con Python 3.11.18: colorama 0.4.6, async-timeout 5.0.1 y NumPy 2.5.5. No se devolvieron avisos activos. Las [notas oficiales de Django 5.2.19](https://github.com/django/django/blob/stable/5.2.x/docs/releases/5.2.19.txt) documentan cinco correcciones de seguridad frente a 5.2.18. El bloqueo garantiza que una instalación nueva conserva esos parches, que ya estaban presentes en el entorno original.

El [servicio de avisos de npm](https://docs.npmjs.com/cli/commands/npm-audit#bulk-advisory-endpoint) no devolvió avisos para las versiones directas CDN consultadas antes y después. Los siete tags externos de scripts y estilos tienen ahora SRI y `crossorigin="anonymous"`. Se comprobaron sus hashes contra los archivos servidos y las interfaces de ZXing, SortableJS y Chart.js usadas por los templates. La auditoría de paquetes no cubre los componentes nativos de Debian, Tesseract, Poppler ni las bibliotecas embebidas en wheels o bundles.

## Instalación reproducible

Usa un entorno virtual con Python 3.11. Una vez activado, instala primero las herramientas y luego la aplicación.

```bash
python -m pip install --only-binary=:all: --no-deps --require-hashes -r requirements-bootstrap.txt
python -m pip install --require-hashes -r requirements.txt
python -m pip check
```

En un entorno Codex cuyo venv no contiene pip se puede usar `uv`. Créalo en una ruta nueva para evitar cambios en un entorno de trabajo existente.

```bash
stockex_venv="$(mktemp -d)/venv"
uv venv --python 3.11 "$stockex_venv"
uv pip sync --require-hashes --python "$stockex_venv/bin/python" requirements-bootstrap.txt requirements.txt
uv pip check --python "$stockex_venv/bin/python"
```

Para actualizar de forma controlada, edita el `.in` correspondiente y regenera con `uv 0.13.9`. Revisa el diff de las transitivas, repite la auditoría de PyPI y prueba ambos motores.

```bash
uv pip compile requirements.in --universal --python-version 3.11 --generate-hashes -o requirements.txt
uv pip compile requirements-bootstrap.in --universal --python-version 3.11 --generate-hashes -o requirements-bootstrap.txt
```

Para OCR instala Tesseract con `spa` y `eng` y Poppler con `pdfinfo` y `pdftoppm` en el PATH. Verifica los idiomas con `tesseract --list-langs`. Docker instala los paquetes de sistema en el contenedor. En Codex, si se usa la instalación de idiomas del entorno, configura `TESSDATA_PREFIX` para apuntar a esa carpeta.

## Verificación local

CPython 3.11.18, Django 5.2.19, SQLite 3.53.1 y PostgreSQL 15.20 en un contenedor temporal. La compilación desde cero reprodujo ambos archivos de bloqueo. La instalación limpia con pip y la sincronización con uv pasaron sus comprobaciones de dependencias. La resolución para Windows x86-64 también pasó en simulación con wheels.

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --noinput
python -m pytest -o addopts='' --migrations -q
```

| Comprobación | SQLite | PostgreSQL 15 |
| --- | --- | --- |
| Django `check` y migraciones pendientes | Sin problemas ni cambios | Sin problemas ni cambios |
| Migraciones desde base vacía | Hasta `0017` | Hasta `0017` |
| Suite completa | 73 aprobadas, 6 fallidas | 73 aprobadas, 6 fallidas |

Los seis fallos coinciden con STK-01A: representación de cliente, tres pruebas de propiedades de cuentas por cobrar, cotización sin vencimiento y contrato de búsqueda global. Las 55 advertencias de cada ejecución correspondieron al directorio de estáticos sin recopilar en la copia aislada.

El OCR de PNG y PDF sintéticos extrajo el texto esperado en Codex y Docker con Tesseract 5.5.0 y OpenCV 5.1.0. Poppler fue 26.05.0 en Codex y 25.03.0 en Docker. La imagen se compiló usando una copia temporal del Dockerfile con la CA del proxy montada como secreto de BuildKit. La comprobación del contenedor, incluido el OCR, se ejecutó sin red. La configuración de Render se revisó estáticamente y la ejecución de Windows queda sin verificar.

## Reversión

Si se detecta una incompatibilidad, revierte el commit en una rama de recuperación, conserva un entorno virtual anterior o reinstala desde su bloqueo y vuelve a verificar con bases aisladas. Conserva las versiones corregidas de pip y setuptools al preparar ese entorno. La etapa no requiere una reversión de esquema.

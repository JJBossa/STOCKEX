#!/usr/bin/env bash
# Build script para Render

set -o errexit  # Exit on error

# Opcional: Instalar Tesseract OCR (descomenta si necesitas OCR)
# apt-get update && apt-get install -y tesseract-ocr tesseract-ocr-spa

# Instalar dependencias Python
pip install -r requirements.txt

# Recolectar archivos estáticos
python manage.py collectstatic --no-input --clear

# Ejecutar migraciones
python manage.py migrate --no-input

# Importar datos si existe el archivo datos_exportados.json (migración desde SQLite local)
# Esto permite migrar productos automáticamente sin necesidad de shell
if [ -f "datos_exportados.json" ]; then
    echo "Archivo datos_exportados.json encontrado. Importando datos..."
    python manage.py importar_datos datos_exportados.json || echo "Advertencia: Error al importar datos (puede ser que ya existan)"
fi

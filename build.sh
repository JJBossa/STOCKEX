#!/usr/bin/env bash
# Build script para Render

set -o errexit  # Exit on error

# Opcional: Instalar Tesseract OCR (descomenta si necesitas OCR)
# apt-get update && apt-get install -y tesseract-ocr tesseract-ocr-spa

# Instalar dependencias Python
python -m pip install --only-binary=:all: --no-deps --require-hashes -r requirements-bootstrap.txt
python -m pip install --require-hashes -r requirements.txt
python -m pip check

# Recolectar archivos estáticos
python manage.py collectstatic --no-input --clear

# Ejecutar migraciones
python manage.py migrate --no-input

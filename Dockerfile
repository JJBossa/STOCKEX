# Dockerfile para STOCKEX
FROM python:3.11-slim

# Variables de entorno
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

# Directorio de trabajo
WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-spa \
    libtesseract-dev \
    poppler-utils \
    libpoppler-cpp-dev \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements y instalar dependencias Python
COPY requirements-bootstrap.txt requirements.txt ./
RUN python -m pip install --no-cache-dir --only-binary=:all: --no-deps --require-hashes -r requirements-bootstrap.txt \
    && python -m pip install --no-cache-dir --require-hashes -r requirements.txt \
    && python -m pip check

# Copiar el proyecto
COPY . .

# Crear directorios necesarios
RUN mkdir -p /app/media /app/staticfiles /app/logs

# Exponer puerto
EXPOSE 8000

# Comando por defecto (puede ser sobrescrito)
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "control_stock.wsgi:application"]


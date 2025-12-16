# ¿Qué se Instala Automáticamente en Render?

## ✅ Lo que Render hace AUTOMÁTICAMENTE durante el deploy

Cuando Render ejecuta el `build.sh`, automáticamente se hace:

1. **Instalación de dependencias Python**
   ```bash
   pip install -r requirements.txt
   ```
   - Instala Django, gunicorn, whitenoise, psycopg2-binary, dj-database-url, Pillow, openpyxl, reportlab, pytesseract, pdf2image, opencv-python, etc.

2. **Recolección de archivos estáticos**
   ```bash
   python manage.py collectstatic --no-input --clear
   ```
   - Recolecta todos los archivos estáticos (CSS, JS, imágenes) en `staticfiles/`
   - WhiteNoise los servirá automáticamente

3. **Ejecución de migraciones**
   ```bash
   python manage.py migrate --no-input
   ```
   - Crea todas las tablas en la base de datos PostgreSQL
   - Aplica todas las migraciones automáticamente

4. **Inicio del servidor**
   ```bash
   gunicorn control_stock.wsgi:application
   ```
   - Render inicia el servidor automáticamente

---

## ✅ Creación Automática de Superusuario

**El superusuario se crea AUTOMÁTICAMENTE** durante el build mediante el comando `crear_superusuario`.

### Configuración (Opcional pero Recomendado)

Para personalizar las credenciales del superusuario, agrega estas variables de entorno en Render:

- **SUPERUSER_USERNAME**: Username (default: `admin`)
- **SUPERUSER_EMAIL**: Email (default: `admin@example.com`)
- **SUPERUSER_PASSWORD**: Password (**IMPORTANTE**: Define una contraseña segura)

**Si no defines `SUPERUSER_PASSWORD`, se usará `admin123` por defecto.**

⚠️ **IMPORTANTE**: Define siempre `SUPERUSER_PASSWORD` en Render con una contraseña segura.

### Comandos Iniciales Opcionales

Si necesitas ejecutar comandos personalizados como crear categorías o importar productos:

**Desde el Shell de Render:**
```bash
python manage.py crear_categorias
python manage.py importar_productos
```

**O puedes agregarlos al build.sh** (se ejecutarán en cada deploy):
```bash
# Agregar al final de build.sh:
python manage.py crear_categorias --no-input
```

---

## 🔧 Configuraciones Adicionales

### Tesseract OCR

Si necesitas OCR para procesar facturas:

1. **Descomentar en build.sh:**
   ```bash
   # Cambiar de:
   # apt-get update && apt-get install -y tesseract-ocr tesseract-ocr-spa
   
   # A:
   apt-get update && apt-get install -y tesseract-ocr tesseract-ocr-spa
   ```

2. **Hacer commit y push** del cambio

3. **Render hará el rebuild automáticamente**

---

## 📋 Checklist Post-Deploy

Después del primer deploy, verifica:

- [ ] El servicio web está "Live" (verde) en Render
- [ ] Puedes acceder a tu URL de Render (ej: `tu-app.onrender.com`)
- [ ] Puedes hacer login en `/login/` con las credenciales del superusuario
- [ ] Puedes acceder al admin en `/admin/`
- [ ] Los archivos estáticos se cargan correctamente (CSS, imágenes)
- [ ] Las migraciones se ejecutaron (verifica en los logs)
- [ ] El superusuario se creó automáticamente (usa las credenciales por defecto o las que configuraste)

---

## 🚨 Si algo falla

### Ver logs en tiempo real:
1. En Render Dashboard → Tu servicio web → "Logs"
2. Verás errores en tiempo real durante el build y runtime

### Errores comunes:

**Error: "No module named 'xxx'"**
- Verifica que todas las dependencias estén en `requirements.txt`

**Error: "DisallowedHost"**
- Verifica que `ALLOWED_HOSTS` incluya tu dominio de Render

**Error: "relation does not exist"**
- Las migraciones no se ejecutaron. Verifica en los logs del build
- Ejecuta manualmente: `python manage.py migrate` desde el Shell

**Error: "static files not found"**
- Verifica que `collectstatic` se ejecutó correctamente
- Revisa los logs del build

---

## ✅ Resumen

**Automático (sin hacer nada):**
- ✅ Instalación de dependencias
- ✅ Recolección de archivos estáticos
- ✅ Ejecución de migraciones
- ✅ Inicio del servidor

**Manual (solo una vez después del deploy):**
- ⚠️ Crear superusuario
- ⚠️ (Opcional) Ejecutar comandos personalizados iniciales

**Todo lo demás se hace automáticamente en cada deploy.**


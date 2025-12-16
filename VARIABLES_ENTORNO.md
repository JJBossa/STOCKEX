# Variables de Entorno Requeridas

Este documento describe las variables de entorno necesarias para configurar la aplicación en Render.

## Variables Requeridas

### SECRET_KEY
- **Descripción**: Clave secreta de Django para firmar cookies y otros elementos sensibles
- **Valor por defecto**: Se usa una clave por defecto (NO recomendado para producción)
- **Cómo generar una nueva**:
  ```bash
  python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
  ```
- **Ejemplo**: `django-insecure-abcdefghijklmnopqrstuvwxyz1234567890`

### DEBUG
- **Descripción**: Activa/desactiva el modo debug de Django
- **Valor por defecto**: `False`
- **Valores permitidos**: `True` o `False` (como string)
- **Recomendación**: Siempre usar `False` en producción
- **Ejemplo**: `False`

### ALLOWED_HOSTS
- **Descripción**: Lista de hosts permitidos separados por comas
- **Valor por defecto**: `localhost,127.0.0.1`
- **Formato**: Lista separada por comas sin espacios extra
- **Ejemplo**: `tu-app.onrender.com,www.tu-app.onrender.com`
- **Nota**: Render proporcionará una URL como `tu-app-xxxx.onrender.com`. Asegúrate de incluirla aquí.

### DATABASE_URL
- **Descripción**: URL de conexión a la base de datos PostgreSQL
- **Valor por defecto**: None (usa SQLite localmente)
- **Formato**: `postgresql://user:password@host:port/dbname`
- **Ejemplo**: `postgresql://user:pass@dpg-xxxxx-a.render.com:5432/dbname`
- **Nota**: Render proporciona esta variable automáticamente si configuras la base de datos como dependencia del servicio web, o puedes copiarla manualmente desde el panel de la base de datos.

### SUPERUSER_USERNAME (Opcional)
- **Descripción**: Username para el superusuario que se creará automáticamente
- **Valor por defecto**: `admin`
- **Ejemplo**: `admin`

### SUPERUSER_EMAIL (Opcional)
- **Descripción**: Email para el superusuario que se creará automáticamente
- **Valor por defecto**: `admin@example.com`
- **Ejemplo**: `admin@tudominio.com`

### SUPERUSER_PASSWORD (Recomendado)
- **Descripción**: Password para el superusuario que se creará automáticamente
- **Valor por defecto**: `admin123` (⚠️ NO usar en producción)
- **Recomendación**: **SIEMPRE** define esta variable en Render con una contraseña segura
- **Ejemplo**: `MiPasswordSeguro123!`
- **Nota**: Si no defines esta variable, se usará `admin123` por defecto. El comando `crear_superusuario` solo crea el usuario si no existe, por lo que es seguro ejecutarlo múltiples veces.

## Configuración en Render

1. Ve a tu servicio web en Render
2. Navega a la sección "Environment"
3. Agrega cada variable con su valor correspondiente
4. Guarda los cambios

## Notas Importantes

- **NUNCA** commitees valores reales de estas variables al repositorio
- Usa el archivo `.gitignore` para asegurarte de que `.env` no se suba al repositorio
- En producción, siempre usa una `SECRET_KEY` única y segura
- `DEBUG=False` es esencial para seguridad en producción
- **SUPERUSER_PASSWORD**: Define siempre esta variable en Render con una contraseña segura para evitar usar el valor por defecto

## Creación Automática de Superusuario

El proyecto incluye un comando `crear_superusuario` que se ejecuta automáticamente durante el build. Este comando:
- Crea un superusuario solo si no existe (es seguro ejecutarlo múltiples veces)
- Usa las variables de entorno `SUPERUSER_USERNAME`, `SUPERUSER_EMAIL`, y `SUPERUSER_PASSWORD`
- Si no defines `SUPERUSER_PASSWORD`, usa `admin123` por defecto (⚠️ cambia esto en producción)

**No necesitas crear el superusuario manualmente** - se crea automáticamente en cada deploy.


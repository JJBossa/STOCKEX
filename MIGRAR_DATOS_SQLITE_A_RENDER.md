# Guía: Migrar Datos de SQLite Local a PostgreSQL en Render

Esta guía te ayudará a transferir tus productos y datos existentes desde tu base de datos SQLite local a PostgreSQL en Render.

---

## 📋 Paso 1: Exportar Datos desde tu Base de Datos Local

### 1.1 Asegúrate de estar usando SQLite localmente

Verifica que `settings.py` NO tenga `DATABASE_URL` configurada, para que use SQLite.

### 1.2 Ejecuta el comando de exportación

En tu terminal local, desde la raíz del proyecto:

```bash
python manage.py exportar_datos
```

Esto creará un archivo `datos_exportados.json` en la raíz del proyecto con todos tus datos:
- ✅ Categorías
- ✅ Productos
- ✅ Proveedores
- ✅ Facturas
- ✅ Items de factura

---

## 📤 Paso 2: Subir el Archivo JSON a Render

### Opción A: Usar Git (Recomendado)

1. **Agrega el archivo al repositorio temporalmente:**
   ```bash
   git add datos_exportados.json
   git commit -m "Agregar datos exportados para migración"
   git push origin main
   ```

2. **Después de importar, elimínalo del repositorio:**
   ```bash
   git rm datos_exportados.json
   git commit -m "Remover datos exportados después de migración"
   git push origin main
   ```

**⚠️ Nota:** Esto expondrá temporalmente tus datos. Si prefieres mantenerlos privados, usa la Opción B.

### Opción B: Usar Render Shell (Requiere plan de pago)

Si tienes acceso al shell de Render:
1. Sube el archivo usando `scp` o desde el dashboard
2. Ejecuta el comando de importación desde el shell

### Opción C: Base64 Encoding (Para datos pequeños)

Si tienes pocos productos, puedes:
1. Convertir el JSON a base64
2. Copiarlo como variable de entorno temporal
3. Decodificarlo y guardarlo en Render

---

## 📥 Paso 3: Importar Datos en Render (AUTOMÁTICO)

✅ **El proceso de importación es AUTOMÁTICO** - no necesitas hacer nada manual.

El `build.sh` ya está configurado para importar datos automáticamente si encuentra el archivo `datos_exportados.json`.

### ¿Qué pasa automáticamente?

1. **Render detecta el archivo** `datos_exportados.json` en el repositorio
2. **Durante el build**, ejecuta automáticamente: `python manage.py importar_datos datos_exportados.json`
3. **El comando verifica** si ya existen productos:
   - Si **NO hay productos**, importa todos los datos
   - Si **ya hay productos**, no importa (para evitar duplicados)
4. **Los datos se importan** en el orden correcto (categorías → proveedores → productos → facturas → items)

### Si necesitas forzar la importación (reimportar)

Si quieres forzar la importación aunque ya existan datos, puedes eliminar temporalmente los productos existentes o ejecutar:

```bash
python manage.py importar_datos datos_exportados.json --clear
```

⚠️ **Nota:** `--clear` eliminará todos los datos existentes antes de importar.

---

## 🔄 Paso 4: Verificar la Importación

1. Accede a tu aplicación en Render
2. Haz login con `bossa` / `bossa123`
3. Verifica que todos los productos aparezcan
4. Verifica categorías, proveedores, facturas, etc.

---

## ⚠️ Consideraciones Importantes

### 1. Relaciones con Usuarios

Los productos y otros datos pueden tener relaciones con usuarios. Si los IDs de usuario son diferentes entre SQLite y PostgreSQL, es posible que necesites:

- Reimportar los usuarios primero, o
- Ajustar las relaciones después de la importación

### 2. Archivos Media (Imágenes)

Los archivos media (imágenes de productos, facturas) **NO se migran** con este método. Necesitarás:

1. Subirlos a un servicio de almacenamiento en la nube (S3, Cloudinary, etc.), o
2. Subirlos manualmente después de la migración

### 3. Historial de Cambios

Si tienes `HistorialCambio` con muchas entradas, también se exportarán e importarán.

---

## 🛠️ Solución de Problemas

### Error: "Foreign key constraint failed"

Esto significa que hay dependencias faltantes. Asegúrate de importar en este orden:
1. Categorías
2. Proveedores
3. Productos
4. Facturas
5. Items de factura

El comando `importar_datos` ya lo hace en el orden correcto.

### Error: "User does not exist"

Si algunos registros hacen referencia a usuarios que no existen:
- Los usuarios se crean automáticamente (`bossa` y `user1`)
- Si usas otros usuarios, créalos primero

### Los productos no aparecen

1. Verifica que la importación se completó sin errores
2. Verifica que estás usando el usuario correcto (`bossa`)
3. Revisa los logs de Render para ver si hubo errores

---

## ✅ Resumen del Proceso (TODO AUTOMÁTICO)

1. ✅ Ejecuta `python manage.py exportar_datos` localmente
2. ✅ Sube `datos_exportados.json` a Git: `git add datos_exportados.json && git commit -m "Datos para migración" && git push`
3. ✅ **Render importa automáticamente** durante el build (sin necesidad de shell)
4. ✅ Verifica que los datos aparezcan en tu aplicación
5. ✅ (Opcional) Elimina `datos_exportados.json` del repositorio después de verificar:
   ```bash
   git rm datos_exportados.json
   git commit -m "Remover datos exportados después de migración exitosa"
   git push
   ```

**¡Todo es automático! No necesitas usar el Shell de Render.**

---

## 🎯 Alternativa Rápida: Usar el Comando de Importación Existente

Si tus productos vienen del comando `importar_productos`, puedes simplemente ejecutarlo en Render después del deploy para recrear los productos básicos.


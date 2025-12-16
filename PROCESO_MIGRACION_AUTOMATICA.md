# Proceso de Migración Automática de Datos

## 🚀 Proceso Completo (Todo Automático)

### Paso 1: Exportar Datos Localmente

En tu computadora local, ejecuta:

```bash
python manage.py exportar_datos
```

Esto creará el archivo `datos_exportados.json` con todos tus productos, categorías, proveedores, facturas, etc.

### Paso 2: Subir a GitHub

```bash
git add datos_exportados.json
git commit -m "Agregar datos exportados para migración automática"
git push origin main
```

### Paso 3: Render Importa Automáticamente

Cuando Render haga el deploy:

1. ✅ Detecta el archivo `datos_exportados.json`
2. ✅ Ejecuta automáticamente `python manage.py importar_datos datos_exportados.json`
3. ✅ Verifica si ya existen productos:
   - Si **NO hay productos**: Importa todos los datos
   - Si **ya hay productos**: No importa (para evitar duplicados)
4. ✅ Importa en el orden correcto:
   - Categorías
   - Proveedores
   - Productos
   - Facturas
   - Items de factura

### Paso 4: Verificar

1. Accede a tu aplicación en Render
2. Haz login con `bossa` / `bossa123`
3. Verifica que todos los productos aparezcan

### Paso 5: Limpiar (Opcional)

Después de verificar que todo funciona:

```bash
git rm datos_exportados.json
git commit -m "Remover datos exportados después de migración exitosa"
git push origin main
```

---

## ⚠️ Notas Importantes

### El proceso es inteligente

- **No duplica datos**: Si ya hay productos, no importa nuevamente
- **Idempotente**: Puedes ejecutarlo múltiples veces sin problemas
- **Seguro**: Solo importa si no hay datos existentes

### Si necesitas reimportar

Si necesitas forzar la importación (por ejemplo, después de eliminar datos):

1. Elimina los datos manualmente desde el admin, o
2. Usa el flag `--clear` (pero esto requiere shell, que no tienes en plan free)

### Archivos Media (Imágenes)

⚠️ **Las imágenes de productos NO se migran automáticamente.**

Los productos se importarán, pero las imágenes quedarán sin referencias. Tendrás que:
- Subirlas manualmente después, o
- Configurar un servicio de almacenamiento en la nube (S3, Cloudinary, etc.)

---

## ✅ Ventajas de este Proceso

- ✅ **100% Automático** - No necesitas Shell
- ✅ **Funciona en plan free** de Render
- ✅ **No duplica datos** - Solo importa si no hay datos existentes
- ✅ **Seguro** - Puedes ejecutarlo múltiples veces
- ✅ **Orden correcto** - Respeta dependencias entre modelos

---

## 📋 Checklist

- [ ] Ejecuté `python manage.py exportar_datos` localmente
- [ ] Archivo `datos_exportados.json` creado exitosamente
- [ ] Subí el archivo a GitHub
- [ ] Render hizo deploy automáticamente
- [ ] Los datos se importaron correctamente
- [ ] Puedo ver todos los productos en la aplicación
- [ ] (Opcional) Eliminé `datos_exportados.json` del repositorio

---

## 🎯 Resultado Final

Después de completar estos pasos, tendrás:

- ✅ Usuario `bossa` / `bossa123` (administrador)
- ✅ Usuario `user1` / `u.123456` (normal)
- ✅ Todos tus productos migrados
- ✅ Todas tus categorías migradas
- ✅ Todos tus proveedores migrados
- ✅ Todas tus facturas migradas

**¡Todo funcionando en Render sin necesidad de Shell!**


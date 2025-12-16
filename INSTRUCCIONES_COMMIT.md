# Instrucciones para Commit y Deploy

## 📋 Archivos a Agregar al Commit

### Archivos Modificados:
- ✅ `build.sh` - Agregado comando crear_superusuario
- ✅ `control_stock/settings.py` - Configuración para Render
- ✅ `requirements.txt` - Dependencias para Render
- ✅ `.gitignore` - Agregado .env
- ✅ `render.yaml` - Configuración de Render
- ✅ `DEPLOY_RENDER.md` - Documentación actualizada
- ✅ `RESUMEN_DEPLOYMENT.md` - Resumen actualizado
- ✅ `VARIABLES_ENTORNO.md` - Documentación de variables

### Archivos Nuevos:
- ✅ `inventario/management/commands/crear_superusuario.py` - **IMPORTANTE** - Crea superusuario automáticamente
- ✅ `QUE_SE_INSTALA_AUTOMATICAMENTE.md` - Documentación
- ✅ `SOLUCION_SIN_SHELL.md` - Documentación
- ✅ `CAMBIOS_DEPLOYMENT.md` - Documentación
- ✅ `INSTRUCCIONES_COMMIT.md` - Este archivo

---

## 🚀 Comandos para Commit

### 1. Agregar todos los archivos necesarios:

```bash
git add build.sh
git add control_stock/settings.py
git add requirements.txt
git add .gitignore
git add render.yaml
git add inventario/management/commands/crear_superusuario.py
git add *.md
```

**O simplemente:**
```bash
git add .
```

### 2. Verificar qué se va a commitear:

```bash
git status
```

### 3. Hacer commit:

```bash
git commit -m "Preparar proyecto para deployment en Render con creación automática de superusuario

- Configurar variables de entorno en settings.py
- Agregar dependencias para Render (gunicorn, whitenoise, psycopg2-binary, dj-database-url)
- Configurar STATIC_ROOT y WhiteNoise para archivos estáticos
- Agregar build.sh para Render con creación automática de superusuario
- Crear comando crear_superusuario.py para plan free (sin shell)
- Configurar soporte para PostgreSQL con fallback a SQLite
- Agregar documentación completa de deployment"
```

### 4. Push a GitHub:

```bash
git push origin main
```

---

## ✅ Después del Push

Si ya tienes Render conectado a tu repositorio:

1. **Render detectará automáticamente el nuevo commit**
2. **Iniciará un nuevo build automáticamente**
3. **El build ejecutará:**
   - Instalación de dependencias
   - `collectstatic`
   - `migrate`
   - `crear_superusuario` ← **NUEVO** - crea el superusuario automáticamente

### Si NO tienes Render conectado aún:

Sigue las instrucciones en `DEPLOY_RENDER.md` para:
1. Crear la base de datos PostgreSQL
2. Crear el servicio web
3. Conectar el repositorio
4. Configurar variables de entorno

---

## ⚠️ IMPORTANTE: Variables de Entorno en Render

Después del deploy, **agrega estas variables de entorno en Render**:

```
SECRET_KEY=<genera-una-nueva>
DEBUG=False
ALLOWED_HOSTS=tu-app-xxxx.onrender.com
DATABASE_URL=<se-provide-automaticamente-si-conectas-la-bd>
SUPERUSER_PASSWORD=TuPasswordSeguro123!  ← IMPORTANTE!
```

**Opcionales (pero recomendadas):**
```
SUPERUSER_USERNAME=admin
SUPERUSER_EMAIL=admin@tudominio.com
```

---

## 🎯 Lo que Cambiará Después del Commit

✅ **En el próximo deploy de Render:**
- Se creará el superusuario automáticamente
- No necesitarás usar el Shell (que es de pago)
- Podrás hacer login inmediatamente después del deploy

✅ **El proyecto funcionará igual localmente:**
- Sin cambios en el funcionamiento local
- Todo sigue igual para desarrollo

---

## 📝 Checklist Final

- [ ] Todos los archivos modificados están listos
- [ ] El comando `crear_superusuario.py` está creado
- [ ] `build.sh` incluye el comando crear_superusuario
- [ ] Hiciste commit de todos los cambios
- [ ] Hiciste push a GitHub
- [ ] Render está conectado al repositorio (o lo configurarás)
- [ ] Variables de entorno configuradas en Render (después del deploy)


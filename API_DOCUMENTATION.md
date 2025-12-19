# Documentación de la API REST

## 📋 Resumen

Se ha implementado una API REST completa usando Django REST Framework que está **en paralelo** con los endpoints existentes. Los endpoints originales siguen funcionando normalmente.

## 🔐 Autenticación

La API soporta dos métodos de autenticación:

### 1. Autenticación por Sesión (para uso desde navegador)
```bash
# Se usa automáticamente si estás logueado en el sitio web
GET /api/v1/productos/
```

### 2. Autenticación JWT (para aplicaciones externas)
```bash
# Obtener token
POST /api/v1/auth/token/
{
    "username": "usuario",
    "password": "contraseña"
}

# Respuesta
{
    "access": "eyJ0eXAiOiJKV1QiLCJhbGc...",
    "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}

# Usar token en requests
GET /api/v1/productos/
Headers: Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...

# Refrescar token
POST /api/v1/auth/token/refresh/
{
    "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

## 📚 Endpoints Disponibles

### Productos

#### Listar productos
```http
GET /api/v1/productos/
```

**Parámetros de consulta:**
- `search`: Búsqueda en nombre, SKU, descripción
- `categoria`: ID de categoría
- `activo`: true/false (default: true)
- `stock_bajo`: true (solo productos con stock bajo)
- `ordering`: nombre, precio, stock, fecha_creacion
- `page`: Número de página

**Ejemplo:**
```bash
GET /api/v1/productos/?search=producto&categoria=1&stock_bajo=true&ordering=-precio
```

#### Obtener un producto
```http
GET /api/v1/productos/{id}/
```

#### Crear producto (Solo admin bossa)
```http
POST /api/v1/productos/
Content-Type: application/json

{
    "nombre": "Nuevo Producto",
    "descripcion": "Descripción",
    "categoria": 1,
    "precio": 10000,
    "precio_compra": 5000,
    "stock": 50,
    "stock_minimo": 10,
    "activo": true
}
```

#### Actualizar producto (Solo admin bossa)
```http
PUT /api/v1/productos/{id}/
PATCH /api/v1/productos/{id}/
```

#### Eliminar producto (Solo admin bossa)
```http
DELETE /api/v1/productos/{id}/
```

#### Actualizar stock
```http
POST /api/v1/productos/{id}/actualizar_stock/
{
    "cantidad": 10,
    "tipo": "entrada"  // entrada, salida, ajuste
}
```

### Categorías

```http
GET /api/v1/categorias/          # Listar
GET /api/v1/categorias/{id}/     # Detalle
POST /api/v1/categorias/         # Crear (solo bossa)
PUT /api/v1/categorias/{id}/     # Actualizar (solo bossa)
DELETE /api/v1/categorias/{id}/  # Eliminar (solo bossa)
```

### Ventas

```http
GET /api/v1/ventas/              # Listar (solo lectura)
GET /api/v1/ventas/{id}/         # Detalle
```

**Nota:** Para crear ventas, usar el endpoint existente `/pos/procesar-venta/`

**Filtros:**
- `metodo_pago`: efectivo, tarjeta, transferencia, mixto
- `cancelada`: true/false
- `usuario`: ID de usuario

### Cotizaciones

```http
GET /api/v1/cotizaciones/        # Listar
GET /api/v1/cotizaciones/{id}/   # Detalle
POST /api/v1/cotizaciones/       # Crear
PUT /api/v1/cotizaciones/{id}/   # Actualizar
DELETE /api/v1/cotizaciones/{id}/ # Eliminar
```

**Filtros:**
- `estado`: pendiente, aprobada, rechazada, vencida
- `usuario`: ID de usuario

### Movimientos de Stock

```http
GET /api/v1/movimientos-stock/   # Listar (solo lectura)
GET /api/v1/movimientos-stock/{id}/ # Detalle
```

**Filtros:**
- `tipo`: entrada, salida, ajuste, perdida, devolucion
- `motivo`: compra, venta, ajuste_inventario, etc.
- `producto`: ID de producto

### Notificaciones de Stock

```http
GET /api/v1/notificaciones-stock/        # Listar (solo lectura)
GET /api/v1/notificaciones-stock/{id}/    # Detalle
POST /api/v1/notificaciones-stock/{id}/marcar_vista/ # Marcar como vista
```

**Filtros:**
- `vista`: true/false
- `notificada`: true/false

### Proveedores

```http
GET /api/v1/proveedores/         # Listar
GET /api/v1/proveedores/{id}/    # Detalle
POST /api/v1/proveedores/        # Crear (solo bossa)
PUT /api/v1/proveedores/{id}/    # Actualizar (solo bossa)
DELETE /api/v1/proveedores/{id}/ # Eliminar (solo bossa)
```

## 📝 Ejemplos de Uso

### Python (requests)
```python
import requests

# Autenticación
response = requests.post('http://localhost:8000/api/v1/auth/token/', {
    'username': 'usuario',
    'password': 'contraseña'
})
token = response.json()['access']

# Obtener productos
headers = {'Authorization': f'Bearer {token}'}
response = requests.get('http://localhost:8000/api/v1/productos/', headers=headers)
productos = response.json()
```

### JavaScript (fetch)
```javascript
// Autenticación
const response = await fetch('/api/v1/auth/token/', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
        username: 'usuario',
        password: 'contraseña'
    })
});
const {access} = await response.json();

// Obtener productos
const productosResponse = await fetch('/api/v1/productos/', {
    headers: {'Authorization': `Bearer ${access}`}
});
const productos = await productosResponse.json();
```

### cURL
```bash
# Obtener token
curl -X POST http://localhost:8000/api/v1/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username":"usuario","password":"contraseña"}'

# Usar token
curl -X GET http://localhost:8000/api/v1/productos/ \
  -H "Authorization: Bearer YOUR_TOKEN_HERE"
```

## 🔒 Permisos

- **Lectura (GET)**: Todos los usuarios autenticados
- **Escritura (POST, PUT, DELETE)**: Solo usuario `bossa` (admin)
- **Ventas**: Los usuarios solo ven sus propias ventas (excepto bossa)
- **Cotizaciones**: Los usuarios solo ven sus propias cotizaciones (excepto bossa)

## 📊 Paginación

Todas las listas están paginadas (20 items por página):

```json
{
    "count": 100,
    "next": "http://localhost:8000/api/v1/productos/?page=2",
    "previous": null,
    "results": [...]
}
```

## 🔍 Búsqueda y Filtrado

- **Búsqueda**: Usa el parámetro `search` (busca en múltiples campos)
- **Filtrado**: Usa los filtros específicos de cada endpoint
- **Ordenamiento**: Usa `ordering` con el nombre del campo (prefijo `-` para descendente)

## ⚠️ Notas Importantes

1. **Endpoints existentes siguen funcionando**: La API REST está en paralelo, no reemplaza los endpoints actuales
2. **Misma autenticación**: Usa el mismo sistema de usuarios de Django
3. **Mismos permisos**: Respeta las mismas reglas de negocio (es_admin_bossa)
4. **Compatibilidad**: Puedes usar ambos sistemas simultáneamente

## 🧪 Testing

Los endpoints de la API están cubiertos por tests. Para ejecutar:

```bash
pytest tests/test_api.py -v
```


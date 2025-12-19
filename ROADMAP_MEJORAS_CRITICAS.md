# Roadmap de Mejoras Críticas para Competir

## 🎯 Objetivo: Hacer STOCKEX Competitivo en el Mercado

---

## FASE 1: Sistema de Clientes (2-3 semanas) 🔴 CRÍTICO

### Modelo Cliente
```python
class Cliente(models.Model):
    nombre = models.CharField(max_length=200)
    rut = models.CharField(max_length=20, unique=True)
    email = models.EmailField()
    telefono = models.CharField(max_length=50)
    direccion = models.TextField()
    tipo_cliente = models.CharField(...)  # Natural, Empresa
    limite_credito = models.DecimalField(...)
    fecha_registro = models.DateTimeField(auto_now_add=True)
    activo = models.BooleanField(default=True)
```

### Funcionalidades
- [ ] CRUD completo de clientes
- [ ] Búsqueda avanzada de clientes
- [ ] Historial de compras por cliente
- [ ] Total gastado por cliente
- [ ] Clientes frecuentes
- [ ] Integrar con ventas y cotizaciones

### Impacto
- ✅ Permite ventas recurrentes
- ✅ Base para cuentas por cobrar
- ✅ Reportes por cliente

---

## FASE 2: Cuentas por Cobrar (2-3 semanas) 🔴 CRÍTICO

### Modelos
```python
class CuentaPorCobrar(models.Model):
    cliente = models.ForeignKey(Cliente)
    venta = models.ForeignKey(Venta, null=True)
    monto_total = models.DecimalField(...)
    monto_pagado = models.DecimalField(...)
    fecha_vencimiento = models.DateField()
    estado = models.CharField(...)  # Pendiente, Parcial, Pagado, Vencido
    notas = models.TextField()

class PagoCliente(models.Model):
    cuenta_por_cobrar = models.ForeignKey(CuentaPorCobrar)
    monto = models.DecimalField(...)
    fecha_pago = models.DateTimeField(auto_now_add=True)
    metodo_pago = models.CharField(...)
    notas = models.TextField()
```

### Funcionalidades
- [ ] Registrar créditos en ventas
- [ ] Pagos parciales
- [ ] Estados de cuenta
- [ ] Alertas de vencimiento
- [ ] Reporte de cuentas por cobrar
- [ ] Historial de pagos

### Impacto
- ✅ Permite ventas a crédito
- ✅ Control de cobranza
- ✅ Mejora flujo de caja

---

## FASE 3: Facturación Electrónica - SII Chile (4-6 semanas) 🔴 CRÍTICO (Solo si es para Chile)

### Integración con SII
- [ ] Generar DTE (Documento Tributario Electrónico)
- [ ] Folios electrónicos
- [ ] Envío automático al SII
- [ ] Consulta de estado de envío
- [ ] Reenvío de documentos

### Modelos
```python
class DTE(models.Model):
    venta = models.ForeignKey(Venta)
    folio = models.IntegerField(unique=True)
    tipo_dte = models.IntegerField(...)  # 33, 34, 52, etc.
    estado_envio = models.CharField(...)  # Pendiente, Enviado, Aceptado, Rechazado
    xml = models.TextField()
    respuesta_sii = models.TextField()
    fecha_envio = models.DateTimeField(null=True)
```

### Librerías Necesarias
- `libxml2` o `lxml` para XML
- `cryptography` para firma
- `requests` para envío al SII

### Impacto
- ✅ Cumplimiento legal en Chile
- ✅ Requisito para muchos negocios
- ✅ Competitividad en mercado chileno

---

## FASE 4: Múltiples Almacenes (2-3 semanas) 🟡 IMPORTANTE

### Modelo Almacén
```python
class Almacen(models.Model):
    nombre = models.CharField(max_length=200)
    codigo = models.CharField(max_length=20, unique=True)
    direccion = models.TextField()
    activo = models.BooleanField(default=True)

class StockAlmacen(models.Model):
    producto = models.ForeignKey(Producto)
    almacen = models.ForeignKey(Almacen)
    cantidad = models.IntegerField()
    stock_minimo = models.IntegerField()

class Transferencia(models.Model):
    almacen_origen = models.ForeignKey(Almacen, related_name='transferencias_salida')
    almacen_destino = models.ForeignKey(Almacen, related_name='transferencias_entrada')
    producto = models.ForeignKey(Producto)
    cantidad = models.IntegerField()
    fecha = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(User)
    estado = models.CharField(...)  # Pendiente, En tránsito, Completada
```

### Funcionalidades
- [ ] CRUD de almacenes
- [ ] Stock por almacén
- [ ] Transferencias entre almacenes
- [ ] Reportes por almacén
- [ ] Ajustes de inventario por almacén

### Impacto
- ✅ Escalabilidad
- ✅ Negocios con múltiples ubicaciones
- ✅ Mejor control de inventario

---

## FASE 5: Módulo de Compras (2-3 semanas) 🟡 IMPORTANTE

### Modelos
```python
class OrdenCompra(models.Model):
    numero_orden = models.CharField(unique=True)
    proveedor = models.ForeignKey(Proveedor)
    fecha_orden = models.DateField()
    fecha_esperada = models.DateField()
    estado = models.CharField(...)  # Pendiente, Parcial, Completa, Cancelada
    total = models.DecimalField(...)
    notas = models.TextField()

class ItemOrdenCompra(models.Model):
    orden = models.ForeignKey(OrdenCompra)
    producto = models.ForeignKey(Producto)
    cantidad = models.IntegerField()
    precio_unitario = models.DecimalField(...)
    cantidad_recibida = models.IntegerField(default=0)
    subtotal = models.DecimalField(...)

class RecepcionMercancia(models.Model):
    orden_compra = models.ForeignKey(OrdenCompra)
    fecha_recepcion = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(User)
    notas = models.TextField()
```

### Funcionalidades
- [ ] Crear órdenes de compra
- [ ] Recepción de mercancía
- [ ] Actualización automática de stock
- [ ] Historial de compras
- [ ] Reportes de compras

### Impacto
- ✅ Planificación de compras
- ✅ Control de proveedores
- ✅ Mejor gestión de inventario

---

## FASE 6: Integración con Sistemas de Pago (3-4 semanas) 🟡 IMPORTANTE

### Integración Transbank (Chile)
- [ ] Webpay Plus
- [ ] OneClick
- [ ] Lectores de tarjeta
- [ ] Procesamiento de pagos

### Modelos
```python
class TransaccionPago(models.Model):
    venta = models.ForeignKey(Venta)
    token = models.CharField(max_length=200)
    monto = models.DecimalField(...)
    estado = models.CharField(...)  # Pendiente, Aprobada, Rechazada
    respuesta_transbank = models.JSONField()
    fecha_transaccion = models.DateTimeField(auto_now_add=True)
```

### Impacto
- ✅ Aceptar tarjetas de crédito/débito
- ✅ Pagos en línea
- ✅ Mejor experiencia de cliente

---

## 📊 Resumen de Roadmap

| Fase | Funcionalidad | Tiempo | Prioridad | Impacto Competitivo |
|------|---------------|--------|-----------|---------------------|
| 1 | Sistema de Clientes | 2-3 semanas | 🔴 Crítica | Alto |
| 2 | Cuentas por Cobrar | 2-3 semanas | 🔴 Crítica | Alto |
| 3 | Facturación Electrónica | 4-6 semanas | 🔴 Crítica* | Muy Alto* |
| 4 | Múltiples Almacenes | 2-3 semanas | 🟡 Importante | Medio |
| 5 | Módulo de Compras | 2-3 semanas | 🟡 Importante | Medio |
| 6 | Integración Pagos | 3-4 semanas | 🟡 Importante | Medio |

**Total estimado:** 15-22 semanas (4-6 meses)

*Solo si el mercado objetivo es Chile

---

## 🎯 Plan de Implementación Recomendado

### Sprint 1-2: Clientes (3 semanas)
- Semana 1-2: Modelo y CRUD
- Semana 3: Integración con ventas

### Sprint 3-4: Cuentas por Cobrar (3 semanas)
- Semana 4-5: Modelos y funcionalidad básica
- Semana 6: Reportes y alertas

### Sprint 5-8: Facturación Electrónica (6 semanas) - Solo si es para Chile
- Semana 7-9: Integración con SII
- Semana 10-12: Testing y validación

### Sprint 9-10: Almacenes (3 semanas)
- Semana 13-14: Modelos y transferencias
- Semana 15: Reportes

### Sprint 11-12: Compras (3 semanas)
- Semana 16-17: Órdenes de compra
- Semana 18: Recepción

### Sprint 13-14: Pagos (4 semanas)
- Semana 19-21: Integración Transbank
- Semana 22: Testing

---

## 💡 Recomendación

**Para competir básicamente:**
- ✅ Fase 1 (Clientes) - **2-3 semanas**
- ✅ Fase 2 (Cuentas por Cobrar) - **2-3 semanas**
- ✅ Fase 3 (Facturación Electrónica) - **4-6 semanas** (solo si es para Chile)

**Total: 8-12 semanas (2-3 meses)**

Con estas 3 fases, el sistema puede competir con software de $50-100/mes para negocios pequeños/medianos.

---

## 🚀 ¿Empezamos con la Fase 1?

La implementación del sistema de clientes es relativamente rápida y tiene alto impacto. ¿Quieres que la implementemos?


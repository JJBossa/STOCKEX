# STK-04A — Núcleo seguro de registro de ventas

`Venta` registra la modalidad `rapida` o `detallada`, el vendedor autenticado, la fecha generada por Django y los importes de la operación. Cada número nuevo usa un UUID v4 con prefijo `V-` y una restricción de unicidad en la base de datos. Las ventas rápidas guardan el importe directamente y tienen cero líneas. En las detalladas, cada `ItemVenta` guarda su relación con el producto, el nombre, la cantidad, el precio unitario vigente y el subtotal.

## Servicio y contrato HTTP

`registrar_venta(usuario, clave, datos)` valida permisos y datos y devuelve la venta, sus líneas y un indicador de reintento. La vista `POST /pos/registrar-venta/` recibe JSON UTF-8, una sesión de Django, la cookie CSRF junto con `X-CSRFToken` y un UUID v4 en `Idempotency-Key`. El permiso `inventario.registrar_venta` se asigna a Administrador y Vendedor mediante `python manage.py crear_grupos_permisos` después de migrar.

Venta rápida por $900 en efectivo con $1.000 recibidos.

```json
{"modalidad":"rapida","metodo_pago":"efectivo","monto":900,"monto_recibido":1000}
```

Venta detallada a partir de la selección de dos unidades de un producto de $1.

```json
{"modalidad":"detallada","metodo_pago":"tarjeta","items":[{"producto_id":42,"cantidad":2,"precio_visto":1}]}
```

`precio_visto` corresponde al campo `precio` de `GET /api/catalogo-productos/`. Es obligatorio para confirmar el precio que vio el vendedor. El servicio lee el precio base actual de la base de datos y calcula los importes en el servidor. Si cambió el precio, la respuesta 409 incluye `error: "precio_cambiado"` y `productos` con `producto_id` y `precio_vigente` por cada diferencia. La interfaz debe mostrar los cambios y esperar confirmación explícita antes de volver a enviar. Una lista con productos duplicados se rechaza. Un producto inexistente o inactivo produce 409 y devuelve los IDs afectados.

HTTP 201 indica una venta nueva y HTTP 200 indica un reintento idempotente. Ambos devuelven `id`, `numero_venta`, `modalidad`, `usuario_id`, `fecha` ISO 8601, `subtotal`, `total`, `metodo_pago`, `monto_recibido`, `cambio`, `items` y `repetida`. Cada línea incluye `producto_id`, `nombre_producto`, `cantidad`, `precio_unitario` y `subtotal`, en orden de ID de producto. Los importes JSON son enteros CLP.

| HTTP | Motivo |
| --- | --- |
| 302 | Sesión ausente, con redirección al login |
| 400 | Clave inválida, JSON malformado, campos inválidos o pago inválido |
| 403 | Permiso ausente o validación CSRF fallida |
| 405 | Método distinto de POST para una sesión autorizada |
| 409 | Precio cambiado, producto indisponible, precio de catálogo inválido o clave ya usada con otra solicitud |
| 413 | Cuerpo mayor de 16 KiB |
| 415 | Tipo de contenido distinto de `application/json` |
| 503 | Espera agotada por bloqueo de SQLite, con `Retry-After: 1` |

Los errores de negocio incluyen `error` y `mensaje` con los detalles aplicables. Para `entero_invalido`, `campo` identifica el dato rechazado. La ruta heredada `/pos/procesar-venta/` permanece suspendida. La API REST de historial y Django Admin restringen las ventas a la lectura. Las suspensiones de cancelaciones, eliminaciones de historial, conversiones de cotizaciones, devoluciones, créditos y abonos siguen vigentes.

## Pagos, importes e inventario

- `efectivo` usa el total como importe exacto si el navegador omite `monto_recibido`. Si se envía, debe ser igual o superior al total. El servidor calcula `cambio = monto_recibido - total`.
- `tarjeta` y `transferencia` registran el total como recibido y el cambio como cero. Un monto explícito debe coincidir con el total. El registro es contable y se realiza sin procesar el pago.
- Los importes deben ser enteros positivos. El límite por venta o monto recibido es $999.999.999.999. El precio unitario y el subtotal de línea admiten hasta $9.999.999.999. Se admiten hasta 100 líneas, una por producto, y cantidades enteras de 1 a 1.000.000. Los IDs positivos caben en un entero de 64 bits con signo.
- Se rechazan booleanos, cadenas numéricas, fracciones, números JSON con parte decimal, campos desconocidos y propiedades JSON duplicadas. Se preserva el precio de $1. El cálculo usa aritmética entera, suma de subtotales y descuento cero.
- El catálogo activo admite productos con stock cero. Registrar ventas prescinde de consultas de disponibilidad, descuentos de stock y movimientos de inventario. Las nuevas líneas guardan `stock_anterior` y `stock_despues` en `NULL`. El detalle histórico los presenta con un guion cuando no se registraron.

## Idempotencia y concurrencia

`RegistroVenta` reserva la clave por vendedor mediante una restricción única en base de datos. Guarda una huella SHA-256 de la solicitud válida normalizada y se vincula a una única venta. El orden de propiedades JSON y el de las líneas carecen de efecto sobre la huella. Omitir `monto_recibido` y enviarlo explícitamente son solicitudes distintas. Un HTTP 200 recupera la venta y los precios originales aunque haya cambiado el catálogo. Con la misma clave y otros datos válidos se devuelve 409 `clave_en_conflicto`. Las ventas consecutivas con claves distintas se registran por separado.

La reserva, la venta y la inserción en bloque de los ítems se confirman en una transacción. Una segunda solicitud concurrente con la misma clave espera la resolución de la primera. Si la primera confirma, la segunda recupera ese resultado o informa conflicto. Si la primera falla, su clave y sus registros se revierten y otro intento puede continuar. Para reintentar tras un error de transporte o un 503 hay que conservar la clave y el cuerpo de la operación.

En PostgreSQL, la consulta de catálogo bloquea los productos por ID ascendente con `SELECT FOR UPDATE`, hasta confirmar o revertir la venta. Así, una modificación concurrente de nombre, precio o estado queda ordenada con respecto a la venta. SQLite carece de bloqueos de fila. La reserva, primera operación de escritura de la transacción, adquiere el bloqueo de escritor de SQLite antes de leer el catálogo. Una espera que supere el límite devuelve 503 para reintentar con la misma clave. Las pruebas específicas de bloqueos de fila corren en PostgreSQL.

## Compatibilidad y migración

`0018_nucleo_seguro_ventas` agrega la modalidad nullable, la reserva de idempotencia, el permiso y los campos de stock nullable. Los registros existentes conservan valores, números, relaciones y métodos de pago históricos. Su modalidad queda en `NULL`. Las relaciones existentes con productos y clientes se protegen frente al borrado para conservar la referencia histórica. Los productos asociados se pueden desactivar por las vías habituales del catálogo. Las cuentas de usuarios se desactivan desde la interfaz de gestión, lo que preserva la atribución.

Para aplicar la migración, ejecutar `python manage.py migrate --noinput` y luego `python manage.py crear_grupos_permisos`. Antes de revertir, suspender el tráfico de escritura, respaldar la base y conservar los metadatos de idempotencia si ya se registraron ventas. Revertir el código en una rama de recuperación con la migración aplicada conserva los metadatos. Si se necesita revertir también el esquema, usar `python manage.py migrate inventario 0017`. Esa reversión conserva las ventas, líneas e importes. Elimina la modalidad y las claves, y convierte a cero únicamente los valores de stock `NULL` para ajustarse al esquema previo. Volver a aplicar `0018` deja las ventas resultantes con modalidad desconocida y no restaura claves antiguas.

## Pruebas y rendimiento

La suite completa pasó con **170 pruebas aprobadas y 5 omitidas en SQLite**, y **175 aprobadas en PostgreSQL 15.20**. Las cinco pruebas específicas de PostgreSQL usan conexiones independientes y cubren ventas simultáneas con claves distintas, reintentos con la misma clave, conflicto por cambio de contenido y escrituras concurrentes de precio y estado. En ambos motores se verificó un fallo durante la escritura de líneas con rollback de la venta y la reserva, junto con el avance, la reversión y la reaplicación de `0018` con datos sintéticos históricos y nuevos. Pasaron `pip check`, `manage.py check`, `makemigrations --check --dry-run` y `scripts/check_lint.py`.

Una prueba adicional con SQLite en archivo y dos conexiones obtuvo 201 y 200 para envíos simultáneos con la misma clave. Con el bloqueo de escritura sostenido, se verificó el 503 y el registro exitoso al reintentar después de liberar el bloqueo.

Mediciones locales con el cliente Django autenticado, 10 llamadas de calentamiento y 50 medidas por operación y motor. Las consultas incluyen sesión, permisos y control de transacción. Los tiempos no incluyen transporte HTTP externo.

| Operación | SQLite p50 / p95 (ms) | PostgreSQL p50 / p95 (ms) | SQL por petición |
| --- | ---: | ---: | ---: |
| Rápida | 7,74 / 11,27 | 11,22 / 14,78 | 9 |
| Detallada, 1 producto | 9,08 / 10,76 | 12,63 / 19,26 | 11 |
| Detallada, 5 productos | 8,68 / 11,08 | 12,96 / 16,62 | 11 |
| Detallada, 20 productos | 9,65 / 13,09 | 14,39 / 25,68 | 11 |
| Reintento de rápida | 4,50 / 5,89 | 9,83 / 18,53 | 8 |
| Reintento de detallada, 20 productos | 5,51 / 8,54 | 10,80 / 16,10 | 9 |

## STK-04B

Integrar el buscador instantáneo, la captura del monto y método de pago, el manejo de claves y reintentos por operación, la nueva confirmación ante cambios de precio y la presentación del comprobante desde la interfaz definitiva.

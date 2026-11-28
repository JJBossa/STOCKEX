# STK-05B · Anulación segura de ventas

La anulación corrige el registro interno de ventas. El historial conserva el número, la hora, el vendedor, el medio de pago, los importes y las líneas de la operación original. El ajuste no mueve inventario ni devuelve dinero.

## Auditoría y permisos

La migración `inventario.0020_anulacion_segura_ventas` agrega `AnulacionVenta` con una relación única a `Venta`, el usuario responsable, la fecha del servidor y el motivo de hasta 250 caracteres. Las referencias a la venta y al responsable tienen protección contra borrado. La base exige un único registro por venta y rechaza el motivo vacío. El servicio recorta espacios externos, rechaza textos en blanco, exceso de longitud y caracteres nulos, y usa exclusivamente la identidad autenticada y la hora del servidor. El detalle muestra el motivo como texto escapado y las fechas en `America/Santiago`.

El permiso `inventario.anular_venta` se asigna inicialmente a Administrador por migración y por el comando `crear_grupos_permisos`. Vendedor conserva el acceso de lectura a sus ventas. Una delegación explícita del permiso continúa limitada al alcance de `ventas_visibles`, que también exige `inventario.view_venta`. En una instalación nueva, configura la matriz completa con `python manage.py crear_grupos_permisos` después de migrar.

El formulario usa la ruta existente `POST /ventas/<id>/cancelar/`, con autenticación y CSRF. La venta es de solo lectura en Django Admin y la API REST. El registro de anulación se consulta desde el detalle de la venta. Las operaciones financieras suspendidas por STK-01A y STK-04A conservan su bloqueo.

## Elegibilidad y concurrencia

`inventario/anulacion_ventas.py` concentra la elegibilidad y la vuelve a verificar dentro de la transacción. Se admiten ventas en efectivo, tarjeta o transferencia. Se bloquean crédito, pagos mixtos, medios desconocidos, cuentas por cobrar, devoluciones, cotizaciones convertidas y movimientos de lote vinculados. También se bloquean las líneas históricas que registran un cambio de stock o tienen solo una de las dos existencias registradas. Los asientos de idempotencia de STK-04A se conservan junto a su venta original.

PostgreSQL obtiene un bloqueo de fila con `SELECT … FOR UPDATE` después de aplicar el alcance del usuario. SQLite obtiene primero el bloqueo de escritor mediante un `UPDATE` que no afecta filas y, si está ocupada, propone consultar el estado antes de reintentar. En la misma transacción se actualiza únicamente `Venta.cancelada` y se inserta la auditoría. Cualquier fallo revierte ambos cambios.

| Resultado | Respuesta para el formulario con JavaScript |
| --- | --- |
| Nueva anulación confirmada | `201` con el identificador y estado persistido |
| Reintento de la misma venta, actor y motivo normalizado | `200` con `repetida=true`, conservando la auditoría original |
| Motivo inválido | `400` |
| Venta anulada con otros datos, anulación histórica o dependencias incompatibles | `409` |
| SQLite ocupado | `503` con `Retry-After` |

Si se pierde la respuesta, el formulario conserva el motivo y bloquea el envío mientras el usuario comprueba el estado. La consulta lee el detalle autorizado desde Django sin caché. Si ya está anulada, el detalle muestra la auditoría registrada. Si sigue vigente, vuelve a habilitar la confirmación. El formulario HTML también funciona sin JavaScript y, al confirmar, redirige al detalle. Los filtros y la página acompañan los enlaces y el formulario.

## Historial e indicadores

Las ventas históricas con `cancelada=True` se muestran como anulaciones históricas sin información disponible. La migración evita rellenar esa auditoría. `resumir_ventas` calcula desde la base el total y la cantidad vigentes, el promedio, el desglose por medio y el monto y la cantidad anulados. El historial mantiene la venta y su total original. El orden por compras del listado de clientes excluye anuladas, al igual que los reportes y las exportaciones de ventas vigentes. Las rutas directas de tickets térmicos y A4 responden `404` para ventas anuladas, en consonancia con las acciones del detalle.

## Preparación para STK-06

`impedimento_anulacion` es el punto de extensión para rechazar una venta con un cierre de caja confirmado. Cuando exista la sesión de caja, el cierre y la anulación deberán bloquear esa misma sesión antes de tomar las filas de ventas en orden por ID. Ambos deberán volver a consultar el estado bajo esos bloqueos. Así, una anulación confirmada primero queda fuera del total vigente del cierre, y un cierre confirmado primero impide cambiarlo. El registro de ventas de esa sesión deberá respetar el mismo orden para estabilizar el conjunto incluido en el cierre.

## Verificación y rendimiento local

| Motor | Línea base | Resultado STK-05B |
| --- | --- | --- |
| SQLite | 199 aprobadas, 5 omitidas | 227 aprobadas, 6 omitidas |
| PostgreSQL 15.20 | 204 aprobadas | 233 aprobadas |

La omisión adicional en SQLite corresponde a la prueba de bloqueo de fila de PostgreSQL. En PostgreSQL, dos solicitudes HTTP autenticadas con distintos responsables y motivos compitieron por la misma venta. Se observó la espera mediante `pg_blocking_pids`, seguida de una respuesta `201` y otra `409` con una única auditoría. Se comprobó además el rollback tras un fallo de inserción y el acceso por alcance y CSRF. La prueba de STK-01A que antes esperaba la suspensión genérica de anulación conserva la protección de la venta con cuenta por cobrar y ahora verifica el rechazo específico y la ausencia de cambios.

Se ejecutaron `pip check`, `manage.py check`, `makemigrations --check --dry-run`, migraciones reales desde bases vacías y `scripts/check_lint.py`. Se retiraron únicamente entradas obsoletas de la línea base de lint. La prueba de Chromium con Django real verificó permisos, confirmación, doble envío, pérdida de respuesta antes y después de guardar, historial y formulario sin JavaScript. Se comprobaron 390, 768, 1366 y 1920 px en claro y oscuro.

Para repetir el recorrido de navegador, usa `node tests/browser/anulacion-venta.mjs` con Playwright y Chromium. El script crea una base SQLite temporal y genera sus propios datos. Acepta `PYTHON`, `PLAYWRIGHT_MODULE`, `CHROMIUM_PATH` y `POS_CDN_LOCAL` para los recursos fijados de Bootstrap e iconos.

Medianas de 20 solicitudes por operación y modalidad. La venta detallada sintética tuvo 10 líneas. La medición usa el cliente de pruebas de Django autenticado como Administrador e incluye middleware, consultas de sesión y control transaccional. SQLite usa la base de pruebas y PostgreSQL 15.20 corre en un contenedor local.

| Operación | SQLite · mediana / SQL | PostgreSQL 15.20 · mediana / SQL |
| --- | --- | --- |
| Anular venta rápida | 7,56 ms / 16 | 15,54 ms / 15 |
| Anular venta detallada | 6,98 ms / 16 | 15,43 ms / 15 |
| Reintentar anulación rápida | 5,07 ms / 10 | 10,58 ms / 9 |
| Reintentar anulación detallada | 5,09 ms / 10 | 11,11 ms / 9 |
| Consultar estado de venta rápida | 8,87 ms / 9 | 15,71 ms / 9 |
| Consultar estado de venta detallada | 9,06 ms / 9 | 16,22 ms / 9 |

Para repetir la medición, ejecuta `python -m pytest -q -s tests/test_anulacion_ventas.py::test_medicion_solicitudes_anulacion` con la configuración de base de pruebas del motor correspondiente.

## Migraciones y reversión

Aplica la nueva migración con `python manage.py migrate`. Se verificó en ambos motores el recorrido `0019 → 0020 → 0019 → 0020` con ventas sintéticas. Si se necesita retirar la función, suspende primero los POST de anulación y conserva la migración aplicada para mantener la auditoría consultable.

**Revertir el esquema a `0019` elimina la tabla `inventario_anulacionventa` y el permiso de anulación.** Antes de hacerlo, crea un respaldo consistente de la tabla, de sus referencias a ventas y usuarios y de las concesiones del permiso. Verifica la posibilidad de restaurarlos. Las ventas conservan `cancelada=True` y sus importes. Reaplicar `0020` por sí sola crea una tabla vacía, por lo que esas ventas aparecerán como anulaciones históricas hasta restaurar la auditoría.

## Límites

El ajuste es interno. Las reversas de pago, los fiados, la reposición de stock y los cierres de caja requieren sus propios flujos. Las diferencias históricas de stock solo pueden bloquearse cuando los registros permiten detectarlas. La protección de la auditoría en las interfaces de STOCKEX se complementa con los permisos operativos de acceso directo a la base de datos.

# STK-06A · Núcleo de cierres de caja

## Sesiones y ventas

`SesionCaja` representa la única caja del negocio. La sesión está abierta mientras `cerrada_en` sea nulo. Un índice único parcial garantiza como máximo una abierta en PostgreSQL y SQLite. La apertura guarda el efectivo inicial, el responsable, la hora del servidor y una observación opcional. Al confirmar el cierre se completan juntos sus campos de auditoría y la instantánea financiera. Las referencias entre la sesión, sus responsables, sus ventas y sus movimientos usan protección contra eliminación.

La jornada comienza con una apertura explícita y termina con un cierre explícito. Puede atravesar medianoche y los cambios de hora. La pertenencia de una venta se define por la clave foránea, con independencia de su fecha civil. Django guarda instantes con zona horaria y los endpoints de caja presentan ISO 8601 con el desplazamiento aplicable en `America/Santiago`.

El servicio STK-04A obtiene la sesión activa bajo el bloqueo de caja y la asocia dentro de la transacción que guarda la venta, la reserva y las líneas. Distintos vendedores comparten la sesión y conservan el alcance individual del historial. La clave por vendedor recupera la venta original y su asociación aunque la sesión ya esté cerrada.

Las ventas anteriores a esta migración tienen sesión nula. Durante STK-06A, el POS también admite nuevas ventas sin sesión cuando la caja está cerrada o todavía falta una apertura. La asignación aplica a ventas nuevas a partir de la próxima apertura.

## Efectivo y cierre

`MovimientoCaja` conserva la sesión, el tipo `ingreso` o `retiro`, un importe positivo, el motivo, el responsable y la hora del servidor. La operación registra efectivo adicional por separado del historial de ventas. Los movimientos y los valores de apertura confirmados son de solo lectura a través de las superficies de STOCKEX.

`resumir_caja` reutiliza `resumir_ventas` sobre las ventas de la sesión y agrega los movimientos por tipo. El resumen contiene `efectivo_inicial`, `cantidad_vigente`, `total_vigente`, `por_metodo` con `cantidad` e `importe` vigentes por pago, `cantidad_anulada`, `monto_anulado`, `ingresos`, `retiros`, `cantidad_ingresos`, `cantidad_retiros` y `efectivo_esperado`. Los desgloses de crédito y mixto de STK-05A aparecen con valor cero en las sesiones nuevas.

```text
efectivo_esperado = efectivo_inicial + ventas_vigentes_en_efectivo + ingresos - retiros
diferencia = efectivo_contado - efectivo_esperado
```

La contribución en efectivo de una venta es su total neto del vuelto. Tarjeta y transferencia contribuyen únicamente al total vendido. Una anulación ajusta el registro interno y excluye la venta vigente. Su importe original se informa por separado. El efectivo esperado representa el saldo teórico y el conteo físico queda registrado aparte. Los importes usan aritmética entera en CLP.

El cierre admite sesiones vacías y diferencias. La clasificación es `cuadrada` si la diferencia es cero, `sobrante` si es positiva y `faltante` si es negativa. Una diferencia exige observaciones. Se persisten el resumen, el desglose, los totales y las cantidades de movimientos, la diferencia y su clasificación, junto con el conteo, el responsable y la hora. Los movimientos individuales permanecen en sus registros. El historial lee la instantánea persistida.

## Bloqueos y huella

El orden comienza siempre por la fila persistente `BloqueoCaja(pk=1)`, incluso entre jornadas. La migración crea esa fila. PostgreSQL usa `SELECT FOR UPDATE` y SQLite ejecuta `UPDATE` como primera operación en la transacción para obtener el bloqueo de escritor antes de las lecturas críticas. Si SQLite agota la espera de bloqueo, las vistas responden `503` con `Retry-After: 1`. La vista previa también toma el bloqueo para obtener ventas, movimientos y huella del mismo estado.

Sólo después del bloqueo común se consulta o modifica la caja y se adquieren los bloqueos de la operación. El registro reserva la clave de la venta y bloquea los productos en orden ascendente de ID. La anulación bloquea la fila de la venta autorizada y aplica `impedimento_anulacion` bajo el mismo bloqueo común. Los demás cambios de sesión y movimientos se ejecutan dentro de la misma transacción. Los servicios financieros adquieren el bloqueo común antes que cualquier bloqueo de catálogo o venta.

Cada nueva venta, anulación confirmada o movimiento de la sesión cambia `version_resumen` en la misma transacción. El GET devuelve esa versión como `huella`. El cierre verifica la versión bajo bloqueo y recalcula el resumen en el servidor. Si la versión cambió, devuelve `409 resumen_cambiado` y requiere volver a consultar y confirmar. El cierre confirmado bloquea anulaciones y movimientos nuevos para esa sesión. Si el cierre gana frente a una venta nueva, se aplica la compatibilidad temporal del POS y la venta puede quedar con sesión nula.

## Idempotencia

La apertura usa una clave única por responsable. El movimiento usa una clave única por sesión y compara también el responsable. Un cierre conserva la clave en la sesión y permite un reintento idéntico con el mismo responsable, conteo, observaciones y huella. La comparación se hace sobre los textos con espacios externos recortados y el UUID normalizado. La recuperación ocurre antes de validar que la sesión siga abierta. Una misma clave con datos distintos devuelve `409 clave_en_conflicto`. Una clave nueva para cerrar una sesión ya cerrada devuelve `409 caja_cerrada`.

Tras perder la respuesta o recibir `503`, se debe repetir la misma clave con el mismo cuerpo. Si se recibe `resumen_cambiado`, se debe volver a mostrar la vista previa, obtener confirmación explícita y enviar su nueva huella. Ese rechazo deja disponible la clave original.

## Permisos y endpoints

Todas las rutas requieren una sesión autenticada y el permiso explícito de la operación. Las respuestas con datos de caja o errores de negocio incluyen `Cache-Control: no-store`. Las escrituras requieren POST, `Content-Type: application/json`, `X-CSRFToken` y `Idempotency-Key` UUID v4. El GET de caja activa puede establecer la cookie CSRF. El cuerpo admite hasta 16 KiB. El Administrador recibe los cinco permisos en la migración y por `crear_grupos_permisos`. Vendedor conserva sus permisos de registro y consulta individual de ventas. La gestión de caja se realiza a través de estos servicios. Los modelos de caja carecen de rutas en Django Admin y en el router de REST Framework.

| Método y ruta | Permiso `inventario` | Solicitud y respuesta |
| --- | --- | --- |
| GET `/caja/activa/` | `consultar_caja` | `sesion`, `resumen` y `huella` de la caja activa. Devuelve `{"sesion": null}` entre jornadas. |
| POST `/caja/abrir/` | `abrir_caja` | `efectivo_inicial` obligatorio y `observaciones` opcional. Devuelve `id`, `abierta_en`, `abierta_por_id`, `efectivo_inicial` y `observaciones_apertura`. |
| POST `/caja/<id>/movimientos/` | `registrar_movimiento_caja` | `tipo`, `importe`, `motivo`. Devuelve `id`, `sesion_id`, `tipo`, `importe`, `motivo`, `usuario_id` y `fecha`. |
| POST `/caja/<id>/cerrar/` | `cerrar_caja` | `efectivo_contado`, `huella`, `observaciones` según la diferencia. Devuelve el mismo contenido que el detalle del cierre. |
| GET `/caja/cierres/?antes_de=<id>` | `consultar_cierres_caja` | Hasta 50 cierres por ID descendente con `id`, `cerrada_en`, `cerrada_por_id` y `efectivo_contado`. `antes_de` es el cursor siguiente o nulo. Es opcional en la solicitud. |
| GET `/caja/cierres/<id>/` | `consultar_cierres_caja` | Datos de apertura, `cerrada_en`, `cerrada_por_id`, `efectivo_contado`, `observaciones_cierre`, `huella` y `resumen` persistido con `diferencia` y `clasificacion`. |

Los POST exitosos devuelven `201` y `repetida: false`, o `200` y `repetida: true`. Los errores del servicio incluyen `error`, `mensaje` y, cuando aplica, `campo`. HTTP 400 cubre campos inválidos, 403 permisos o CSRF, 404 sesiones ausentes y detalles de sesiones abiertas, 405 métodos inválidos, 409 conflictos, 413 cuerpos excesivos y 415 formato de contenido. Una sesión HTTP ausente redirige al login.

El efectivo inicial y los movimientos admiten hasta $999.999.999.999 por operación. El contado admite desde cero hasta $9.007.199.254.740.991. Los importes requieren números JSON enteros. El motivo admite de 1 a 250 caracteres y las observaciones hasta 500. La hora, los responsables, la sesión de una venta y los totales se determinan en el servidor.

## Migración y recuperación

`0021_nucleo_cierres_caja` crea las tablas, los permisos, la fila de bloqueo y la referencia nullable de `Venta`. Aplicar con `python manage.py migrate --noinput`. Las ventas, importes y auditorías de anulación existentes se conservan.

Para retirar la función conservando los datos, suspender el tráfico de escritura financiera y revertir el código en una rama de recuperación con el esquema `0021` aplicado. El código anterior carece de estas reglas y podría aceptar nuevas ventas y anulaciones ajenas a ese flujo. Mantener suspendidos los POST financieros mientras se ejecuta ese código si ya existen sesiones o cierres.

**Revertir el esquema a `0020` elimina las sesiones, sus claves, los cierres, los movimientos de caja, el vínculo de las ventas y los permisos de caja.** Suspender escrituras, tomar y verificar un respaldo consistente antes de revertir. En PostgreSQL puede usarse `pg_dump -Fc` y una restauración de prueba con `pg_restore` sobre una base aislada. En SQLite, usar `.backup` y verificar la copia con `PRAGMA integrity_check`. Ejecutar `python manage.py migrate inventario 0020` con el código de STK-06A disponible. Para restaurar íntegramente, recuperar el respaldo en una base aislada, comprobar referencias, instantáneas, permisos y conteos, y habilitar el código compatible con `0021` antes de reanudar operaciones. Si hubo escrituras tras el respaldo, conciliarlas antes de reemplazar la base. Reaplicar la migración por sí sola vuelve a crear un esquema de caja vacío.

## Verificación

| Motor | Suite completa |
| --- | --- |
| SQLite en archivo | 275 aprobadas, 6 omitidas específicas de PostgreSQL |
| PostgreSQL 15.20 | 280 aprobadas, 1 omitida específica de SQLite |

Las pruebas de concurrencia usan conexiones independientes. En PostgreSQL se verifica la espera con `pg_blocking_pids`. Cubren aperturas simultáneas, apertura frente a venta, cierres simultáneos, movimientos repetidos y los dos órdenes del cierre frente a venta, anulación y movimiento. En SQLite se verifican las mismas carreras y la recuperación tras un `503`. En ambos motores se probó `0020 → 0021 → 0020 → 0021` con ventas y auditorías sintéticas y rollback después de escrituras con fallo inducido.

Se ejecutaron `pip check`, `manage.py check`, `makemigrations --check --dry-run` y `scripts/check_lint.py`.

Los recorridos de punto de venta, historial y anulación pasaron en Chromium 156.0.8078.79 con Django y SQLite temporal. El recorrido del POS cubrió la compatibilidad entre jornadas, el registro rápido y detallado y la recuperación de intentos.

## Rendimiento

Mediciones locales con el cliente Django autenticado como Administrador, SQLite en archivo y PostgreSQL 15.20 local. Se incluyen middleware y control transaccional. Apertura, venta y movimiento usan 30 muestras tras cinco calentamientos. Para cada volumen se usan 20 sesiones sintéticas por motor tras tres calentamientos, con tres métodos de pago, anulaciones y dos ingresos adicionales por sesión. La carga de datos queda fuera de los tiempos. El registro se compara con el mismo servicio de STK-04A presente en `main` (`41a81bf`).

| Operación | SQLite p50 / p95 (ms) | PostgreSQL p50 / p95 (ms) | SQL |
| --- | ---: | ---: | ---: |
| Apertura | 4,87 / 6,56 | 6,61 / 7,79 | 10 |
| Venta rápida · STK-04A | 5,45 / 8,35 | 7,30 / 8,29 | 11 |
| Venta rápida · asociada | 4,99 / 6,06 | 7,10 / 8,53 | 12 |
| Venta detallada, un producto · STK-04A | 5,98 / 8,81 | 8,73 / 9,44 | 13 |
| Venta detallada, un producto · asociada | 5,54 / 6,61 | 8,06 / 9,58 | 14 |
| Reintento de venta rápida · STK-04A | 3,92 / 4,75 | 6,56 / 7,26 | 9 |
| Reintento de venta rápida · asociada | 3,53 / 4,39 | 6,18 / 7,43 | 9 |
| Movimiento | 4,85 / 5,62 | 7,14 / 8,58 | 11 |
| Reintento de movimiento | 4,42 / 5,89 | 5,98 / 7,19 | 9 |
| Resumen · 100 ventas | 8,16 / 9,03 | 11,43 / 12,42 | 10 |
| Cierre · 100 ventas | 8,40 / 10,46 | 11,71 / 12,10 | 11 |
| Resumen · 500 ventas | 8,97 / 10,81 | 11,33 / 11,91 | 10 |
| Cierre · 500 ventas | 8,91 / 9,67 | 11,83 / 13,32 | 11 |
| Resumen · 2.000 ventas | 10,11 / 11,26 | 12,05 / 12,68 | 10 |
| Cierre · 2.000 ventas | 10,12 / 11,00 | 12,32 / 20,53 | 11 |
| Reintento de cierre · 2.000 ventas | 4,25 / 4,70 | 5,70 / 6,40 | 8 |

El número de consultas de resumen y cierre es constante en los tres volúmenes. En estas ejecuciones, las medianas de registro variaron menos de 0,7 ms en ambos motores. El p95 de registro en PostgreSQL subió 0,24 ms para venta rápida y 0,14 ms para venta detallada. La medición usa peticiones secuenciales. Las operaciones concurrentes pueden sumar tiempo de espera por el bloqueo común.

## STK-06B y alcance

STK-06B implementará la interfaz de apertura, movimientos, confirmación, reconfirmación e historial y exigirá una sesión activa al registrar nuevas ventas. La caja actual cubre un único punto de venta. Las correcciones posteriores al cierre, las devoluciones de efectivo, los gastos, los fiados y la operación de múltiples cajas quedan fuera de este flujo.

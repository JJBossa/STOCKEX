# STK-07A · Núcleo seguro de fiados y abonos

## Ventas fiadas y cuentas por cobrar

El servicio de venta del POS admite `metodo_pago: "credito"` en modalidad rápida y detallada. Exige un cliente activo, una caja abierta y permiso específico. El RUT y los datos de contacto son opcionales. El registro guarda el total original y asocia al cliente, vendedor y sesión. La venta queda marcada como crédito, con monto recibido y vuelto en cero. Los precios detallados y la fecha vienen del servidor. La venta, sus líneas, su reserva de idempotencia y la cuenta por cobrar se confirman juntas.

Se reutilizan `Cliente`, `Venta`, `CuentaPorCobrar`, `RegistroVenta`, `PagoCliente`, `SesionCaja` y `AnulacionVenta`. Las deudas nuevas llevan `fiado_seguro` y un documento único `CC-` seguido de un UUID v4. Un índice único parcial garantiza una deuda segura por venta. Su restricción de estado exige monto original positivo, pagado entre cero y el total y consistencia entre saldo y estado. Los servicios conservan el monto original.

El saldo de una cuenta es monto original menos el monto pagado. Una deuda cancelada queda fuera del saldo exigible. **Pendiente** significa sin pagos, **Parcial** significa pago inferior al total, **Pagado** indica saldo cero y **Cancelado** indica una anulación. La fecha de vencimiento es opcional y se compara con la fecha civil de `America/Santiago`. Las cuentas vencidas siguen formando parte de la deuda pendiente.

El límite de crédito cero representa ausencia de tope. Un límite positivo cubre la suma de la deuda pendiente y la nueva venta. El HTML de clientes y Django Admin validan importes enteros no negativos y coordinan las modificaciones de límite, estado y eliminación con el bloqueo de caja. Un límite nuevo positivo debe cubrir el saldo confirmado. Los clientes con historial de ventas, deudas o devoluciones tienen referencias protegidas.

## Abonos

El servicio de abonos admite efectivo, tarjeta y transferencia. Permite pagar una deuda pendiente o parcial, incluso vencida y aunque el cliente esté inactivo. El importe debe ser positivo y menor o igual al saldo. Cada `PagoCliente` guarda la cuenta, importe, método, responsable, fechas del servidor, sesión de recepción, referencia, observaciones y clave UUID v4. El abono, la actualización del saldo y la invalidación de la huella de caja se confirman juntos. La operación prescinde de ventas nuevas, ajustes de stock y actualizaciones implícitas desde `save()`.

La clave de abono es única por responsable. Se compara la cuenta, el importe, el método y los textos normalizados. La venta conserva la huella idempotente de STK-04A y los campos de crédito se incluyen en la huella de una venta fiada. La recuperación se evalúa antes de la apertura de caja o la elegibilidad de la deuda, y devuelve la operación y sesión originales. La misma clave con otros datos devuelve `409 clave_en_conflicto`. Una respuesta perdida o un `503` se recupera usando el mismo cuerpo y la misma clave.

## Caja, bloqueos y anulaciones

El fiado suma al total y cantidad vendidos. Solo los tres métodos de pago inmediato contribuyen a `ventas_directas`. Los métodos históricos de venta se conservan en `por_metodo`. El abono suma a `abonos` y `recibido_por_metodo` de su sesión de recepción. Su importe en efectivo se agrega al efectivo esperado. La deuda pendiente permanece como saldo vivo del cliente bajo el permiso de cuentas por cobrar.

```text
efectivo_esperado = efectivo_inicial + ventas_vigentes_en_efectivo
                  + abonos_en_efectivo + ingresos - retiros
```

`fiados` y `ventas_directas` contienen `cantidad` e `importe`. `abonos` agrega esos campos y `por_metodo`. `recibido_por_metodo` desglosa `ventas_directas`, `abonos` y `total` en CLP. Un abono nuevo cambia la huella antes de admitir el cierre. La siguiente confirmación usa la nueva vista previa. Los cierres nuevos guardan estos campos en la instantánea. Las vistas y el validador de Caja aceptan las instantáneas de STK-06A/B y muestran los indicadores de STK-07A cuando están presentes.

El orden empieza por `BloqueoCaja` tanto para ventas como para abonos, anulaciones, cambios de límite, movimientos, apertura y cierre. Después se comprueba el estado de caja y se aplican los bloqueos propios del registro o la anulación. Las consultas de cliente, cuenta y saldo en las escrituras ocurren bajo ese mismo bloqueo. PostgreSQL usa `SELECT FOR UPDATE` y SQLite adquiere el bloqueo del escritor antes de leer. Una espera agotada en SQLite devuelve `503` y `Retry-After: 1`.

Un fiado seguro puede anularse si su sesión sigue abierta, la deuda concuerda con la venta, el abono acumulado es cero y la venta supera las comprobaciones de STK-05B. La misma transacción anula la venta, conserva su auditoría y cancela su cuenta. Un fiado con pagos confirmados, una venta de caja cerrada o un registro histórico incompatible se bloquea. Los flujos directos conservan las comprobaciones anteriores.

## Permisos y contratos

Los permisos `inventario.registrar_venta_fiada`, `inventario.consultar_cuentas_por_cobrar` e `inventario.registrar_abono` se entregan inicialmente a **Administrador**. Verificar los roles con `crear_grupos_permisos`. Una futura delegación puede conceder abono sin acceso a consultas, o crédito junto a `registrar_venta`. El permiso de consulta habilita los saldos de todos los clientes, por lo que corresponde a personas autorizadas para ese alcance. El historial de ventas conserva el alcance individual del Vendedor.

Las escrituras usan POST, sesión Django, CSRF, `Content-Type: application/json` e `Idempotency-Key` UUID v4. El servidor compara `X-Stockex-Account` con la sesión cuando se envía. Los cuerpos financieros admiten hasta 16 KiB y los importes por operación hasta $999.999.999.999. Los GET financieros y los resultados de los servicios usan `Cache-Control: no-store`. Las rutas heredadas de escritura de cuentas, pagos y devoluciones permanecen suspendidas. Las cuentas y los pagos se consultan en Django Admin con permiso y en modo de solo lectura.

| Ruta | Permiso y respuesta |
| --- | --- |
| GET `/fiados/clientes/?q=...` | Venta y crédito. Devuelve hasta 20 clientes activos con `id`, `nombre` y `rut` nullable. Busca por nombre o RUT, desde dos caracteres y hasta 100. |
| GET `/fiados/clientes/<id>/saldo/` | Consulta. Devuelve `cliente_id`, `limite_credito`, `saldo` y `pendientes`. Una discrepancia impide confirmar el saldo. |
| GET `/fiados/clientes/<id>/cuentas/` | Consulta. Devuelve `cuentas` y `antes_de`. Incluye vencidas. |
| GET `/fiados/cuentas/<id>/` | Consulta. Devuelve documento, referencias a cliente y venta, importes, estado financiero y registrado, fechas, indicador de conciliación y notas. |
| GET `/fiados/cuentas/<id>/abonos/` | Consulta. Devuelve `abonos` y `antes_de`, incluidos métodos históricos y sesión nula cuando corresponda. |
| POST `/pos/registrar-venta/` | Venta y crédito para `credito`. Añade `cliente_id`, `cuenta_id`, `es_credito` y `sesion_caja_id` a la respuesta de un fiado. |
| POST `/fiados/cuentas/<id>/abonar/` | Abono. Devuelve ID, cuenta, importe, método, responsable, fechas, sesión, textos y `repetida`. |

Las listas usan ID descendente con 50 registros por página. El cliente envía `?antes_de=<id>` para la página siguiente. El cursor nulo indica el final.

Ejemplo de fiado rápido:

```json
{"modalidad":"rapida","metodo_pago":"credito","monto":12000,"cliente_id":42,"fecha_vencimiento":"2026-12-15","notas":"Crédito semanal"}
```

Para un fiado detallado se envía `modalidad: "detallada"` e `items` con `producto_id`, `cantidad` y `precio_visto`, como en STK-04A. `monto_recibido` puede omitirse o ser cero. `fecha_vencimiento` admite omisión, nulo o una fecha ISO civil. `notas` admite hasta 500 caracteres.

Ejemplo de abono:

```json
{"importe":3000,"metodo_pago":"transferencia","referencia":"TR-42","observaciones":"Abono semanal"}
```

El método y el importe entero son obligatorios. `referencia` y `observaciones` admiten hasta 200 y 500 caracteres. HTTP 201 confirma una operación nueva y 200 recupera la original. HTTP 400 identifica validación de campos o cursor. HTTP 403 cubre permisos y CSRF y una sesión vencida redirige a login. HTTP 404 cubre el recurso inexistente. HTTP 409 incluye `caja_no_abierta`, `cliente_no_elegible`, `limite_credito_excedido`, `cuenta_no_pagable`, `abono_supera_saldo`, `cuenta_inconsistente`, `clave_en_conflicto` y los conflictos existentes de precio o resumen.

## Historia y conciliación

`0022_nucleo_fiados_abonos` conserva los datos de `0021`. Los pagos históricos conservan su método y llevan sesión y clave nulas. El indicador de deuda segura empieza desactivado para cuentas históricas, incluso si hay referencias a una venta repetida. Conserva el estado registrado `vencido`. En lecturas nuevas, una cuenta histórica coherente expone además su estado financiero pendiente o parcial. La primera operación nueva válida puede actualizar el estado conforme al pago.

Las cuentas con importes inconsistentes, pagos que no cuadran con el acumulado, una referencia de venta incompatible o una deuda duplicada se identifican para conciliación. El detalle devuelve sus importes registrados, `saldo: null` y `conciliacion_requerida: true`. Se rechaza abonar esa cuenta y se suspende el crédito nuevo y la confirmación de saldo del cliente hasta reconciliarla. Un límite histórico negativo también impide crédito nuevo. Pagar una deuda coherente de ese cliente sigue siendo posible.

Para conciliar, identifica las cuentas desde el detalle, el historial de abonos o una lectura controlada de `fiados.cuentas_auditadas(...).filter(inconsistente=True)`. Verifica documento, venta, cliente, importes y comprobantes contra una copia respaldada. Registra las diferencias y deja la corrección para un procedimiento contable autorizado con evidencia. Conserva referencias de caja desconocidas como nulas y las instantáneas ya confirmadas.

## Migración y reversión

Respalda antes de aplicar `python manage.py migrate --noinput`. En PostgreSQL usa `pg_dump -Fc` y prueba la restauración en una base aislada. En SQLite usa `.backup` y valida la copia con `PRAGMA integrity_check`. Comprueba registros, responsables, importes, vínculos y las instantáneas.

Con escrituras suspendidas, `python manage.py migrate inventario 0021` permite volver al esquema anterior mientras pueda conservar toda la información. La migración rechaza la reversión si hay fiados o abonos de STK-07A, o cuentas sin vencimiento. Después de uso operativo, conserva `0022`, reconcilia los intentos pendientes y mantén suspendidas las operaciones financieras si reviertes el código. STK-06B carece de la contabilización de los abonos en Caja.

## Pruebas y rendimiento

- SQLite en archivo. 298 aprobadas y 6 omitidas específicas de PostgreSQL.
- PostgreSQL 15.20. 303 aprobadas y 1 omitida específica de SQLite.
- Once pruebas de concurrencia nuevas en ambos motores. PostgreSQL verificó bloqueos entre conexiones independientes con `pg_blocking_pids`. Se probaron pagos simultáneos e idempotentes, límites, los dos órdenes de cierre con fiado o abono, y anulación frente a abono.
- Migración de ida y vuelta en ambos motores con datos sintéticos inconsistentes y una instantánea histórica. Se verificó el rechazo de la reversión con operaciones nuevas.
- Regresiones de POS, historial, anulaciones y Caja en Chromium 156.0.8078.79 con Django real. Un abono posterior a la vista previa obligó a reconfirmar la conciliación.
- `pip check`, `manage.py check`, `makemigrations --check --dry-run` y `scripts/check_lint.py`.

Mediciones locales del cliente Django autenticado, 30 muestras por operación después de cinco calentamientos, con SQLite en archivo y PostgreSQL 15.20. Se usaron 100 ventas y 25 abonos sintéticos por sesión y 60 cuentas con pagos históricos por cliente. Las ventas detalladas incluyen cinco líneas y las consultas SQL incluyen middleware y transacciones.

| Operación | SQLite p50 / p95 (ms) | PostgreSQL p50 / p95 (ms) | SQL |
| --- | ---: | ---: | ---: |
| Fiado rápido | 9,42 / 10,07 | 12,87 / 14,58 | 13 |
| Fiado detallado | 10,05 / 10,41 | 13,93 / 15,46 | 15 |
| Abono | 6,74 / 6,97 | 9,28 / 10,01 | 11 |
| Reintento de fiado | 2,85 / 3,02 | 4,84 / 5,46 | 8 |
| Reintento de abono | 2,95 / 3,19 | 3,66 / 4,00 | 6 |
| Saldo de cliente | 6,22 / 6,45 | 8,08 / 9,03 | 4 |
| Cuentas pendientes | 5,32 / 5,91 | 7,03 / 8,48 | 4 |
| Resumen de caja | 7,52 / 8,27 | 9,61 / 11,81 | 9 |
| Cierre de caja | 7,59 / 8,11 | 9,70 / 10,29 | 10 |
| Venta directa rápida · STK-06B | 4,35 / 5,18 | 7,35 / 9,82 | 12 |
| Venta directa rápida · STK-07A | 4,72 / 5,22 | 7,57 / 8,79 | 12 |
| Venta directa detallada · STK-06B | 4,91 / 7,79 | 8,62 / 10,16 | 14 |
| Venta directa detallada · STK-07A | 5,20 / 5,68 | 8,76 / 9,91 | 14 |

El agregado de abonos añade una consulta en resumen y cierre. Las ventas directas mantuvieron sus consultas y las medianas variaron hasta 0,37 ms. Las mediciones secuenciales excluyen las esperas por operaciones concurrentes.

## Alcance de STK-07B

STK-07B incorpora los formularios de selección de cliente, fiado, consulta y abono, y la recuperación manual de pendientes desde el navegador. STK-07A habilita esos flujos por API y actualiza la conciliación existente. Los abonos iniciales, pagos mixtos y reversas de abonos quedan fuera de este alcance.

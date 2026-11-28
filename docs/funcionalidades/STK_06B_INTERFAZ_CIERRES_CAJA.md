# STK-06B · Interfaz de sesiones y cierres de caja

## Operación diaria

En **Menú → Caja**, ingresa el efectivo inicial en CLP enteros, incluido $0, y añade observaciones si corresponden. **Abrir caja** usa el servicio de STK-06A. Tras confirmar, la página consulta el estado actual y muestra el acceso al POS cuando hay una sesión abierta.

El resumen reúne hora y responsable de apertura, ventas vigentes y anuladas, desglose por pago y composición del efectivo. El **total vendido** incluye los pagos de todos los métodos. El **efectivo esperado** suma el fondo inicial, las ventas vigentes en efectivo y los ingresos y resta los retiros. **Actualizar** consulta el servidor y conserva el borrador para la misma sesión. Crédito y mixto aparecen en el desglose si hay ventas registradas con esos métodos.

Para registrar un ingreso o retiro, selecciona el tipo e ingresa un importe positivo y un motivo. La sesión se indica junto al formulario. La confirmación válida actualiza el resumen. **Ver movimientos** muestra importe, tipo, motivo, responsable y hora de cada movimiento registrado, incluso en sesiones cerradas. Las vistas muestran fechas de `America/Santiago`.

## Conciliación y cierre

Indica el efectivo físico contado, incluido $0. La diferencia estimada se calcula en enteros a partir del efectivo esperado del servidor. Un faltante o sobrante exige observaciones. **Revisar cierre** abre un diálogo con el conteo, la diferencia y las consecuencias del cierre. **Confirmar cierre** envía el conteo, la nota y la huella de la vista previa. El servidor calcula y guarda la instantánea definitiva. El cierre es permanente y bloquea movimientos nuevos y anulaciones de ventas de la sesión.

Si el servidor responde `409 resumen_cambiado`, se obtiene una nueva vista previa. La interfaz conserva el conteo y las observaciones, compara los importes y cantidades y vuelve a calcular la diferencia. La siguiente escritura requiere abrir el diálogo y confirmar otra vez con la huella nueva. Si la consulta falla, **Actualizar** permite recuperar la vista previa antes de cerrar.

**Historial de cierres** permite consultar páginas de hasta 50 cierres por ID descendente y filtrar por fecha de cierre chilena y clasificación. Cada fila vincula al detalle y presenta las cifras de la instantánea. El detalle y el resumen usan una plantilla de presentación reutilizable para futuras salidas. Los movimientos se consultan mediante su propio cursor, con hasta 50 registros por página.

## Recuperación e idempotencia

Antes de cada POST se guarda un UUID v4 y el cuerpo JSON exacto junto con la cuenta, la operación y la sesión objetivo, si corresponde. `sessionStorage` mantiene un espacio por cuenta y por tipo de operación en cada pestaña, con claves separadas para apertura, ingreso, retiro y cierre. Las credenciales y el token CSRF se toman de la sesión vigente al enviar.

Si hay pérdida de respuesta, espera agotada, `503`, sesión vencida, CSRF rechazado o respuesta inconcluyente, el intento permanece pendiente. **Reintentar** recupera explícitamente la misma solicitud y se puede usar tras recargar. Hasta resolverla, esa pestaña bloquea nuevas operaciones de caja. Un `409 clave_en_conflicto` exige revisar los registros y resolver el intento de forma explícita. Los rechazos con resultado definitivo permiten corregir los datos. Una apertura recuperada consulta el estado actual, pues la sesión original puede haber cerrado. Los reintentos no se ejecutan automáticamente.

Cerrar la pestaña, perder el almacenamiento o cambiar de dispositivo puede quitar acceso al intento guardado. Antes de registrar una operación equivalente, comprueba el historial o los movimientos con la cuenta original y concilia el resultado. Con JavaScript deshabilitado, la navegación, los filtros y las consultas siguen disponibles y la página indica que las escrituras requieren JavaScript.

## POS y permisos

Al cargar, el POS presenta solamente si hay caja abierta. **Consultar estado de caja** vuelve a consultar el indicador sin tocar el borrador. Un vendedor puede recuperar una venta pendiente aunque la caja esté cerrada. Si una venta nueva recibe `caja_no_abierta`, el formulario conserva los datos editables y espera una nueva acción del vendedor después de la apertura.

El servicio de ventas toma primero el bloqueo común de STK-06A. Una clave ya registrada recupera la venta original con su sesión original. Para una clave nueva, el servicio exige una sesión activa dentro de la misma transacción. Si el cierre ganó la carrera y la caja ya está cerrada, el servicio devuelve HTTP 409 y la transacción revierte la reserva. Las ventas históricas con sesión nula se conservan. El registro mantiene la separación entre ventas y stock.

Las escrituras reutilizan los permisos de STK-06A y requieren autenticación, POST, CSRF y `Idempotency-Key`. Los formularios envían `X-Stockex-Account` y el servidor comprueba que corresponda a la sesión autenticada si está presente. Los roles iniciales conservan la administración de caja en Administrador. Un usuario con permiso de venta puede consultar el indicador del POS sin acceder a importes globales. Las lecturas financieras usan `Cache-Control: no-store`.

| Contrato | Permiso y alcance |
| --- | --- |
| GET `/caja/` o `/caja/?fragmento=resumen` | `consultar_caja` para el resumen. `abrir_caja` permite acceder a la apertura y ver el estado. |
| GET `/caja/historial/` | `consultar_cierres_caja`. Admite `antes_de`, `desde`, `hasta` y `clasificacion`. |
| GET `/caja/historial/<id>/` | `consultar_cierres_caja`. Presenta la instantánea persistida. |
| GET `/caja/<id>/movimientos/listado/` | `consultar_caja` para una sesión activa. `consultar_cierres_caja` para una sesión cerrada. Admite `antes_de`. |
| GET `/caja/cierres/` | Conserva el cursor y agrega hora de apertura, responsables, total vendido, cantidad de ventas, efectivo esperado, diferencia y clasificación. |
| POST `/caja/<id>/cerrar/` | Conserva el contrato de STK-06A. El cliente de Caja recibe además un fragmento de la instantánea para el caso en que tiene permiso de cierre sin permiso de historial. |
| GET `/pos/estado-caja/` | `registrar_venta`. Devuelve únicamente `{"abierta": true}` o `{"abierta": false}`. |
| POST `/pos/registrar-venta/` | Devuelve `409 caja_no_abierta` al intentar una venta nueva entre sesiones. La recuperación idempotente conserva la respuesta anterior. |

## Verificación

- SQLite en archivo. 278 aprobadas y 6 omitidas específicas de PostgreSQL.
- PostgreSQL 15.20. 283 aprobadas y 1 omitida específica de SQLite. Las carreras usan conexiones independientes y verifican bloqueos reales con `pg_blocking_pids`.
- Chromium 156.0.8078.79 con Django real y SQLite temporal. Recorridos de Caja, POS, historial de ventas y anulación. Caja comprobada en claro y oscuro a 390, 768, 1366 y 1920 px. Las pruebas usan cuentas y datos sintéticos.
- `pip check`, `manage.py check`, `makemigrations --check --dry-run` y `scripts/check_lint.py`.

## Rendimiento

Mediciones locales con el cliente Django autenticado, 30 muestras por operación tras cinco calentamientos. Las sesiones medidas tuvieron 100 ventas sintéticas iniciales, tres medios de pago, anulaciones y un ingreso. Los tiempos incluyen middleware, vistas y control de transacción. Se usó una cuenta superusuaria en Caja y el rol Vendedor en el POS. Las solicitudes HTTP cuentan las operaciones de aplicación por acción y excluyen recursos estáticos.

| Operación | SQLite p50 / p95 (ms) | PostgreSQL p50 / p95 (ms) | SQL por petición | HTTP por acción |
| --- | ---: | ---: | ---: | ---: |
| Carga inicial de Caja cerrada | 4,21 / 7,14 | 5,27 / 7,26 | 6 | 1 |
| Carga inicial de Caja activa | 9,02 / 14,21 | 10,79 / 14,32 | 8 | 1 |
| Estado de caja desde el POS | 2,20 / 3,18 | 4,25 / 6,15 | 5 | 1, a petición |
| Actualización del resumen | 7,51 / 11,22 | 9,47 / 15,02 | 8 | 1 |
| Apertura | 3,47 / 6,11 | 5,06 / 6,56 | 8 | 2, incluido el resumen |
| Registro de movimiento | 3,71 / 5,13 | 5,47 / 7,10 | 9 | 2, incluido el resumen |
| Confirmación de cierre | 7,19 / 11,30 | 8,92 / 12,64 | 9 | 2, incluido el detalle |
| Detalle de cierre | 3,13 / 4,77 | 4,37 / 5,90 | 3 | 1 |
| Historial de cierres | 11,58 / 16,97 | 12,96 / 22,64 | 3 | 1 por página |
| Venta rápida asociada a caja | 4,41 / 5,76 | 8,03 / 9,36 | 12 | 1 |

En STK-06A, la venta rápida asociada usó igualmente 12 consultas y registró medianas de 4,99 y 7,10 ms. Apertura, movimiento, resumen y cierre registraron medianas del mismo orden. Las cifras entre tareas incluyen perfiles, carga local y condiciones de ejecución diferentes.

El recorrido de navegador del POS midió 287,10 ms de carga, 16,70 ms de actualización visual y 20,60 y 26,30 ms por registro rápido y detallado. STK-04B informó 247,60, 16,80, 17,30 y 20,60 ms respectivamente. La carga registró 15 solicitudes frente a 14 de STK-04B, incluido el módulo de UUID compartido. Se midieron cero solicitudes por búsqueda de producto o cambio de cantidad y cero consultas de caja automáticas al editar.

## Reversión segura

STK-06B usa el esquema existente de `0021_nucleo_cierres_caja` y conserva las instantáneas. Para revertir el código, suspende las escrituras financieras, reconcilia los intentos pendientes y conserva una copia verificada. Mantén el esquema aplicado. Si vuelves a STK-06A, mantén suspendido el registro de ventas mientras dependas de la regla de caja activa, ya que esa versión admite ventas entre sesiones.

# STK-07B · Interfaz de fiados, clientes y abonos

## Registrar un fiado

Con caja abierta, prepara una venta rápida o detallada y elige **Fiado**. Escribe al menos dos caracteres del nombre o RUT, usa las flechas y Enter o elige un resultado con el mouse. Cada resultado muestra el ID para distinguir homónimos. Puedes quitar la selección y buscar otro cliente. El buscador consulta hasta 20 clientes activos por solicitud y conserva solo la respuesta de la búsqueda vigente.

**Crear cliente** abre un formulario dentro del POS para quien tenga autorización. Solo el nombre es obligatorio. Un límite en blanco o cero representa crédito sin tope. Tras el alta, el POS selecciona el cliente y conserva el monto, los productos y las cantidades. Un doble envío con la misma clave produce la misma alta. Dos altas distintas pueden tener el mismo nombre.

Antes de guardar, revisa el cliente, el total y el vencimiento opcional. La confirmación indica que no se recibe dinero. Quien tiene permiso de consulta ve el saldo anterior y el proyectado cuando el servidor puede confirmarlos. Puedes registrar observaciones opcionales. El servidor valida el cliente activo, el límite, la sesión y los precios vigentes.

## Consultar deudas y registrar abonos

**Menú → Fiados** muestra saldos, clientes y cuentas pendientes, deuda vencida y abonos del día civil chileno. Los abonos del día incluyen todas las sesiones y se distinguen de la conciliación de Caja. Si el total pendiente, vencido o del día depende de registros inconsistentes, el indicador muestra **Por conciliar**.

Filtra por nombre o RUT, deuda, vencimiento y estado del cliente. El listado admite orden por nombre o saldo y pagina de a 30 clientes. Volver desde el cliente conserva los filtros y la página. En el detalle puedes consultar cuentas pendientes, pagadas, canceladas o todas, con historial de abonos. Los listados de cuentas y abonos usan cursores de hasta 50 registros. El detalle distingue el vencimiento del estado financiero y conserva el estado registrado cuando difiere. Los abonos históricos muestran su método y referencia y presentan **Sin sesión registrada** cuando corresponde.

En una cuenta coherente y con caja abierta, ingresa un abono entero en CLP o pulsa **Pagar saldo completo** para rellenar el importe. Elige efectivo, tarjeta o transferencia y añade referencia u observaciones si corresponde. Revisa el saldo anterior, el importe, el método y el saldo proyectado. La escritura ocurre al pulsar **Confirmar abono**. Las deudas coherentes vencidas y de clientes inactivos se pueden cobrar.

## Recuperar una operación

El POS y Abonos guardan la clave UUID v4 y el cuerpo exacto en `sessionStorage` antes de enviar. El espacio está separado por usuario y pestaña. La venta conserva la selección y los datos del fiado, y el abono identifica la cuenta objetivo. Las credenciales y los tokens CSRF se toman de la sesión vigente al enviar.

Si la respuesta se pierde, expira la sesión o el servicio devuelve `503`, usa el reintento manual desde la misma pestaña y cuenta. La recarga recupera el intento. También puedes recuperar un registro confirmado cuando la caja original esté cerrada. Abonos mantiene una operación pendiente por usuario y pestaña y dirige a la cuenta correspondiente. Un conflicto de clave requiere verificar el historial y confirmar la conciliación. Los rechazos definitivos permiten corregir el borrador.

La confirmación de un abono y la actualización de la vista son pasos distintos. Si se confirma el abono y falla el refresco, **Actualizar saldo e historial** solo vuelve a consultar. Cerrar la pestaña, perder el almacenamiento o cambiar de dispositivo puede quitar acceso al intento guardado. En ese caso consulta el historial antes de ingresar una operación equivalente. El alta modal de cliente conserva su intento en la página abierta. La creación desde el formulario HTML también envía una clave de alta.

## Permisos y contratos

El POS muestra Fiado a quienes tienen `inventario.registrar_venta` y `inventario.registrar_venta_fiada`. **Fiados** y los saldos requieren `inventario.consultar_cuentas_por_cobrar`. El formulario de abono requiere además `inventario.registrar_abono`. La API de escritura de abonos conserva su permiso independiente. El alta usa `inventario.add_cliente` y el requisito de Administrador existente. El enlace y el ID de la venta relacionada respetan `view_venta` y el alcance individual. Las consultas financieras usan `Cache-Control: no-store`.

| Contrato | Uso |
| --- | --- |
| `POST /pos/registrar-venta/` | Contrato STK-07A para crédito. La confirmación valida venta, número, cliente, deuda, usuario, modalidad, sesión, total, indicadores y efectivo y vuelto en cero. |
| `GET /fiados/clientes/?q=…` y `GET /fiados/clientes/<id>/saldo/` | Buscador y consulta autorizada. El encabezado `X-Stockex-Account` permite detectar un cambio de cuenta. |
| `GET /fiados/` | Panel HTML con `q`, `deuda=1`, `vencidas=1`, `activo=0` o `1`, `orden=saldo` o `nombre` y `page`. |
| `GET /fiados/gestion/clientes/<id>/` | Detalle HTML. Admite `estado`, `cuentas_antes_de` y `abonos_antes_de`. |
| `GET /fiados/gestion/cuentas/<id>/` | Detalle de cuenta e historial HTML. `fragmento=abono` recarga saldo e historial en un GET. |
| `POST /fiados/cuentas/<id>/abonar/` | Contrato STK-07A. La confirmación valida cuenta, importe, método, usuario, fechas, sesión, referencia, observaciones y repetición. |
| `POST /clientes/crear/` | Conserva el formulario HTML con `clave_alta`. La variante JSON acepta campos de cliente como texto y exige `Idempotency-Key` UUID v4. Devuelve `id`, `nombre`, `rut`, `activo` y `repetida`, con HTTP 201 o 200. Una misma clave con otros datos devuelve 409. |
| `GET /fiados/cuentas/<id>/` y `GET /fiados/clientes/<id>/cuentas/` | `venta_id` es nulo si el solicitante carece de alcance para la venta relacionada. |

Los POST del navegador mantienen CSRF y los contratos financieros de STK-07A. Las consultas y la navegación funcionan sin JavaScript. El POS y Abonos indican que las escrituras requieren JavaScript.

## Caja y reversión

Caja utiliza las ventas y abonos registrados por STK-07A. Un fiado aumenta las ventas y la deuda. Un abono reduce la deuda y aumenta lo recibido en su sesión. Solo un abono en efectivo aumenta el efectivo esperado. Ambos pueden cambiar la huella y exigir reconfirmación. Los cierres históricos conservan sus instantáneas.

La migración `0023_clave_alta_cliente` añade una clave única y una huella al modelo Cliente. La restricción permite deduplicar dos altas concurrentes incluso si falta RUT, sin usar el nombre como identificador. Las altas existentes quedan intactas. La reversión de esquema se bloquea si existen claves de alta. Para revertir el código, suspende escrituras, concilia los intentos pendientes y conserva la migración aplicada. El respaldo y las comprobaciones financieras de STK-07A siguen vigentes.

## Verificación y rendimiento

Las suites se ejecutaron con Python 3.11.18, Django 5.2.19 y las opciones de pytest de CI. Pasaron 302 pruebas en SQLite en memoria compartida y en archivo, con 6 omisiones en cada uno. PostgreSQL 15.20 registró 307 aprobadas y 1 omitida. Pasaron `pip check`, `manage.py check`, `makemigrations --check --dry-run` y `scripts/check_lint.py`. La cobertura de navegador usa Chromium 156 con Django real y datos sintéticos. Se comprobaron recuperación de fiados y abonos, reconfirmación, autorización, CSRF, escape de texto, consultas sin JavaScript y resoluciones de 390, 768, 1366 y 1920 px en claro y oscuro.

Las mediciones locales usan 30 muestras después de cinco calentamientos y el cliente Django autenticado. El conjunto incluye 300 clientes, 1.200 cuentas y sus pagos históricos sintéticos. La tabla informa tiempo del servidor en milisegundos, consultas SQL por petición y solicitudes de aplicación por acción. No incluye el debounce de 250 ms, recursos estáticos ni latencia de red.

| Operación | SQLite p50 / p95 | PostgreSQL 15.20 p50 / p95 | SQL | HTTP |
| --- | ---: | ---: | ---: | ---: |
| Carga inicial del POS, Vendedor | 3,44 / 4,52 | 6,14 / 6,74 | 6 | 1 |
| Carga inicial del POS, Administrador | 2,40 / 2,73 | 3,48 / 3,71 | 3 | 1 |
| Búsqueda de clientes | 1,68 / 2,10 | 2,77 / 3,12 | 3 | 1 por consulta estabilizada |
| Fiado rápido | 9,30 / 10,40 | 13,06 / 17,49 | 13 | 1 |
| Fiado detallado, cinco líneas | 10,18 / 11,30 | 14,49 / 16,38 | 15 | 1 |
| Panel de fiados, ordenado por saldo | 29,00 / 82,03 | 37,69 / 75,22 | 6 | 1 |
| Detalle de cliente | 12,89 / 13,98 | 15,85 / 17,48 | 6 | 1 |
| Abono | 6,80 / 8,83 | 9,82 / 11,34 | 11 | 2, incluido refresco |
| Reintento de fiado | 2,77 / 3,62 | 5,39 / 6,27 | 8 | 1 |
| Reintento de abono | 2,84 / 3,70 | 3,89 / 4,27 | 6 | 2, incluido refresco |
| Refresco de cuenta | 6,64 / 16,28 | 9,25 / 11,82 | 7 | 1 |

La selección agrega un GET de saldo solo cuando la cuenta tiene permiso de consulta. El buscador de clientes se carga al elegir Fiado. Las ventas directas conservan 12 consultas SQL para el registro rápido y 14 para el detallado. En Chromium la carga del POS Vendedor registró 15 solicitudes y cero solicitudes de fiados.

Se repitió la comparación de ventas directas con 60 muestras por escenario y motor, usando el mismo flujo de ventas directas en `main` y en la rama. La mediana de registro varió como máximo 0,24 ms.

| Venta directa | SQLite p50 / p95 en main → STK-07B (ms) | PostgreSQL p50 / p95 en main → STK-07B (ms) |
| --- | ---: | ---: |
| Rápida | 4,38 / 4,76 → 4,47 / 4,89 | 6,83 / 8,36 → 7,07 / 8,59 |
| Detallada | 5,23 / 5,84 → 5,26 / 5,74 | 8,25 / 10,39 → 8,31 / 10,03 |

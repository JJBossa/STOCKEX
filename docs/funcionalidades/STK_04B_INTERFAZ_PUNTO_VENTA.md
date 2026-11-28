# STK-04B — Interfaz del punto de venta

El punto de venta en `/pos/` abre en **Venta rápida**, con efectivo seleccionado y el foco en el monto. Ingresa pesos enteros, con o sin puntos de miles, y elige efectivo, tarjeta o transferencia. Deja vacío el efectivo recibido para registrar el importe exacto. El formulario muestra el total y el vuelto estimado, y señala si falta efectivo.

En **Venta detallada**, el buscador de STK-03 carga el catálogo al abrir la modalidad. Busca por nombre, SKU o categoría. Seleccionar de nuevo un producto aumenta su cantidad. Cada línea permite editar la cantidad o quitarla y muestra el precio base y el subtotal. El total visual se actualiza en el navegador. Se admiten productos activos con stock cero y precio de $1. El registro prescinde de descuentos y movimientos de stock.

## Teclado

| Tecla | Acción |
| --- | --- |
| Flechas arriba y abajo | Recorre resultados en el buscador |
| Enter en el buscador | Agrega el resultado enfocado o el primero. También permite usar un lector que envíe el SKU seguido de Enter |
| Escape en el buscador | Cierra los resultados |
| Tab y espacio | Navega y activa los botones |
| Ctrl+Enter dentro del formulario | Registra la venta editable cuando el foco está fuera del buscador |

Enter por sí solo nunca registra una venta, incluso con el botón de registro enfocado. Usa espacio o un clic para un reintento pendiente. Pon el foco en el buscador antes de escanear.

## Registro y recuperación

El único envío de escritura es `POST /pos/registrar-venta/`. Se usa el [contrato de STK-04A](STK_04A_NUCLEO_SEGURO_VENTAS.md) con JSON, `X-CSRFToken` e `Idempotency-Key` UUID v4. El servidor calcula los importes definitivos. HTTP 201 confirma una venta nueva y HTTP 200 recupera una venta existente. La última venta muestra número, fecha y hora de Santiago, importe, método y, para efectivo, monto recibido y vuelto. La confirmación limpia los campos, conserva la modalidad y el método de pago y devuelve el foco al monto o al buscador. El comprobante en pantalla es de uso interno.

Antes de enviar, la interfaz guarda la clave y el cuerpo JSON exacto bajo un nombre asociado al ID de la cuenta autenticada en `sessionStorage`. Durante el envío se deshabilitan la edición y el botón de registro. Una pérdida de conexión, una espera de 12 segundos sin respuesta, un 503 o una respuesta inconcluyente conserva el intento y habilita el reintento manual. Volver a cargar la pestaña muestra el intento sin enviarlo. Si la sesión venció, vuelve a abrir el POS, inicia sesión con la misma cuenta y reintenta desde la pestaña original. Otra cuenta abre su propio formulario y sólo recupera sus intentos.

Una confirmación verificada elimina el estado pendiente y habilita una clave nueva para la operación siguiente. Un conflicto de clave mantiene bloqueada la operación hasta que el vendedor revise el historial y cierre explícitamente el intento. Si el navegador impide guardar el intento, el POS detiene el envío.

## Precio y disponibilidad

El conflicto de precio muestra cada producto afectado, su precio anterior, el vigente y el nuevo total. Acepta los precios y vuelve a pulsar **Registrar venta**. Si el efectivo queda corto, el formulario devuelve el foco al importe recibido para corregirlo. Un producto inactivo o inexistente se marca en su línea. Quita esa línea para continuar con las demás. Después de estos rechazos, la misma clave acompaña la corrección manual del intento hasta que la venta se confirme.

## Permisos y límites

La vista y el registro requieren `inventario.registrar_venta`. Administrador y Vendedor lo reciben mediante `python manage.py crear_grupos_permisos`. El buscador usa `inventario.view_producto` y el enlace al historial usa `inventario.view_venta`. La consulta del historial conserva sus permisos. Las rutas heredadas de escritura financiera siguen suspendidas.

La recuperación depende de la pestaña, el origen, la cuenta y el almacenamiento de sesión. Si cierras la pestaña, pierdes el almacenamiento o cambias de dispositivo, consulta el historial antes de repetir una operación incierta. El lector se verificó mediante emulación de teclado. Para revertir la interfaz, revierte el commit en una rama de recuperación. STK-04B carece de migraciones.

## Pruebas

La suite completa pasó con **173 aprobadas y 5 omitidas en SQLite** y **178 aprobadas en PostgreSQL 15.20**. Las cinco omisiones son pruebas de PostgreSQL. Pasaron `pip check`, `manage.py check`, `makemigrations --check --dry-run` y `scripts/check_lint.py`.

Los 12 escenarios en Chromium 156.0.8078.79 ejecutaron Django con una base SQLite temporal y 531 productos sintéticos. Verificaron pagos, cantidades, teclado y lector emulado, nombres mostrados como texto, stock, permisos, CSRF, precios, disponibilidad, recuperación de respuesta perdida y aislamiento entre cuentas. Examinaron los controles y el desbordamiento horizontal a 390, 768, 1366 y 1920 px en las dos modalidades. También pasó la prueba de navegador de STK-03 con 531 y 5.000 productos.

Para repetir el flujo, ejecuta `node tests/browser/punto-venta.mjs` con Playwright y un Chromium disponibles. Se pueden configurar `PLAYWRIGHT_MODULE`, `CHROMIUM_PATH`, `PYTHON` y `POS_CAPTURAS` para guardar las imágenes. Por defecto se usan las URL de Bootstrap e iconos existentes en la plantilla base. `POS_CDN_LOCAL` permite repetir las mediciones con copias locales de esos archivos.

## Rendimiento

Mediciones locales en Chromium sin interfaz gráfica, Django de desarrollo y SQLite en archivo, con los recursos de CDN servidos desde copias locales. Se midieron cinco cargas hasta el evento `load`, 25 cambios de cantidad hasta el siguiente cuadro y diez registros por modalidad. La venta detallada de la medición incluye dos productos. El tiempo hasta que el formulario queda listo se cuenta desde el final de la respuesta del servidor.

| Operación | p50 |
| --- | ---: |
| Carga inicial | 247,60 ms |
| Actualización visual de totales | 16,80 ms |
| Registro HTTP de venta rápida | 17,30 ms |
| Registro HTTP de venta detallada | 20,60 ms |
| Confirmación recibida a formulario listo | 6,90 ms |

La carga inicial hizo 14 solicitudes HTTP, incluidas las de la plantilla base. El HTML del vendedor ocupó 18.437 bytes, el JavaScript propio del POS 24.595 bytes y el CSS propio 7.971 bytes. El módulo del buscador agrega 9.145 bytes al abrir la modalidad detallada. El navegador hizo cero solicitudes HTTP por teclear en el buscador o editar cantidades.

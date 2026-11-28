# STK-05A — Historial y totales de ventas

`/ventas/` muestra por defecto las ventas del día en Chile. Ordena por fecha e ID descendentes y presenta hasta 50 ventas por página. El enlace al detalle y el regreso conservan los filtros y la página. Si tienes permiso de registro, el encabezado ofrece acceso al punto de venta.

## Filtros y navegación

Los períodos son Hoy, Ayer, Últimos 7 días incluyendo hoy, Mes actual, Todas las fechas y Rango personalizado. Un rango personalizado admite una o ambas fechas. También se puede filtrar por número de venta completo o parcial, modalidad, método, estado y, para Administrador, vendedor. Una fecha inválida, un rango invertido o un valor desconocido muestra sus errores junto con un resultado vacío.

Django renderiza tanto la página completa como el fragmento con los resultados. Actualizar, filtrar y cambiar de página pueden reemplazar el fragmento sin recargar el sitio. Los mismos controles funcionan como enlaces y formularios GET sin JavaScript. La consulta ocurre al aplicar filtros, elegir un período rápido, paginar o actualizar.

El detalle presenta fecha y hora de Chile, modalidad, vendedor, método, estado y total almacenado. Para efectivo y mixto muestra el importe recibido y el vuelto registrados. Las ventas rápidas tienen un mensaje específico cuando carecen de productos. Las ventas históricas con modalidad NULL aparecen como **Histórica sin clasificar** en la tabla y **No registrada** en el detalle. Las líneas leen el nombre, el precio y el subtotal guardados en `ItemVenta`.

## Indicadores

El resumen toma todas las ventas autorizadas que coinciden con los filtros, incluidas las que quedan fuera de la página visible.

| Indicador | Cálculo |
| --- | --- |
| Total vendido vigente | Suma de `Venta.total` de ventas vigentes |
| Ventas vigentes | Cantidad de ventas con `cancelada=False` |
| Promedio por venta | Total vigente dividido por su cantidad, con dos decimales y redondeo a la mitad hacia arriba |
| Desglose por método | Total y cantidad de ventas vigentes de cada método |
| Monto original anulado | Suma y cantidad de ventas con `cancelada=True`, en una tarjeta separada |

Efectivo neto usa el total de la venta. El monto entregado y su vuelto se conservan para el detalle. Crédito y mixto mantienen sus importes y cantidades propios. Los registros mixtos se muestran como una sola categoría. El resumen mide ventas y deja la conciliación de caja para otra etapa. Aplicar sólo el estado Anulada deja los indicadores vigentes en cero.

## Alcance y hora de Chile

La página, su fragmento, los indicadores, el detalle y la API usan el alcance de `ventas_visibles` y exigen `inventario.view_venta`. Administrador consulta todas las ventas y Vendedor sólo las propias. El detalle ajeno de un vendedor devuelve 404. La página, los fragmentos, el detalle, los tickets y el API de ventas usan `Cache-Control: no-store`. La API mantiene sus campos y filtros históricos. Su filtro por usuario aplica únicamente para Administrador, evita listar cuentas en el formulario REST y el orden predeterminado desempata por ID.

Cada rango usa `fecha >= inicio` y `fecha < fin`, donde fin es el comienzo del día siguiente al último seleccionado en `America/Santiago`. Los extremos se convierten individualmente a UTC. En el cambio con medianoche saltada, el inicio coincide con el primer instante de ese día chileno. Las pruebas cubren el 4 de abril de 2026, de 25 horas, y el 6 de septiembre de 2026, de 23 horas.

## Consultas y reversión

`resumir_ventas(queryset)` agrega en SQL los importes y las cantidades con sumas y conteos condicionales. Usa pesos enteros para los importes y `Decimal` para el promedio. Paginación reutiliza el conteo de ventas vigentes y anuladas y obtiene un máximo de 50 filas con una consulta. El historial prescinde de cargar ítems. Sólo el detalle los consulta. La API los carga junto con sus productos para sus campos existentes.

La migración incremental `0019_venta_historial_fecha` añade el índice descendente `(fecha, id)`. Los totales de todas las fechas siguen leyendo las filas que cumplen los filtros. Ya existe el índice de la relación a vendedor. Para revertir el índice, ejecuta `python manage.py migrate inventario 0018` desde esta versión antes de revertir el commit en una rama de recuperación. La reversión retira el índice y conserva las ventas.

Para STK-06, `resumir_ventas` admite un queryset previamente autorizado y delimitado por la ventana de trabajo. `inicio_dia_chileno` está disponible para límites basados en fechas civiles. El resumen es una lectura en vivo. Nuevas ventas entre consultas pueden cambiar la posición de una fila al paginar.

## Rendimiento

Medianas de 12 peticiones por caso después de dos calentamientos. Se usó el cliente Django autenticado, con SQLite en archivo y PostgreSQL 15.20 local. Los datos sintéticos cubrieron ocho vendedores, 40 días, cinco métodos, tres modalidades y ambos estados. La medición del administrador usó una cuenta superusuaria, todas las fechas y la página 2. La del vendedor combinó sus ventas, los últimos siete días y tarjeta. Las consultas incluyen autenticación, permisos, indicadores, página y las opciones de vendedor cuando corresponden. El HTML se midió sin compresión.

| Ventas | Perfil | SQLite p50 respuesta / agregado / página (ms) | PostgreSQL p50 respuesta / agregado / página (ms) | SQL | HTML (bytes) |
| ---: | --- | ---: | ---: | ---: | ---: |
| 1.000 | Administrador | 26,56 / 0,85 / 0,07 | 31,77 / 1,32 / 0,67 | 5 | 53.030 |
| 1.000 | Vendedor | 15,74 / 0,14 / 0,06 | 22,43 / 0,87 / 0,68 | 9 | 17.822 |
| 10.000 | Administrador | 32,25 / 6,45 / 0,07 | 34,67 / 6,80 / 0,77 | 5 | 53.239 |
| 10.000 | Vendedor | 25,44 / 0,45 / 0,06 | 31,49 / 1,21 / 1,09 | 9 | 44.144 |
| 50.000 | Administrador | 61,08 / 33,77 / 0,08 | 58,05 / 29,78 / 1,06 | 5 | 53.373 |
| 50.000 | Vendedor | 31,20 / 2,21 / 0,07 | 33,76 / 2,73 / 1,20 | 9 | 49.323 |

Con 50.000 ventas, retirar el índice sobre la misma base elevó el p50 de la consulta de página de **0,08 a 22,99 ms en SQLite** y de **1,06 a 34,23 ms en PostgreSQL**. En la comparación, la respuesta completa del administrador pasó de 61,08 a 89,33 ms en SQLite y de 58,05 a 91,32 ms en PostgreSQL. El índice compuesto adicional por vendedor se probó junto con el índice de fecha. El beneficio para la respuesta filtrada fue menor, y se conservó el índice existente de la relación.

## Pruebas

- SQLite aprobó 199 pruebas y omitió las cinco específicas de PostgreSQL. PostgreSQL 15.20 aprobó 204.
- Pasaron `pip check`, `manage.py check`, `makemigrations --check --dry-run` y `scripts/check_lint.py`. Aplicar, revertir y reaplicar `0019` conservó el conteo y los totales de las 50.000 ventas sintéticas en cada motor.
- Chromium 156 con Django real verificó permisos, filtros, detalle, retorno a la página filtrada, actualización sin recarga y navegación sin JavaScript. Se comprobaron el historial y el detalle en claro y oscuro a 390, 768, 1366 y 1920 px, sin desplazamiento horizontal de la página ni solapamiento de controles. La tabla puede desplazarse horizontalmente dentro de su región en móvil.

La prueba de navegador se ejecuta con `node tests/browser/historial-ventas.mjs` y crea una base SQLite temporal. Usa Playwright y Chromium disponibles en el entorno de pruebas. Admite `PLAYWRIGHT_MODULE`, `CHROMIUM_PATH`, `PYTHON` y `HIST_CAPTURAS`. `POS_CDN_LOCAL` permite usar las copias locales de Bootstrap e iconos que utiliza la prueba de STK-04B.

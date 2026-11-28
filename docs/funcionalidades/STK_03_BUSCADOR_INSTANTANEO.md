# STK-03 — Buscador instantáneo

El catálogo de inicio incluye un buscador rápido separado de los filtros existentes. Busca nombres, SKU y categorías con coincidencias completas, parciales y por varias palabras, aunque cambien las mayúsculas o los acentos. Los resultados priorizan SKU exacto, nombre exacto, prefijos y coincidencias parciales. Los empates se ordenan por nombre, SKU e ID. El SKU se conserva como texto.

Usa las flechas para recorrer hasta 12 resultados, Enter para seleccionar, Escape para cerrar y Tab para seguir la navegación. Un lector que emule el teclado puede enviar un SKU seguido de Enter. La selección habilita el enlace de detalle y emite el evento `producto-seleccionado` con los cinco campos del producto. El componente está en [buscador-productos.js](../../static/js/buscador-productos.js) y exporta `montarBuscador` para integraciones futuras.

## Catálogo, permisos y actualización

`GET /api/catalogo-productos/` requiere sesión autenticada y `inventario.view_producto`. Devuelve ID, SKU, nombre, categoría y precio base de venta en pesos chilenos enteros. Incluye todos los productos activos, también los de stock cero. El catálogo completo se carga por JSON y el buscador opera en memoria de la página. Las tarjetas paginadas mantienen su comportamiento anterior.

La respuesta usa `Cache-Control: private, no-store` y `Vary: Cookie`. El visor limpia el catálogo al salir de la página y no utiliza almacenamiento persistente del navegador. Los nombres, SKU y categorías se muestran como texto. Al fallar la carga se limpian los resultados y se ofrece reintentar.

Se revalida cada 60 segundos mientras la página está visible y al recuperar foco o visibilidad si pasaron al menos 10 segundos desde el último intento. Cada comprobación consulta el estado actual con una sola consulta de catálogo. El ETag se deriva del JSON, así que refleja también importaciones, cambios de categoría y escrituras masivas. Una respuesta 304 ahorra la transferencia y conserva el índice y la opción enfocada. En una pestaña visible puede haber hasta un intervalo de retraso, sujeto a los temporizadores del navegador. No se añade una transacción de venta ni una operación de stock.

## Pruebas y rendimiento

Se ejecutaron **117 pruebas en SQLite y 117 en PostgreSQL 15**, con migraciones reales aplicadas desde bases vacías hasta `0017`. Pasaron `pip check`, `manage.py check`, `makemigrations --check --dry-run` y `scripts/check_lint.py`.

| Productos sintéticos | JSON SQLite / PostgreSQL | Respuesta p50 SQLite / PostgreSQL | SQL por petición |
| --- | ---: | ---: | ---: |
| 531 | 55.131 / 55.139 bytes | 3,99 / 4,66 ms | 3 |
| 5.000 | 523.908 / 524.551 bytes | 31,81 / 27,02 ms | 3 |

Medianas de cinco llamadas con el cliente Django autenticado y SQL instrumentado, sin compresión ni transporte de red. Hay una consulta de catálogo con unión a categoría y dos de sesión y usuario para la cuenta de prueba.

| Productos sintéticos | Búsqueda local p95 | Entrada a siguiente cuadro p95 | HTTP por búsquedas |
| --- | ---: | ---: | ---: |
| 531 | 0,40 ms | 16,80 ms | 0 |
| 5.000 | 0,50 ms | 16,90 ms | 0 |

Chromium 156 headless local, 100 búsquedas en el índice y 25 eventos de entrada por volumen. La prueba usa el módulo y template del componente servidos por un fixture HTTP local. Cubre navegación nativa por teclado, secuencia de lector emulada, texto literal en resultados, revalidación sin contenido, cambio de precio y error con reintento. El tiempo visual incluye esperar el siguiente cuadro. Los valores dependen del navegador y equipo.

Para repetir las pruebas de navegador, usa un entorno de pruebas con Playwright disponible y ejecuta `node tests/browser/buscador-productos.mjs`. Se puede indicar una instalación externa mediante `PLAYWRIGHT_MODULE` y un Chromium existente mediante `CHROMIUM_PATH`. Playwright queda fuera de las dependencias de la aplicación.

## Límites y reversión

La verificación usó datos sintéticos, un lector emulado y servicios locales. Las latencias de despliegue y los lectores físicos quedan pendientes de verificación. Para revertir el cambio, revierte el commit en una rama de recuperación. El cambio no agrega migraciones.

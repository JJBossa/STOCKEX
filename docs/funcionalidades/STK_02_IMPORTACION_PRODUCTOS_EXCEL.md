# STK-02 — Importación de productos desde Excel

## Archivo y validaciones

El importador acepta `.xlsx` y `.xlsm`. Coloca los encabezados en la primera fila de la hoja **Productos**. Se aceptan columnas en cualquier orden.

| Columna | Regla |
| --- | --- |
| SKU | Obligatorio y único dentro del archivo, hasta 50 caracteres. Usa texto para códigos con ceros iniciales o más de 15 dígitos. Un SKU numérico entero con formato de ceros, por ejemplo `000000`, conserva ese relleno. |
| Nombre | Texto obligatorio de hasta 200 caracteres. |
| Categoría | Texto de hasta 100 caracteres o celda vacía. Se busca y crea por nombre exacto, conservando mayúsculas y acentos. Una celda vacía deja el producto sin categoría. |
| Precio | Entero positivo en CLP, de hasta 10 dígitos. Un precio de `1` aparece como advertencia y se importa con su valor original. Si el precio se guarda como texto, escribe el número sin símbolo de moneda ni separador de miles. |

Solo se importan estas cuatro columnas. Precio Compra, Stock y Valor Inventario quedan fuera de la importación. Se ignoran filas donde las cuatro columnas estén vacías. Los errores de fila muestran su número en Excel. Corrige todos antes de confirmar. Para fórmulas se usa el resultado guardado en el archivo. Si no hay un valor válido guardado, recalcula y guarda desde el editor de planillas.

El SKU identifica las actualizaciones. Los productos nuevos parten con stock y precio de compra en cero. En productos existentes se actualizan nombre, categoría y precio, conservando stock, precio de compra, imágenes, estado activo y demás campos. El importador conserva productos ausentes, registra los historiales de precio de Django y mantiene los movimientos de stock intactos.

## Interfaz y comando

1. En el catálogo, selecciona **Importar Excel**, adjunta el archivo y abre la vista previa.
2. Revisa las filas válidas, altas, cambios, filas sin cambios, precios de $1, productos sin categoría y errores.
3. Vuelve a seleccionar el mismo Excel y confirma dentro de 15 minutos. El resumen indica cuántos cambios se aplicaron.

La vista previa consulta el catálogo sin escribir. Su firma vincula al administrador, la huella del archivo y el estado de los SKU y categorías involucrados. Si el catálogo cambió en campos relevantes y quedarían cambios por aplicar, genera una vista previa nueva. Una confirmación repetida de una importación ya aplicada devuelve las filas sin cambios.

```bash
python manage.py importar_productos_excel catalogo.xlsx --dry-run
python manage.py importar_productos_excel catalogo.xlsx --confirm
```

El comando valida y planifica a partir del archivo que recibe en cada ejecución. Un `--dry-run` anterior es informativo. Al confirmar, el comando comprueba el estado observado en esa ejecución antes de escribir. Si hay errores, el comando termina con código distinto de cero. En web, un conflicto devuelve HTTP 409 y pide volver a revisar la vista previa.

## Seguridad y concurrencia

- La web exige un administrador con permisos para crear y modificar productos y crear categorías. La vista previa y la confirmación requieren CSRF. El comando requiere acceso a la consola y a la base configurada.
- Límites de 5 MiB de archivo, 32 MiB descomprimidos, 256 partes, 5.000 filas de datos y 64 columnas. Se validan el contenedor y las partes XML. La lectura con openpyxl descarta macros y enlaces externos. Los importes numéricos se leen del XML y se validan con `Decimal`, sin pasar por `float`.
- Django puede usar un archivo temporal durante cada solicitud y lo cierra al terminar. La aplicación no guarda el Excel ni depende de compartir un directorio entre procesos. Para validar la firma entre procesos se usa la misma `SECRET_KEY` de Django.
- PostgreSQL serializa importadores mediante un bloqueo transaccional y protege las filas existentes que el plan consulta. SQLite toma el bloqueo de escritura antes de consultar. En SQLite una contención puede requerir un reintento. Las restricciones únicas también protegen frente a altas concurrentes. La transacción revierte productos, categorías e historial ante un fallo.
- El antiguo comando `importar_productos` quedó deshabilitado. El build ya no importa datos automáticamente. `importar_datos` conserva la restauración manual de JSON, con la carga de catálogo reservada a una base sin productos ni categorías.

## Verificación y rendimiento

Con migraciones reales hasta `0017` desde bases vacías y archivos sintéticos, pasaron **112 pruebas** en SQLite y **112** en PostgreSQL 15. Pasaron `pip check`, `manage.py check`, `makemigrations --check --dry-run` y el verificador de lint. Solo se retiraron huellas obsoletas de los dos comandos antiguos modificados.

| Operación | SQLite | PostgreSQL 15 local |
| --- | ---: | ---: |
| Lectura, vista previa y alta de 531 productos | 0,205 s · 1.070 SQL | 0,521 s · 1.070 SQL |
| Lectura y nueva importación del mismo archivo | 0,033 s · 5 SQL | 0,034 s · 5 SQL |

Se excluyen la creación y transferencia del Excel. Las consultas de búsqueda y las altas de categorías se agrupan. Las altas de productos y sus historiales usan el guardado y las señales de Django, que explican la mayoría de las consultas. Las mediciones son locales. El archivo comercial y la latencia en Render siguen sin verificarse.

## Reversión

Guarda un respaldo de la base antes de una importación real. Ante un error de procesamiento, la aplicación revierte la transacción por sí sola. Si la importación ya se confirmó, revisa el respaldo y restaura solo los campos y registros afectados, junto con sus historiales, teniendo en cuenta los cambios posteriores y las referencias a productos nuevos. El código se puede revertir en una rama de recuperación. Esta etapa no agrega migraciones.

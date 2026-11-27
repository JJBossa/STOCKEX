# STK-01C — Estabilización de pruebas y CI

Base verificada de `main` en `0598c3ab9df84457b63ff5b7e20f546a0f0e0f4f`. La suite se reprodujo con Python 3.11.18, Django 5.2.19 y los bloqueos de STK-01B.

## Fallos reproducidos y resueltos

| Caso | Causa | Resolución |
| --- | --- | --- |
| `test_cliente_str` | Prueba desactualizada. `Cliente.__str__` identifica al cliente con nombre y RUT, con «Sin RUT» si falta. Django Admin usa esa representación al mostrar las relaciones de clientes. | Comprobar la etiqueta completa en dos casos, con y sin RUT. [Modelo](../../inventario/models.py) |
| `test_crear_cuenta_por_cobrar` | Prueba desactualizada. El modelo expone `saldo_pendiente`, que el detalle de cuentas usa para mostrar el saldo. | Mantener la aserción de 100.000 y consultar la propiedad vigente. [Template](../../templates/inventario/detalle_cuenta_cobrar.html) |
| `test_cuenta_por_cobrar_monto_pendiente` | La prueba de pago parcial también refería a `monto_pendiente`. | Mantener la aserción de 70.000 para `saldo_pendiente`. [Template](../../templates/inventario/detalle_cuenta_cobrar.html) |
| `test_cuenta_vencida` | Prueba desactualizada. `esta_vencida` es la propiedad usada en el detalle y en Django Admin. | Exigir que `esta_vencida` sea verdadera para una cuenta pendiente con vencimiento pasado. [Template](../../templates/inventario/detalle_cuenta_cobrar.html) |
| `test_cotizacion_genera_numero_automatico` | Fixture incompleta. El campo de vencimiento es obligatorio y la vista lo solicita antes de crear la cotización. | Proporcionar una fecha explícita y comprobar el prefijo y la fecha persistidos. [Vista](../../inventario/views_cotizaciones.py) |
| `test_busqueda_global_api_funciona` | Prueba desactualizada. El autocompletado consume `data.resultados`, una lista de elementos tipados. | Comprobar el JSON exacto y excluir un producto inactivo con nombre coincidente. [Consumidor](../../static/js/busqueda-global.js) |

Flake8 detectó un defecto de ejecución adicional, `F821` en `guardar_orden_dashboard`. La vista llamaba a `json.loads` sin importar `json` y devolvía 400 al intentar guardar un orden válido. Se añadió el import y una regresión que comprueba la persistencia en sesión y que un JSON inválido deja intacto el orden.

Se mantienen los contratos de negocio y las suspensiones financieras de STK-01A. Las 79 pruebas originales se conservaron y se agregaron dos casos, uno para el cliente con RUT y otro para el dashboard.

## CI y lint

- Pytest aplica migraciones reales por defecto y crea la base de pruebas sin reutilizarla. CI comprueba también el estado de las migraciones y aplica el historial en una base vacía de cada motor.
- La matriz usa SQLite y PostgreSQL 15. El servicio PostgreSQL se habilita únicamente en su entrada de la matriz. Cada ejecución instala desde los bloqueos con hashes y comprueba las dependencias. La suite incluye las 27 pruebas de STK-01A.
- La cobertura se conserva en artefactos de GitHub Actions por motor, en lugar de enviarse a Codecov. Checkout v6.1.0, setup-python v6.3.0 y upload-artifact v7.0.2 se fijan por SHA. El token del workflow tiene `contents: read` y el checkout no persiste credenciales.
- Flake8 7.5.0 y Black 26.10.1 tienen su propio bloqueo con hashes y dependencias transitivas. Isort se retiró de la instalación de lint porque el workflow no lo ejecutaba.

El [verificador de lint](../../scripts/check_lint.py) inspecciona todos los archivos Python versionados y nuevos sin ignorar, incluidas pruebas y migraciones. Flake8 conserva el límite histórico de 120 columnas. Los códigos `E9`, `F63`, `F7` y `F82` bloquean incluso al generar la línea base. Black usa el destino Python 3.11.

La línea base registra **1.773 diagnósticos de Flake8** y **2.347 bloques de cambios de Black** mediante huellas y multiplicidad por archivo. Excluye los números de línea, así que mover código ajeno a una infracción no la vuelve nueva. Un diagnóstico distinto, un bloque distinto o una ocurrencia adicional hacen fallar el chequeo. Al eliminar deuda hay que retirar sus huellas. Usar `--write-baseline` solo para registrar reducciones revisadas o para una actualización deliberada de la política. La deuda restante incluye formato, espacios, importaciones no usadas y excepciones amplias.

```bash
python -m pip install --only-binary=:all: --no-deps --require-hashes -r requirements-bootstrap.txt
python -m pip install --require-hashes -r requirements-lint.txt
python -m pip check
python scripts/check_lint.py
```

Para actualizar las herramientas de lint, editar `requirements-lint.in` y compilar con `uv pip compile requirements-lint.in --universal --python-version 3.11 --generate-hashes -o requirements-lint.txt`, usando uv 0.13.9.

## Resultados locales

| Comprobación | SQLite | PostgreSQL 15 |
| --- | --- | --- |
| Suite base | 73 aprobadas, 6 fallidas | 73 aprobadas, 6 fallidas |
| Suite final | 81 aprobadas | 81 aprobadas |
| Seguridad STK-01A por separado | 27 aprobadas | 27 aprobadas |
| Cobertura de líneas en `inventario` | 47,65 % → 47,81 % | 47,65 % → 47,81 % |
| `check`, `makemigrations --check --dry-run` y migración desde cero | Correctos hasta `0017` | Correctos hasta `0017` |

La cobertura inicial alcanzó 2.481 de 5.207 sentencias y la final 2.490 de 5.208. La instalación limpia con hashes y `pip check` pasaron. La política de lint pasó y una prueba local aislada confirmó que rechaza infracciones nuevas de ambos linters. `actionlint 1.7.12` validó el workflow.

Para reproducir la matriz tras la instalación de STK-01B, usa una base aislada nueva en cada ejecución. Deja `DATABASE_URL` vacía para SQLite o configúrala con la URL PostgreSQL local de pruebas.

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --noinput
python manage.py collectstatic --noinput --verbosity 0
python -m pytest --cov=inventario --cov-report=term --cov-report=xml
python -m pytest tests/test_seguridad_stk01a.py
```

GitHub Actions sigue bloqueado por facturación según el estado informado, con ticket de soporte abierto. El workflow permanece habilitado. Los resultados corresponden a ejecución local y validación estática. La ejecución alojada y la publicación de sus artefactos quedan pendientes.

## Reversión

Revertir el commit en una rama de recuperación y reinstalar los bloqueos de esa revisión en un entorno nuevo. Volver a ejecutar las pruebas contra bases aisladas. No se modificó el esquema ni se requiere una migración inversa.

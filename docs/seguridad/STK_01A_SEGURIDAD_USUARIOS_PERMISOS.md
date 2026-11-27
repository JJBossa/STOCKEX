# STK-01A — Seguridad de usuarios, autenticación y permisos

## Objetivo y alcance

Establecer una base de autenticación y autorización para La Previa. La implementación parte de `5c240113e4a6c55befd846a53b6b0fa9b7699813`, el commit auditado en STK-00 y la punta de `main` al iniciar. La etapa se verificó con bases aisladas y datos de prueba.

## Hallazgos corregidos

- El nombre de cuenta dejó de decidir permisos o destinos de avisos administrativos. Las alertas de cuentas por cobrar requieren permiso vigente incluso si ya se habían generado. El filtro de avisos se aplica antes del límite, lo que corrige el error preexistente del centro de notificaciones.
- Las operaciones de catálogo y las rutas administrativas comprueban autorización del lado servidor. El paso de un permiso histórico de almacén a edición de catálogo queda bloqueado en HTML, API y Django Admin. El historial propio aplica también en tickets y búsquedas.
- Los formularios de usuarios usan los validadores y el hashing de Django. Los campos de privilegio enviados directamente a las vistas operativas se ignoran. Un administrador operativo solo gestiona cuentas ordinarias o de vendedores sin privilegios adicionales. La desactivación conserva la atribución de ventas y pagos.
- El cierre de sesión usa POST con CSRF. Un cambio de contraseña invalida la sesión web y los tokens de acceso JWT emitidos con el hash anterior.
- Los comandos de aprovisionamiento exigen usuario y contraseña explícitos o contraseña ingresada sin eco en terminal. Un usuario existente provoca un error y conserva sus credenciales. Se retiró la creación automática de cuentas del build, la contraseña visible del script de Windows y la clave fija de desarrollo.
- El historial de ventas y fiados se protege también dentro de Django Admin, incluidos sus formularios en línea. La relación del cliente con las cuentas por cobrar usa `PROTECT` para impedir el borrado indirecto de cuentas y pagos. El endpoint de borrado masivo de ventas devuelve 403.
- El registro y la cancelación de ventas, la conversión de cotizaciones en ventas, las operaciones sobre devoluciones y la creación de deudas y pagos permanecen suspendidos en servidor. Los accesos sin permiso reciben 403. Si el usuario supera el permiso de entrada, la operación devuelve 423 sin escribir datos.

## Matriz de permisos

La matriz describe los dos grupos después de ejecutar `crear_grupos_permisos`. Los superusuarios activos conservan la autorización de Django, sujeta a los bloqueos financieros y al requisito de CSRF.

| Recurso o acción | Operador (`Vendedor`) | `Administrador` |
| --- | --- | --- |
| Catálogo | Consultar productos y categorías | Consultar y administrar según permisos de modelo |
| Inventario | Consultar stock del catálogo | Operaciones administrativas de inventario según permisos y módulo |
| POS e historial | Consultar el POS y sus propias ventas y tickets | Consultar el POS y todas las ventas y tickets |
| Registro de ventas, cancelaciones, conversión y devoluciones | Suspendidos | Suspendidos |
| Borrado de ventas, ítems, cuentas y pagos | Bloqueado | Bloqueado |
| Clientes y fiados | Sin acceso a gestión ni saldos | Gestionar clientes y consultar cuentas y pagos. Alta de créditos y pagos suspendida |
| Usuarios | Sin acceso a gestión | Consultar usuarios y crear, editar, restablecer o desactivar cuentas ordinarias y de vendedores |
| Grupos, asignaciones privilegiadas y administración de accesos en Django Admin | Reservados al superusuario | Reservados al superusuario |
| Configuraciones operativas y módulos administrativos existentes | Sin acceso administrativo | Acceso de administrador según el módulo |

Una cuenta autenticada sin rol conserva las pantallas básicas de consulta de catálogo. Los permisos de lectura REST y del historial se conceden de forma explícita. Los operadores creados por la aplicación no reciben `is_staff` ni permisos directos. La autorización en Django Admin requiere además acceso al panel.

Permisos previstos para etapas posteriores incluyen registrar una venta validada, revertir una venta o un pago, registrar o saldar un fiado, abrir/cerrar/reabrir caja y configurar el modo de inventario. Esas etapas deberán definir qué acciones corresponden a cada rol y en qué ámbito.

## Aprovisionamiento seguro

Ejecutar primero las migraciones y el aprovisionamiento explícito de los roles en la base autorizada:

```bash
python manage.py migrate
python manage.py crear_grupos_permisos
python manage.py crear_superusuario --username CUENTA_ADMIN
python manage.py crear_usuario_normal --username CUENTA_OPERADOR
```

Las dos últimas órdenes solicitan y confirman la contraseña sin eco cuando se ejecutan en una terminal sin variable de contraseña. `--email` es opcional. Para automatización, usar `--noinput` e inyectar `SUPERUSER_USERNAME` y `SUPERUSER_PASSWORD`, o `NORMAL_USER_USERNAME` y `NORMAL_USER_PASSWORD`, desde un gestor de secretos. La contraseña va en la variable de entorno y el comando valida su fortaleza antes de persistirla.

Un superusuario puede asignar el grupo `Administrador` a una cuenta revisada desde Django Admin. Para un operador existente, basta agregar el grupo `Vendedor` tras revisar sus permisos. El formulario web de alta crea operadores. Para rotar una contraseña de forma interactiva con acceso a la consola, ejecutar `python manage.py changepassword CUENTA`. En Windows se puede usar `resetear_password.bat CUENTA`.

Con `DEBUG=False` se requiere una `SECRET_KEY` explícita. En desarrollo sin clave explícita se genera una clave efímera por proceso. Configurar una clave local compartida si se necesitan sesiones estables entre reinicios o workers. Docker Compose exige una clave explícita.

## Usuarios y secretos existentes

- El comando de roles establece la lista de permisos de `Administrador` y `Vendedor` y conserva sus integrantes. Revisar primero las asignaciones de ambos grupos y guardar su configuración anterior. Los demás grupos, permisos directos, hashes y banderas existentes requieren revisión manual. Retirar las asignaciones privilegiadas injustificadas.
- Una cuenta sembrada por el build anterior puede seguir siendo superusuario por su bandera real. Rotar las contraseñas de las cuentas creadas con los scripts antiguos y desactivar las cuentas innecesarias después de verificar un acceso administrativo legítimo.
- Rotar la clave de Django y cualquier contraseña de PostgreSQL de ejemplo que se haya reutilizado. Los candidatos históricos aparecen en los comandos de cuentas anteriores, `render.yaml`, `control_stock/settings.py` y `docker-compose.yml`. Si se usó el restablecimiento de Windows anterior, rotar también esas contraseñas por su exposición en la línea de comandos de proceso. Eliminar los valores del código no los elimina del historial Git.

## Archivos modificados

| Área | Archivos principales |
| --- | --- |
| Roles y cuentas | `inventario/access.py`, `inventario/account_commands.py`, `inventario/utils.py`, `inventario/views_usuarios.py`, `inventario/admin.py`, comandos de cuentas y grupos |
| HTML y API | `inventario/permissions.py`, `inventario/api_views.py`, `inventario/serializers.py`, vistas del catálogo, inventario, búsqueda, notificaciones, ventas, fiados y módulos administrativos, `templates/base.html` y controles operativos de los templates |
| Protección de datos | `inventario/models.py`, `inventario/migrations/0017_proteger_cuentas_por_cobrar.py` |
| Configuración | `control_stock/settings.py`, `build.sh`, `render.yaml`, `docker-compose.yml`, `iniciar.bat`, `resetear_password.bat` |
| Regresión y documentación | `tests/test_seguridad_stk01a.py`, `tests/test_views.py`, `tests/conftest.py`, README, documentación técnica y de API |

## Resultados reproducidos

Python 3.11 y Django 5.2. Se ejecutó `manage.py migrate --noinput` desde bases vacías y pytest con `-o addopts='' --migrations` para aplicar las migraciones en las bases de prueba. `manage.py check` pasó y `makemigrations --check --dry-run` no detectó diferencias.

| Ejecutado | SQLite | PostgreSQL 15 local |
| --- | --- | --- |
| Línea base STK-00 | 45 aprobadas, 7 fallidas | 45 aprobadas, 7 fallidas |
| Migraciones STK-01A desde cero | Aplicadas hasta `0017` | Aplicadas hasta `0017` |
| Nuevas pruebas de seguridad | 27 aprobadas | 27 aprobadas |
| Suite completa STK-01A | 73 aprobadas, 6 fallidas | 73 aprobadas, 6 fallidas |

La prueba histórica que esperaba privilegios por el nombre de cuenta ahora exige una denegación HTTP 403. La prueba de notificaciones que fallaba en la línea base pasa con el filtro de autorización y el orden de consulta corregidos. Las seis fallas restantes corresponden a la representación de cliente, tres expectativas sobre propiedades de cuentas por cobrar, una cotización sin vencimiento y el formato de la API de búsqueda global.

La migración `0017` se revirtió y se volvió a aplicar en ambos motores aislados. Se comprobó sintaxis de `build.sh` y del JavaScript modificado. Los archivos `.bat` se revisaron estáticamente desde Linux.

## Riesgos pendientes

- El núcleo financiero de STK-00 sigue pendiente. Para habilitar ventas y devoluciones se requiere un servicio transaccional e idempotente que calcule importes en servidor, bloquee los registros pertinentes y cree reversas vinculadas con el original. Una reversa debe conservar actor, motivo, fecha y efectos de stock y deuda, y aplicarse una sola vez.
- No se admiten operaciones reales de caja hasta que estén listas las validaciones, las reversas y la conciliación. Las rutas de inventario heredadas ya protegidas mantienen su lógica actual.
- La invalidación de sesiones web y tokens JWT de acceso tras cambiar contraseña quedó verificada. La revocación individual de refresh tokens y el cierre unificado de sesiones necesitan una revisión aparte.
- Quedan pendientes el endurecimiento de HTTPS y despliegue de STK-00 y las seis fallas preexistentes.

## Reversión

1. Antes de cualquier cambio de versión, respaldar la base y registrar integrantes y permisos de los grupos. Mantener la aplicación aislada de operaciones reales durante toda la reversión.
2. Si se necesita retornar al esquema anterior, usar primero el código de STK-01A y ejecutar `python manage.py migrate inventario 0016` sobre la base respaldada. Esto vuelve a habilitar el comportamiento en cascada del modelo anterior. Verificar el respaldo y el estado de las migraciones.
3. Revertir el commit de STK-01A en una rama de recuperación. Si se ejecutó la configuración de grupos, restaurar solo asignaciones revisadas a partir del registro previo. Conservar las contraseñas y claves rotadas.
4. Verificar el acceso administrativo en una copia aislada. El código anterior vuelve a exponer las rutas financieras inseguras y la autorización por nombre, por lo que debe permanecer fuera de uso operativo.

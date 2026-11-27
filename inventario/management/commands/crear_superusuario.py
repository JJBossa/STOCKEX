from inventario.account_commands import CrearCuentaCommand


class Command(CrearCuentaCommand):
    help = 'Crea un superusuario con credenciales explícitas o contraseña interactiva.'
    prefijo = 'SUPERUSER'
    superusuario = True

from inventario.account_commands import CrearCuentaCommand


class Command(CrearCuentaCommand):
    help = 'Crea un operador de ventas con credenciales explícitas o contraseña interactiva.'
    prefijo = 'NORMAL_USER'
    grupo = 'Vendedor'

import json
from uuid import UUID

from django.core.exceptions import PermissionDenied


def comprobar_cuenta(request):
    cuenta = request.headers.get("X-Stockex-Account")
    if cuenta is not None and cuenta != str(request.user.pk):
        raise PermissionDenied


class ErrorJSON(Exception):
    def __init__(self, codigo, estado):
        self.codigo = codigo
        self.estado = estado


def objeto_json(pares):
    objeto = dict(pares)
    if len(objeto) != len(pares):
        raise ValueError("Propiedad JSON duplicada.")
    return objeto


def constante_invalida(valor):
    raise ValueError(f"Constante JSON inválida: {valor}")


def leer_json(request):
    limite = 16 * 1024
    if request.content_type != "application/json":
        raise ErrorJSON("tipo_de_contenido_invalido", 415)
    cuerpo = request.read(limite + 1)
    if len(cuerpo) > limite:
        raise ErrorJSON("payload_demasiado_grande", 413)
    try:
        return json.loads(
            cuerpo.decode("utf-8"),
            object_pairs_hook=objeto_json,
            parse_constant=constante_invalida,
        )
    except (ValueError, RecursionError) as error:
        raise ErrorJSON("json_invalido", 400) from error


def uuid_v4(valor):
    if not isinstance(valor, str) or len(valor) != 36:
        raise ValueError("Se requiere un UUID v4.")
    uuid = UUID(valor)
    if uuid.version != 4 or str(uuid) != valor.lower():
        raise ValueError("Se requiere un UUID v4.")
    return uuid

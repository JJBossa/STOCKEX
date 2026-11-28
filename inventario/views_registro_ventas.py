import json
import sqlite3

from django.db import OperationalError, connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from .access import permiso_requerido
from .registro_ventas import (
    PERMISO_REGISTRAR_VENTA,
    ErrorRegistroVenta,
    registrar_venta,
)

MAX_PAYLOAD = 16 * 1024


def objeto_json(pares):
    objeto = dict(pares)
    if len(objeto) != len(pares):
        raise ValueError("Propiedad JSON duplicada.")
    return objeto


def constante_invalida(valor):
    raise ValueError(f"Constante JSON inválida: {valor}")


@never_cache
@permiso_requerido(PERMISO_REGISTRAR_VENTA)
@require_POST
@csrf_protect
def registrar_venta_pos(request):
    if request.content_type != "application/json":
        return JsonResponse({"error": "tipo_de_contenido_invalido"}, status=415)
    cuerpo = request.read(MAX_PAYLOAD + 1)
    if len(cuerpo) > MAX_PAYLOAD:
        return JsonResponse({"error": "payload_demasiado_grande"}, status=413)
    try:
        datos = json.loads(
            cuerpo.decode("utf-8"),
            object_pairs_hook=objeto_json,
            parse_constant=constante_invalida,
        )
    except (ValueError, RecursionError):
        return JsonResponse({"error": "json_invalido"}, status=400)

    try:
        resultado = registrar_venta(
            request.user, request.headers.get("Idempotency-Key"), datos
        )
    except ErrorRegistroVenta as error:
        return JsonResponse(error.datos, status=error.estado)
    except OperationalError as error:
        codigo = getattr(error.__cause__, "sqlite_errorcode", 0)
        if connection.vendor != "sqlite" or (codigo & 0xFF) not in (
            sqlite3.SQLITE_BUSY,
            sqlite3.SQLITE_LOCKED,
        ):
            raise
        return JsonResponse(
            {"error": "registro_temporalmente_ocupado"},
            status=503,
            headers={"Retry-After": "1"},
        )

    venta = resultado.venta
    return JsonResponse(
        {
            "id": venta.pk,
            "numero_venta": venta.numero_venta,
            "modalidad": venta.modalidad,
            "usuario_id": venta.usuario_id,
            "fecha": venta.fecha,
            "subtotal": int(venta.subtotal),
            "total": int(venta.total),
            "metodo_pago": venta.metodo_pago,
            "monto_recibido": int(venta.monto_recibido),
            "cambio": int(venta.cambio),
            "items": [
                {
                    "producto_id": item.producto_id,
                    "nombre_producto": item.nombre_producto,
                    "cantidad": item.cantidad,
                    "precio_unitario": int(item.precio_unitario),
                    "subtotal": int(item.subtotal),
                }
                for item in resultado.items
            ],
            "repetida": resultado.repetida,
        },
        status=200 if resultado.repetida else 201,
    )

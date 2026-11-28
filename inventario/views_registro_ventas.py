from django.db import OperationalError
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from .access import permiso_requerido
from .bloqueo_caja import sqlite_ocupado
from .caja import ErrorCaja
from .peticion_financiera import ErrorJSON, comprobar_cuenta, leer_json
from .registro_ventas import (
    PERMISO_REGISTRAR_VENTA,
    ErrorRegistroVenta,
    registrar_venta,
)


@never_cache
@permiso_requerido(PERMISO_REGISTRAR_VENTA)
@require_POST
@csrf_protect
def registrar_venta_pos(request):
    comprobar_cuenta(request)
    try:
        datos = leer_json(request)
        resultado = registrar_venta(
            request.user, request.headers.get("Idempotency-Key"), datos
        )
    except ErrorJSON as error:
        return JsonResponse({"error": error.codigo}, status=error.estado)
    except (ErrorRegistroVenta, ErrorCaja) as error:
        return JsonResponse(error.datos, status=error.estado)
    except OperationalError as error:
        if not sqlite_ocupado(error):
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
            **(
                {
                    "cliente_id": venta.cliente_id,
                    "cuenta_id": resultado.cuenta_id,
                    "es_credito": True,
                    "sesion_caja_id": venta.sesion_caja_id,
                }
                if resultado.cuenta_id
                else {}
            ),
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

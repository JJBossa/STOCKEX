from functools import wraps

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from . import caja
from .access import permiso_requerido
from .historial_ventas import SANTIAGO
from .peticion_financiera import ErrorJSON, leer_json


def endpoint_caja(permiso, *, escritura=False):
    def decorator(view):
        metodo = require_POST if escritura else require_GET

        @never_cache
        @permiso_requerido(permiso)
        @metodo
        @csrf_protect
        @wraps(view)
        def responder(request, *args, **kwargs):
            try:
                if escritura:
                    kwargs.update(
                        clave=request.headers.get("Idempotency-Key"),
                        datos=leer_json(request),
                    )
                return view(request, *args, **kwargs)
            except ErrorJSON as error:
                return JsonResponse({"error": error.codigo}, status=error.estado)
            except caja.ErrorCaja as error:
                headers = {"Retry-After": "1"} if error.estado == 503 else {}
                return JsonResponse(error.datos, status=error.estado, headers=headers)

        return responder

    return decorator


def fecha_chile(fecha):
    return timezone.localtime(fecha, SANTIAGO).isoformat()


def apertura_json(sesion):
    return {
        "id": sesion.pk,
        "abierta_en": fecha_chile(sesion.abierta_en),
        "abierta_por_id": sesion.abierta_por_id,
        "efectivo_inicial": sesion.efectivo_inicial,
        "observaciones_apertura": sesion.observaciones_apertura,
    }


def datos_cierre(sesion):
    return {
        "id": sesion.pk,
        "cerrada_en": fecha_chile(sesion.cerrada_en),
        "cerrada_por_id": sesion.cerrada_por_id,
        "efectivo_contado": sesion.efectivo_contado,
    }


def cierre_json(sesion):
    return {
        **apertura_json(sesion),
        **datos_cierre(sesion),
        "observaciones_cierre": sesion.observaciones_cierre,
        "huella": str(sesion.version_resumen),
        "resumen": sesion.resumen_cierre,
    }


def resultado_json(resultado, datos):
    return JsonResponse(
        {**datos, "repetida": resultado.repetida},
        status=200 if resultado.repetida else 201,
    )


@endpoint_caja(caja.CONSULTAR_CAJA)
@ensure_csrf_cookie
def activa(request):
    sesion, resumen = caja.consultar_caja(request.user)
    if sesion is None:
        return JsonResponse({"sesion": None})
    return JsonResponse(
        {
            "sesion": apertura_json(sesion),
            "resumen": resumen,
            "huella": str(sesion.version_resumen),
        }
    )


@endpoint_caja(caja.ABRIR_CAJA, escritura=True)
def apertura(request, clave, datos):
    resultado = caja.abrir_caja(request.user, clave, datos)
    return resultado_json(resultado, apertura_json(resultado.registro))


@endpoint_caja(caja.REGISTRAR_MOVIMIENTO, escritura=True)
def movimiento(request, sesion_id, clave, datos):
    resultado = caja.registrar_movimiento(request.user, sesion_id, clave, datos)
    registro = resultado.registro
    return resultado_json(
        resultado,
        {
            "id": registro.pk,
            "sesion_id": registro.sesion_id,
            "tipo": registro.tipo,
            "importe": registro.importe,
            "motivo": registro.motivo,
            "usuario_id": registro.usuario_id,
            "fecha": fecha_chile(registro.fecha),
        },
    )


@endpoint_caja(caja.CERRAR_CAJA, escritura=True)
def cerrar(request, sesion_id, clave, datos):
    resultado = caja.cerrar_caja(request.user, sesion_id, clave, datos)
    return resultado_json(resultado, cierre_json(resultado.registro))


@endpoint_caja(caja.CONSULTAR_CIERRES)
def listar(request):
    cursor = request.GET.get("antes_de")
    if cursor is not None:
        if len(cursor) > 19 or not cursor.isascii() or not cursor.isdecimal():
            raise caja.ErrorCaja("cursor_invalido", "Envía un identificador de cierre.")
        cursor = int(cursor)
    cierres, siguiente = caja.listar_cierres(request.user, cursor)
    return JsonResponse(
        {"cierres": [datos_cierre(sesion) for sesion in cierres], "antes_de": siguiente}
    )


@endpoint_caja(caja.CONSULTAR_CIERRES)
def detalle(request, sesion_id):
    return JsonResponse(cierre_json(caja.consultar_cierre(request.user, sesion_id)))

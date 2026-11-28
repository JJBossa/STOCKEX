from django.core.exceptions import PermissionDenied
from django.db.models import Exists, OuterRef, Q
from django.http import JsonResponse

from . import caja, fiados
from .access import ventas_visibles
from .models import Cliente
from .peticion_financiera import comprobar_cuenta
from .registro_ventas import PERMISO_REGISTRAR_VENTA
from .views_caja import cursor_pagina, endpoint_caja, fecha_chile, resultado_json

LIMITE_PAGINA = 50


def cliente_existente(cliente_id):
    caja.entero(cliente_id, "cliente_id", 1, caja.MAX_ID)
    try:
        return Cliente.objects.get(pk=cliente_id)
    except Cliente.DoesNotExist as error:
        raise caja.ErrorCaja(
            "cliente_no_encontrado", "No se encontró el cliente.", estado=404
        ) from error


def cuenta_json(cuenta, *, venta_visible=False):
    estado = cuenta.estado
    if estado == "vencido" and not cuenta.inconsistente:
        estado = "parcial" if cuenta.monto_pagado else "pendiente"
    return {
        "id": cuenta.pk,
        "numero_documento": cuenta.numero_documento,
        "cliente_id": cuenta.cliente_id,
        "venta_id": cuenta.venta_id if venta_visible else None,
        "monto_total": int(cuenta.monto_total),
        "monto_pagado": int(cuenta.monto_pagado),
        "saldo": None if cuenta.inconsistente else int(cuenta.saldo_pendiente),
        "fecha_emision": cuenta.fecha_emision,
        "fecha_vencimiento": cuenta.fecha_vencimiento,
        "estado": estado,
        "estado_registrado": cuenta.estado,
        "vencida": None if cuenta.inconsistente else cuenta.esta_vencida,
        "conciliacion_requerida": cuenta.inconsistente,
    }


def abono_json(abono):
    return {
        "id": abono.pk,
        "cuenta_id": abono.cuenta_por_cobrar_id,
        "importe": int(abono.monto),
        "metodo_pago": abono.metodo_pago,
        "usuario_id": abono.usuario_id,
        "fecha_pago": abono.fecha_pago,
        "fecha_registro": fecha_chile(abono.fecha_registro),
        "sesion_caja_id": abono.sesion_caja_id,
        "referencia": abono.referencia,
        "observaciones": abono.notas,
    }


@endpoint_caja(fiados.REGISTRAR_FIADO)
def buscar_clientes(request):
    if not request.user.has_perm(PERMISO_REGISTRAR_VENTA):
        raise PermissionDenied
    comprobar_cuenta(request)
    consulta = caja.texto(request.GET.get("q", ""), "q", 0, 100)
    if len(consulta) < 2:
        return JsonResponse({"clientes": []})
    clientes = (
        Cliente.objects.filter(activo=True)
        .filter(Q(nombre__icontains=consulta) | Q(rut__icontains=consulta))
        .order_by("nombre", "pk")
        .values("id", "nombre", "rut")[:20]
    )
    return JsonResponse({"clientes": list(clientes)})


@endpoint_caja(fiados.CONSULTAR_CUENTAS)
def saldo(request, cliente_id):
    comprobar_cuenta(request)
    cliente = cliente_existente(cliente_id)
    if cliente.limite_credito < 0:
        raise fiados.error_conciliacion()
    return JsonResponse(
        {
            "cliente_id": cliente.pk,
            "limite_credito": int(cliente.limite_credito),
            **fiados.saldo_cliente(cliente),
        }
    )


@endpoint_caja(fiados.CONSULTAR_CUENTAS)
def pendientes(request, cliente_id):
    cliente = cliente_existente(cliente_id)
    cuentas = fiados.cuentas_auditadas(
        cliente.cuentas_por_cobrar.filter(fiados.PENDIENTES)
    ).annotate(
        venta_visible=Exists(
            ventas_visibles(request.user).filter(pk=OuterRef("venta_id"))
        )
    )
    pagina, cursor = caja.pagina_por_id(cuentas, cursor_pagina(request), LIMITE_PAGINA)
    return JsonResponse(
        {
            "cuentas": [
                cuenta_json(cuenta, venta_visible=cuenta.venta_visible)
                for cuenta in pagina
            ],
            "antes_de": cursor,
        }
    )


@endpoint_caja(fiados.CONSULTAR_CUENTAS)
def detalle(request, cuenta_id):
    cuenta = fiados.obtener_cuenta(cuenta_id)
    venta_visible = (
        cuenta.venta_id is not None
        and ventas_visibles(request.user).filter(pk=cuenta.venta_id).exists()
    )
    return JsonResponse(
        {**cuenta_json(cuenta, venta_visible=venta_visible), "notas": cuenta.notas}
    )


@endpoint_caja(fiados.CONSULTAR_CUENTAS)
def abonos(request, cuenta_id):
    cuenta = fiados.obtener_cuenta(cuenta_id)
    pagina, cursor = caja.pagina_por_id(
        cuenta.pagos.all(), cursor_pagina(request), LIMITE_PAGINA
    )
    return JsonResponse(
        {"abonos": [abono_json(pago) for pago in pagina], "antes_de": cursor}
    )


@endpoint_caja(fiados.REGISTRAR_ABONO, escritura=True)
def abonar(request, cuenta_id, clave, datos):
    resultado = fiados.registrar_abono(request.user, cuenta_id, clave, datos)
    return resultado_json(resultado, abono_json(resultado.registro))

"""Deudas y abonos. Las escrituras comparten el bloqueo financiero de caja."""

from datetime import date

from django.db.models import (
    BigIntegerField,
    Case,
    Count,
    Exists,
    F,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Cast, Coalesce
from django.utils import timezone

from .bloqueo_caja import invalidar_resumen, sesion_activa
from .caja import (
    MAX_ID,
    MAX_IMPORTE,
    ErrorCaja,
    ResultadoCaja,
    comprobar_permiso,
    conflicto_clave,
    entero,
    identificador,
    texto,
    transaccion_caja,
    validar_campos,
)
from .historial_ventas import SANTIAGO
from .models import Cliente, CuentaPorCobrar, PagoCliente

REGISTRAR_FIADO = "inventario.registrar_venta_fiada"
CONSULTAR_CUENTAS = "inventario.consultar_cuentas_por_cobrar"
REGISTRAR_ABONO = "inventario.registrar_abono"
PENDIENTES = Q(estado__in=CuentaPorCobrar.ESTADOS_PENDIENTES)


def fecha_opcional(valor):
    if valor is None:
        return None
    try:
        fecha = date.fromisoformat(valor)
        if fecha.isoformat() == valor:
            return valor
    except (TypeError, ValueError):
        pass
    raise ErrorCaja(
        "fecha_invalida", "Usa una fecha YYYY-MM-DD.", campo="fecha_vencimiento"
    )


def cuentas_auditadas(cuentas):
    """Identifica discrepancias sin modificar montos, estados ni pagos históricos."""
    pagos = PagoCliente.objects.filter(cuenta_por_cobrar_id=OuterRef("pk"))
    suma = (
        pagos.order_by()
        .values("cuenta_por_cobrar_id")
        .annotate(importe=Sum(Cast("monto", BigIntegerField())))
        .values("importe")
    )
    duplicadas = CuentaPorCobrar.objects.filter(venta_id=OuterRef("venta_id")).exclude(
        pk=OuterRef("pk")
    )
    coherente = (
        Q(monto_total__gt=0, monto_total=Cast("monto_total", BigIntegerField()))
        & Q(monto_pagado=F("importe_abonos"), pagos_invalidos=False, duplicada=False)
        & (
            Q(estado__in=["pendiente", "cancelado"], monto_pagado=0)
            | Q(estado="pagado", monto_pagado=F("monto_total"))
            | Q(estado="parcial", monto_pagado__gt=0, monto_pagado__lt=F("monto_total"))
            | Q(
                estado="vencido", monto_pagado__gte=0, monto_pagado__lt=F("monto_total")
            )
        )
        & (
            Q(venta__isnull=True)
            | (
                Q(venta__cliente_id=F("cliente_id"))
                & (
                    Q(estado="cancelado", venta__cancelada=True)
                    | (~Q(estado="cancelado") & Q(venta__cancelada=False))
                )
            )
        )
        & (
            Q(fiado_seguro=False)
            | Q(
                venta__metodo_pago="credito",
                venta__es_credito=True,
                venta__sesion_caja__isnull=False,
                venta__monto_recibido=0,
                venta__cambio=0,
                monto_total=F("venta__total"),
            )
        )
    )
    return cuentas.alias(
        importe_abonos=Coalesce(Subquery(suma), 0, output_field=BigIntegerField()),
        pagos_invalidos=Exists(
            pagos.filter(Q(monto__lte=0) | ~Q(monto=Cast("monto", BigIntegerField())))
        ),
        duplicada=Exists(duplicadas),
    ).annotate(
        inconsistente=Case(When(coherente, then=Value(False)), default=Value(True))
    )


def error_conciliacion():
    return ErrorCaja(
        "cuenta_inconsistente",
        "Hay datos financieros que requieren conciliación.",
        estado=409,
    )


def saldo_cliente(cliente):
    totales = cuentas_auditadas(cliente.cuentas_por_cobrar.all()).aggregate(
        pendientes=Count("pk", filter=PENDIENTES),
        saldo=Sum(
            Cast("monto_total", BigIntegerField())
            - Cast("monto_pagado", BigIntegerField()),
            filter=PENDIENTES,
            default=0,
        ),
        inconsistentes=Count("pk", filter=Q(inconsistente=True)),
    )
    if totales.pop("inconsistentes"):
        raise error_conciliacion()
    return totales


def validar_cliente_fiado(cliente_id, total):
    """Valida dentro de la transacción iniciada por el registro de ventas."""
    cliente = Cliente.objects.filter(pk=cliente_id).first()
    if cliente is None or not cliente.activo:
        raise ErrorCaja(
            "cliente_no_elegible", "Elige un cliente activo existente.", estado=409
        )
    if cliente.limite_credito < 0:
        raise error_conciliacion()
    situacion = saldo_cliente(cliente)
    if cliente.limite_credito and situacion["saldo"] + total > cliente.limite_credito:
        raise ErrorCaja(
            "limite_credito_excedido",
            "La venta supera el límite de crédito.",
            estado=409,
        )
    return cliente


def validar_limite_credito(cliente, nuevo):
    """La vista o Admin ya adquirió el bloqueo antes de leer al cliente."""
    if cliente.pk and nuevo and nuevo != cliente.limite_credito:
        if nuevo < saldo_cliente(cliente)["saldo"]:
            raise ErrorCaja(
                "limite_inferior_al_saldo",
                "El límite es menor que el saldo pendiente.",
                estado=409,
            )


def crear_deuda(venta, datos):
    return CuentaPorCobrar.objects.create(
        fiado_seguro=True,
        cliente_id=venta.cliente_id,
        venta=venta,
        monto_total=venta.total,
        fecha_emision=timezone.localdate(venta.fecha, SANTIAGO),
        fecha_vencimiento=datos["fecha_vencimiento"],
        notas=datos["notas"],
    )


def obtener_cuenta(cuenta_id):
    entero(cuenta_id, "cuenta_id", 1, MAX_ID)
    try:
        return cuentas_auditadas(CuentaPorCobrar.objects.all()).get(pk=cuenta_id)
    except CuentaPorCobrar.DoesNotExist as error:
        raise ErrorCaja(
            "cuenta_no_encontrada", "No se encontró la cuenta por cobrar.", estado=404
        ) from error


def registrar_abono(usuario, cuenta_id, clave, datos):
    comprobar_permiso(usuario, REGISTRAR_ABONO)
    entero(cuenta_id, "cuenta_id", 1, MAX_ID)
    clave = identificador(clave, "Idempotency-Key")
    validar_campos(datos, "importe", "metodo_pago", "referencia", "observaciones")
    importe = entero(datos.get("importe"), "importe", 1, MAX_IMPORTE)
    metodo = datos.get("metodo_pago")
    if metodo not in PagoCliente.METODOS_ABONO:
        raise ErrorCaja(
            "metodo_pago_invalido", "Usa efectivo, tarjeta o transferencia."
        )
    referencia = texto(datos.get("referencia", ""), "referencia", 0, 200)
    notas = texto(datos.get("observaciones", ""), "observaciones", 0, 500)
    with transaccion_caja():
        anterior = PagoCliente.objects.filter(usuario=usuario, clave=clave).first()
        if anterior is not None:
            if (
                anterior.cuenta_por_cobrar_id,
                anterior.monto,
                anterior.metodo_pago,
                anterior.referencia,
                anterior.notas,
            ) != (cuenta_id, importe, metodo, referencia, notas):
                raise conflicto_clave()
            return ResultadoCaja(anterior, repetida=True)

        cuenta = obtener_cuenta(cuenta_id)
        if cuenta.inconsistente:
            raise error_conciliacion()
        if cuenta.estado not in CuentaPorCobrar.ESTADOS_PENDIENTES:
            raise ErrorCaja(
                "cuenta_no_pagable", "La cuenta está pagada o cancelada.", estado=409
            )
        if importe > cuenta.saldo_pendiente:
            raise ErrorCaja(
                "abono_supera_saldo",
                "El importe supera el saldo pendiente.",
                estado=409,
            )

        sesion_id = sesion_activa().values_list("pk", flat=True).first()
        if sesion_id is None:
            raise ErrorCaja(
                "caja_no_abierta",
                "Abre la caja antes de registrar un abono.",
                estado=409,
            )

        abono = PagoCliente.objects.create(
            cuenta_por_cobrar=cuenta,
            monto=importe,
            fecha_pago=timezone.localdate(timezone=SANTIAGO),
            metodo_pago=metodo,
            referencia=referencia,
            notas=notas,
            usuario=usuario,
            sesion_caja_id=sesion_id,
            clave=clave,
        )
        pagado = cuenta.monto_pagado + importe
        estado = "pagado" if pagado == cuenta.monto_total else "parcial"
        CuentaPorCobrar.objects.filter(pk=cuenta.pk).update(
            monto_pagado=pagado, estado=estado
        )
        invalidar_resumen(sesion_id)
        return ResultadoCaja(abono)

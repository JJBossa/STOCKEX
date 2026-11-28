from contextlib import contextmanager
from dataclasses import dataclass

from django.core.exceptions import PermissionDenied
from django.db import OperationalError, transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from .bloqueo_caja import (
    bloquear_caja,
    invalidar_resumen,
    sesion_activa,
    sqlite_ocupado,
)
from .historial_ventas import resumir_ventas
from .models import MovimientoCaja, SesionCaja
from .peticion_financiera import uuid_v4

CONSULTAR_CAJA = "inventario.consultar_caja"
ABRIR_CAJA = "inventario.abrir_caja"
REGISTRAR_MOVIMIENTO = "inventario.registrar_movimiento_caja"
CERRAR_CAJA = "inventario.cerrar_caja"
CONSULTAR_CIERRES = "inventario.consultar_cierres_caja"

MAX_IMPORTE = 999_999_999_999
MAX_CONTADO = 2**53 - 1
MAX_ID = 2**63 - 1
LIMITE_CIERRES = 50


class ErrorCaja(Exception):
    def __init__(self, codigo, mensaje, *, estado=400, **detalles):
        super().__init__(mensaje)
        self.estado = estado
        self.datos = {"error": codigo, "mensaje": mensaje, **detalles}


@dataclass(frozen=True)
class ResultadoCaja:
    registro: SesionCaja | MovimientoCaja
    repetida: bool = False


def comprobar_permiso(usuario, permiso):
    if not usuario.is_authenticated or not usuario.has_perm(permiso):
        raise PermissionDenied


def validar_campos(datos, *admitidos):
    if not isinstance(datos, dict) or datos.keys() - set(admitidos):
        raise ErrorCaja("campos_invalidos", "Envía un objeto con los campos admitidos.")


def entero(valor, campo, minimo, maximo):
    if type(valor) is not int or not minimo <= valor <= maximo:
        raise ErrorCaja(
            "entero_invalido",
            f"{campo} debe ser un entero entre {minimo} y {maximo}.",
            campo=campo,
        )
    return valor


def texto(valor, campo, minimo, maximo):
    if isinstance(valor, str):
        valor = valor.strip()
        if minimo <= len(valor) <= maximo and "\x00" not in valor:
            try:
                valor.encode("utf-8")
            except UnicodeEncodeError:
                pass
            else:
                return valor
    raise ErrorCaja(
        "texto_invalido",
        f"{campo} debe ser un texto válido de entre {minimo} y {maximo} caracteres.",
        campo=campo,
    )


def identificador(valor, campo):
    try:
        return uuid_v4(valor)
    except ValueError as error:
        raise ErrorCaja(
            "uuid_invalido", f"{campo} requiere un UUID v4.", campo=campo
        ) from error


@contextmanager
def transaccion_caja():
    try:
        with transaction.atomic():
            bloquear_caja()
            yield
    except OperationalError as error:
        if sqlite_ocupado(error):
            raise ErrorCaja(
                "base_ocupada", "La base está ocupada. Vuelve a intentar.", estado=503
            ) from error
        raise


def obtener_sesion(sesion_id, *, cerrada=False):
    entero(sesion_id, "sesion_id", 1, MAX_ID)
    sesiones = SesionCaja.objects.all()
    if cerrada:
        sesiones = sesiones.filter(cerrada_en__isnull=False)
    try:
        return sesiones.get(pk=sesion_id)
    except SesionCaja.DoesNotExist as error:
        raise ErrorCaja(
            "sesion_no_encontrada", "No se encontró la sesión de caja.", estado=404
        ) from error


def conflicto_clave():
    return ErrorCaja(
        "clave_en_conflicto", "La operación ya se registró con otros datos.", estado=409
    )


def exigir_abierta(sesion):
    if sesion.cerrada_en is not None:
        raise ErrorCaja(
            "caja_cerrada", "La sesión de caja ya está cerrada.", estado=409
        )


def abrir_caja(usuario, clave, datos):
    comprobar_permiso(usuario, ABRIR_CAJA)
    clave = identificador(clave, "Idempotency-Key")
    validar_campos(datos, "efectivo_inicial", "observaciones")
    inicial = entero(datos.get("efectivo_inicial"), "efectivo_inicial", 0, MAX_IMPORTE)
    observaciones = texto(datos.get("observaciones", ""), "observaciones", 0, 500)
    with transaccion_caja():
        anterior = SesionCaja.objects.filter(
            abierta_por=usuario, clave_apertura=clave
        ).first()
        if anterior is not None:
            if (anterior.efectivo_inicial, anterior.observaciones_apertura) != (
                inicial,
                observaciones,
            ):
                raise conflicto_clave()
            return ResultadoCaja(anterior, repetida=True)

        if sesion_activa().exists():
            raise ErrorCaja("caja_abierta", "Ya existe una caja abierta.", estado=409)
        return ResultadoCaja(
            SesionCaja.objects.create(
                abierta_por=usuario,
                efectivo_inicial=inicial,
                observaciones_apertura=observaciones,
                clave_apertura=clave,
            )
        )


def registrar_movimiento(usuario, sesion_id, clave, datos):
    comprobar_permiso(usuario, REGISTRAR_MOVIMIENTO)
    clave = identificador(clave, "Idempotency-Key")
    validar_campos(datos, "tipo", "importe", "motivo")
    tipo = datos.get("tipo")
    if tipo not in MovimientoCaja.Tipo.values:
        raise ErrorCaja("tipo_invalido", "El tipo debe ser ingreso o retiro.")
    importe = entero(datos.get("importe"), "importe", 1, MAX_IMPORTE)
    motivo = texto(datos.get("motivo"), "motivo", 1, 250)
    with transaccion_caja():
        sesion = obtener_sesion(sesion_id)
        anterior = sesion.movimientos.filter(clave=clave).first()
        if anterior is not None:
            if (
                anterior.usuario_id,
                anterior.tipo,
                anterior.importe,
                anterior.motivo,
            ) != (
                usuario.pk,
                tipo,
                importe,
                motivo,
            ):
                raise conflicto_clave()
            return ResultadoCaja(anterior, repetida=True)

        exigir_abierta(sesion)
        movimiento = sesion.movimientos.create(
            tipo=tipo, importe=importe, motivo=motivo, usuario=usuario, clave=clave
        )
        invalidar_resumen(sesion.pk)
        return ResultadoCaja(movimiento)


def resumir_caja(sesion):
    """Compone el resumen bajo el bloqueo común de caja."""
    ventas = resumir_ventas(sesion.ventas.all())
    pagos = {
        pago.metodo: {"cantidad": pago.cantidad, "importe": pago.total}
        for pago in ventas.pagos
    }
    ingresos = Q(tipo=MovimientoCaja.Tipo.INGRESO)
    retiros = Q(tipo=MovimientoCaja.Tipo.RETIRO)
    movimientos = sesion.movimientos.aggregate(
        ingresos=Sum("importe", filter=ingresos, default=0),
        retiros=Sum("importe", filter=retiros, default=0),
        cantidad_ingresos=Count("pk", filter=ingresos),
        cantidad_retiros=Count("pk", filter=retiros),
    )
    esperado = (
        sesion.efectivo_inicial
        + pagos["efectivo"]["importe"]
        + movimientos["ingresos"]
        - movimientos["retiros"]
    )
    return {
        "efectivo_inicial": sesion.efectivo_inicial,
        "cantidad_vigente": ventas.cantidad_vigente,
        "total_vigente": ventas.total_vigente,
        "por_metodo": pagos,
        "cantidad_anulada": ventas.cantidad_anulada,
        "monto_anulado": ventas.monto_anulado,
        **movimientos,
        "efectivo_esperado": esperado,
    }


def consultar_caja(usuario):
    comprobar_permiso(usuario, CONSULTAR_CAJA)
    with transaccion_caja():
        sesion = sesion_activa().first()
        return (sesion, resumir_caja(sesion)) if sesion is not None else (None, None)


def cerrar_caja(usuario, sesion_id, clave, datos):
    comprobar_permiso(usuario, CERRAR_CAJA)
    clave = identificador(clave, "Idempotency-Key")
    validar_campos(datos, "efectivo_contado", "observaciones", "huella")
    contado = entero(datos.get("efectivo_contado"), "efectivo_contado", 0, MAX_CONTADO)
    observaciones = texto(datos.get("observaciones", ""), "observaciones", 0, 500)
    huella = identificador(datos.get("huella"), "huella")
    with transaccion_caja():
        sesion = obtener_sesion(sesion_id)
        if sesion.cerrada_en is not None and sesion.clave_cierre == clave:
            if (
                sesion.cerrada_por_id,
                sesion.efectivo_contado,
                sesion.observaciones_cierre,
                sesion.version_resumen,
            ) != (usuario.pk, contado, observaciones, huella):
                raise conflicto_clave()
            return ResultadoCaja(sesion, repetida=True)

        exigir_abierta(sesion)
        if huella != sesion.version_resumen:
            raise ErrorCaja(
                "resumen_cambiado",
                "Consulta el resumen actualizado y confirma nuevamente el cierre.",
                estado=409,
            )

        resumen = resumir_caja(sesion)
        diferencia = contado - resumen["efectivo_esperado"]
        if diferencia and not observaciones:
            raise ErrorCaja(
                "observaciones_requeridas",
                "Describe la diferencia de caja en las observaciones.",
                campo="observaciones",
            )
        clasificacion = "cuadrada"
        if diferencia:
            clasificacion = "sobrante" if diferencia > 0 else "faltante"

        sesion.cerrada_en = timezone.now()
        sesion.cerrada_por = usuario
        sesion.efectivo_contado = contado
        sesion.observaciones_cierre = observaciones
        sesion.clave_cierre = clave
        sesion.resumen_cierre = {
            **resumen,
            "diferencia": diferencia,
            "clasificacion": clasificacion,
        }
        sesion.save(
            update_fields=[
                "cerrada_en",
                "cerrada_por",
                "efectivo_contado",
                "observaciones_cierre",
                "clave_cierre",
                "resumen_cierre",
            ]
        )
        return ResultadoCaja(sesion)


def listar_cierres(usuario, antes_de=None):
    comprobar_permiso(usuario, CONSULTAR_CIERRES)
    sesiones = SesionCaja.objects.filter(cerrada_en__isnull=False)
    if antes_de is not None:
        entero(antes_de, "antes_de", 1, MAX_ID)
        sesiones = sesiones.filter(pk__lt=antes_de)
    cierres = list(
        sesiones.only("cerrada_en", "cerrada_por", "efectivo_contado").order_by("-pk")[
            : LIMITE_CIERRES + 1
        ]
    )
    siguiente = (
        cierres[LIMITE_CIERRES - 1].pk if len(cierres) > LIMITE_CIERRES else None
    )
    return cierres[:LIMITE_CIERRES], siguiente


def consultar_cierre(usuario, sesion_id):
    comprobar_permiso(usuario, CONSULTAR_CIERRES)
    return obtener_sesion(sesion_id, cerrada=True)

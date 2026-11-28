from dataclasses import dataclass

from django.core.exceptions import PermissionDenied
from django.db import OperationalError, transaction
from django.db.models import F, Q
from django.http import Http404

from .access import ventas_visibles
from .bloqueo_caja import bloquear_caja, invalidar_resumen, sqlite_ocupado
from .fiados import cuentas_auditadas
from .models import AnulacionVenta, Cotizacion, CuentaPorCobrar, Venta
from .registro_ventas import METODOS_PAGO

PERMISO_ANULAR_VENTA = "inventario.anular_venta"
MAX_MOTIVO = 250


class ErrorAnulacion(Exception):
    def __init__(self, codigo, mensaje, estado):
        super().__init__(mensaje)
        self.codigo = codigo
        self.estado = estado


@dataclass(frozen=True)
class ResultadoAnulacion:
    anulacion: AnulacionVenta
    repetida: bool


def tiene_permiso_anulacion(usuario):
    return usuario.is_authenticated and usuario.has_perms(
        ("inventario.view_venta", PERMISO_ANULAR_VENTA)
    )


def evaluar_anulacion(venta):
    """Devuelve el impedimento o la deuda que debe cancelarse con la venta."""
    if venta.cancelada:
        return "La venta ya fue anulada.", None
    if venta.sesion_caja_id and venta.sesion_caja.cerrada_en is not None:
        return "La sesión de caja de esta venta está cerrada.", None
    cuenta = None
    if venta.es_credito or venta.metodo_pago == "credito":
        if (
            not venta.es_credito
            or venta.metodo_pago != "credito"
            or not venta.sesion_caja_id
            or not venta.cliente_id
            or venta.monto_recibido != 0
            or venta.cambio != 0
        ):
            return "La venta fiada requiere una conciliación financiera.", None
        cuenta = (
            cuentas_auditadas(venta.cuenta_por_cobrar.all())
            .filter(fiado_seguro=True)
            .first()
        )
        if cuenta is None or cuenta.inconsistente or cuenta.monto_total != venta.total:
            return (
                "La cuenta de la venta fiada requiere una conciliación financiera.",
                None,
            )
        if cuenta.estado != "pendiente":
            return "La venta fiada tiene abonos confirmados.", None
    elif venta.metodo_pago not in METODOS_PAGO:
        return (
            "El método de pago requiere una reversa financiera aún no disponible.",
            None,
        )
    if (
        (cuenta is None and venta.cuenta_por_cobrar.exists())
        or venta.devoluciones.exists()
        or venta.movimientos_lote.exists()
        or Cotizacion.objects.filter(convertida_en_venta=venta).exists()
    ):
        return (
            "La venta tiene registros vinculados que requieren una reversa coordinada.",
            None,
        )
    con_stock = venta.items.filter(
        Q(stock_anterior__isnull=False) | Q(stock_despues__isnull=False)
    )
    if con_stock.filter(
        Q(stock_anterior__isnull=True)
        | Q(stock_despues__isnull=True)
        | ~Q(stock_anterior=F("stock_despues"))
    ).exists():
        return (
            "La venta histórica registra un cambio de stock o datos de stock incompletos.",
            None,
        )
    return None, cuenta


def impedimento_anulacion(venta):
    return evaluar_anulacion(venta)[0]


def normalizar_motivo(motivo):
    motivo = motivo.strip() if isinstance(motivo, str) else ""
    if not motivo or len(motivo) > MAX_MOTIVO or "\x00" in motivo:
        raise ErrorAnulacion(
            "motivo_invalido",
            f"Ingresa un motivo válido de entre 1 y {MAX_MOTIVO} caracteres.",
            400,
        )
    return motivo


def anular_venta(usuario, venta_id, motivo):
    if not tiene_permiso_anulacion(usuario):
        raise PermissionDenied
    motivo = normalizar_motivo(motivo)
    # Evalúa permisos y alcance antes de que SQLite tome el bloqueo de escritura.
    visibles = ventas_visibles(usuario)
    try:
        with transaction.atomic():
            bloquear_caja()
            try:
                venta = visibles.select_for_update().get(pk=venta_id)
            except Venta.DoesNotExist as error:
                raise Http404("Venta no encontrada.") from error
            if venta.cancelada:
                anterior = getattr(venta, "anulacion", None)
                if (
                    anterior
                    and anterior.usuario_id == usuario.pk
                    and anterior.motivo == motivo
                ):
                    return ResultadoAnulacion(anterior, repetida=True)
                raise ErrorAnulacion(
                    "ya_anulada", "La venta ya fue anulada. Consulta el detalle.", 409
                )
            impedimento, cuenta = evaluar_anulacion(venta)
            if impedimento:
                raise ErrorAnulacion("no_anulable", impedimento, 409)
            venta.cancelada = True
            venta.save(update_fields=["cancelada"])
            anulacion = AnulacionVenta.objects.create(
                venta=venta, usuario=usuario, motivo=motivo
            )
            if cuenta is not None:
                CuentaPorCobrar.objects.filter(pk=cuenta.pk).update(estado="cancelado")
            if venta.sesion_caja_id is not None:
                invalidar_resumen(venta.sesion_caja_id)
            return ResultadoAnulacion(anulacion, repetida=False)
    except OperationalError as error:
        if sqlite_ocupado(error):
            raise ErrorAnulacion(
                "base_ocupada",
                "La base está ocupada. Comprueba el estado y vuelve a intentar.",
                503,
            ) from error
        raise

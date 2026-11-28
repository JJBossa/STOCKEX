from dataclasses import dataclass

from django.core.exceptions import PermissionDenied
from django.db import OperationalError, connection, transaction
from django.db.models import F, Q
from django.http import Http404

from .access import ventas_visibles
from .models import AnulacionVenta, Cotizacion, Venta
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


def impedimento_anulacion(venta):
    """Reglas que el servicio vuelve a evaluar bajo bloqueo (extensión para STK-06)."""
    if venta.cancelada:
        return "La venta ya fue anulada."
    if venta.es_credito or venta.metodo_pago not in METODOS_PAGO:
        return "El método de pago requiere una reversa financiera aún no disponible."
    if (
        venta.cuenta_por_cobrar.exists()
        or venta.devoluciones.exists()
        or venta.movimientos_lote.exists()
        or Cotizacion.objects.filter(convertida_en_venta=venta).exists()
    ):
        return (
            "La venta tiene registros vinculados que requieren una reversa coordinada."
        )
    con_stock = venta.items.filter(
        Q(stock_anterior__isnull=False) | Q(stock_despues__isnull=False)
    )
    if con_stock.filter(
        Q(stock_anterior__isnull=True)
        | Q(stock_despues__isnull=True)
        | ~Q(stock_anterior=F("stock_despues"))
    ).exists():
        return "La venta histórica registra un cambio de stock o datos de stock incompletos."
    return None


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
            if connection.vendor == "sqlite":
                # Adquiere el bloqueo de escritor antes de leer, sin tocar ninguna fila.
                Venta.objects.filter(pk__isnull=True).update(cancelada=F("cancelada"))
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
            impedimento = impedimento_anulacion(venta)
            if impedimento:
                raise ErrorAnulacion("no_anulable", impedimento, 409)
            venta.cancelada = True
            venta.save(update_fields=["cancelada"])
            anulacion = AnulacionVenta.objects.create(
                venta=venta, usuario=usuario, motivo=motivo
            )
            return ResultadoAnulacion(anulacion, repetida=False)
    except OperationalError as error:
        codigo = getattr(error.__cause__, "sqlite_errorname", "")
        if connection.vendor == "sqlite" and codigo.startswith(
            ("SQLITE_BUSY", "SQLITE_LOCKED")
        ):
            raise ErrorAnulacion(
                "base_ocupada",
                "La base está ocupada. Comprueba el estado y vuelve a intentar.",
                503,
            ) from error
        raise

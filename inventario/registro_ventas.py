import hashlib
import json
from dataclasses import dataclass

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction

from .bloqueo_caja import bloquear_caja, invalidar_resumen, sesion_activa
from .models import ItemVenta, Producto, RegistroVenta, Venta
from .peticion_financiera import uuid_v4

PERMISO_REGISTRAR_VENTA = "inventario.registrar_venta"
MAX_MONTO = 999_999_999_999
MAX_SUBTOTAL_ITEM = 9_999_999_999
MAX_ID_PRODUCTO = 2**63 - 1
MAX_ITEMS = 100
MAX_CANTIDAD = 1_000_000
METODOS_PAGO = ("efectivo", "tarjeta", "transferencia")


class ErrorRegistroVenta(Exception):
    def __init__(self, codigo, mensaje, *, estado=400, **detalles):
        super().__init__(mensaje)
        self.estado = estado
        self.datos = {"error": codigo, "mensaje": mensaje, **detalles}


@dataclass(frozen=True)
class ResultadoRegistroVenta:
    venta: Venta
    items: list[ItemVenta]
    repetida: bool = False


def entero_positivo(valor, campo, maximo):
    if type(valor) is not int or not 1 <= valor <= maximo:
        raise ErrorRegistroVenta(
            "entero_invalido",
            f"{campo} debe ser un entero entre 1 y {maximo}.",
            campo=campo,
        )
    return valor


def normalizar_clave(clave):
    try:
        return uuid_v4(clave)
    except ValueError as error:
        raise ErrorRegistroVenta(
            "clave_invalida", "Envía un UUID v4 en Idempotency-Key."
        ) from error


def normalizar_items(datos):
    if not isinstance(datos, list) or not 1 <= len(datos) <= MAX_ITEMS:
        raise ErrorRegistroVenta(
            "items_invalidos", f"Envía entre 1 y {MAX_ITEMS} productos."
        )
    items = {}
    for item in datos:
        if not isinstance(item, dict) or item.keys() != {
            "producto_id",
            "cantidad",
            "precio_visto",
        }:
            raise ErrorRegistroVenta(
                "item_invalido",
                "Cada ítem requiere producto_id, cantidad y precio_visto.",
            )
        pk = entero_positivo(item["producto_id"], "producto_id", MAX_ID_PRODUCTO)
        if pk in items:
            raise ErrorRegistroVenta(
                "producto_duplicado",
                "Envía cada producto una sola vez.",
                producto_id=pk,
            )
        items[pk] = (
            entero_positivo(item["cantidad"], "cantidad", MAX_CANTIDAD),
            entero_positivo(item["precio_visto"], "precio_visto", MAX_SUBTOTAL_ITEM),
        )
    return dict(sorted(items.items()))


def normalizar_venta(datos):
    modalidad = datos.get("modalidad") if isinstance(datos, dict) else None
    if modalidad not in Venta.Modalidad.values:
        raise ErrorRegistroVenta(
            "modalidad_invalida", "Usa la modalidad rapida o detallada."
        )
    campo = "monto" if modalidad == Venta.Modalidad.RAPIDA else "items"
    if datos.keys() - {"modalidad", "metodo_pago", "monto_recibido", campo}:
        raise ErrorRegistroVenta(
            "campos_invalidos", "La solicitud contiene campos no admitidos."
        )
    metodo_pago = datos.get("metodo_pago")
    if metodo_pago not in METODOS_PAGO:
        raise ErrorRegistroVenta(
            "metodo_pago_invalido", "Usa efectivo, tarjeta o transferencia."
        )
    recibido = datos.get("monto_recibido")
    if "monto_recibido" in datos:
        recibido = entero_positivo(recibido, "monto_recibido", MAX_MONTO)
    detalle = (
        entero_positivo(datos.get(campo), campo, MAX_MONTO)
        if campo == "monto"
        else normalizar_items(datos.get(campo))
    )
    return {
        "modalidad": modalidad,
        "metodo_pago": metodo_pago,
        "monto_recibido": recibido,
        campo: detalle,
    }


def preparar_items(solicitados):
    productos = {
        producto.pk: producto
        for producto in Producto.objects.filter(pk__in=solicitados)
        .order_by("pk")
        .select_for_update()
        .only("nombre", "precio", "activo")
    }
    no_disponibles = [
        pk for pk in solicitados if pk not in productos or not productos[pk].activo
    ]
    if no_disponibles:
        raise ErrorRegistroVenta(
            "productos_no_disponibles",
            "Hay productos inexistentes o inactivos.",
            estado=409,
            producto_ids=no_disponibles,
        )

    items = []
    precios_cambiados = []
    for pk, (cantidad, precio_visto) in solicitados.items():
        producto = productos[pk]
        precio = producto.precio
        if (
            not precio.is_finite()
            or not 1 <= precio <= MAX_SUBTOTAL_ITEM
            or precio != precio.to_integral_value()
        ):
            raise ErrorRegistroVenta(
                "precio_catalogo_invalido",
                "El precio base de un producto no es un importe positivo entero en CLP.",
                estado=409,
                producto_id=pk,
            )
        precio = int(precio)
        if precio != precio_visto:
            precios_cambiados.append({"producto_id": pk, "precio_vigente": precio})
        items.append(
            ItemVenta(
                producto=producto,
                nombre_producto=producto.nombre,
                cantidad=cantidad,
                precio_unitario=precio,
                subtotal=cantidad * precio,
                stock_anterior=None,
                stock_despues=None,
            )
        )
    if precios_cambiados:
        raise ErrorRegistroVenta(
            "precio_cambiado",
            "Revisa los precios vigentes y confirma nuevamente la venta.",
            estado=409,
            productos=precios_cambiados,
        )
    for item in items:
        entero_positivo(item.subtotal, "subtotal_item", MAX_SUBTOTAL_ITEM)
    return items


def validar_pago(metodo_pago, recibido, total):
    if recibido is None:
        recibido = total
    if metodo_pago == "efectivo":
        if recibido < total:
            raise ErrorRegistroVenta(
                "efectivo_insuficiente", "El efectivo recibido es menor que el total."
            )
    elif recibido != total:
        raise ErrorRegistroVenta(
            "monto_pago_inexacto", "El monto recibido debe coincidir con el total."
        )
    return recibido, recibido - total


def registrar_venta(usuario, clave, datos):
    """Registra una venta o recupera la operación original de la misma clave."""
    if not usuario.is_authenticated or not usuario.has_perm(PERMISO_REGISTRAR_VENTA):
        raise PermissionDenied
    clave = normalizar_clave(clave)
    datos = normalizar_venta(datos)
    huella = hashlib.sha256(
        json.dumps(datos, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    modalidad = datos["modalidad"]

    reserva_creada = False
    try:
        with transaction.atomic():
            bloquear_caja()
            registro = RegistroVenta.objects.create(
                usuario=usuario, clave=clave, huella=huella
            )
            reserva_creada = True
            # Compatibilidad STK-06A: el POS aún puede registrar sin sesión abierta.
            sesion_id = sesion_activa().values_list("pk", flat=True).first()
            items = (
                preparar_items(datos["items"])
                if modalidad == Venta.Modalidad.DETALLADA
                else []
            )
            total = (
                datos.get("monto")
                if modalidad == Venta.Modalidad.RAPIDA
                else sum(i.subtotal for i in items)
            )
            entero_positivo(total, "total", MAX_MONTO)
            recibido, cambio = validar_pago(
                datos["metodo_pago"], datos["monto_recibido"], total
            )
            venta = Venta.objects.create(
                usuario=usuario,
                sesion_caja_id=sesion_id,
                modalidad=modalidad,
                subtotal=total,
                total=total,
                metodo_pago=datos["metodo_pago"],
                monto_recibido=recibido,
                cambio=cambio,
            )
            if items:
                for item in items:
                    item.venta = venta
                ItemVenta.objects.bulk_create(items)
            registro.venta = venta
            registro.save(update_fields=["venta"])
            if sesion_id is not None:
                invalidar_resumen(sesion_id)
            return ResultadoRegistroVenta(venta, items)
    except IntegrityError:
        if reserva_creada:
            raise
        # Una reserva ganadora sólo es visible después de confirmar también la venta y los ítems.
        anterior = (
            RegistroVenta.objects.select_related("venta")
            .filter(usuario=usuario, clave=clave)
            .first()
        )
        if anterior is None or anterior.venta_id is None:
            raise
        if anterior.huella != huella:
            raise ErrorRegistroVenta(
                "clave_en_conflicto",
                "La clave ya se usó para una solicitud diferente.",
                estado=409,
            )
        venta = anterior.venta
        items = (
            list(venta.items.all())
            if venta.modalidad == Venta.Modalidad.DETALLADA
            else []
        )
        return ResultadoRegistroVenta(venta, items, repetida=True)

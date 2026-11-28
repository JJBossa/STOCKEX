from django.core.paginator import Paginator
from django.db.models import (
    BigIntegerField,
    Count,
    Exists,
    OuterRef,
    Q,
    Subquery,
    Sum,
)
from django.db.models.functions import Cast, Coalesce
from django.http import Http404, QueryDict
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from . import caja, fiados
from .access import permiso_requerido, ventas_visibles
from .bloqueo_caja import sesion_activa
from .historial_ventas import SANTIAGO
from .models import Cliente, CuentaPorCobrar, PagoCliente
from .peticion_financiera import comprobar_cuenta
from .views_fiados import LIMITE_PAGINA, cliente_existente, cuenta_json

CUENTAS = {
    "pendientes": fiados.PENDIENTES,
    "pagadas": Q(estado="pagado"),
    "canceladas": Q(estado="cancelado"),
    "todas": Q(),
}
FILTROS_PANEL = ("q", "deuda", "vencidas", "activo", "orden", "page")
IMPORTE_DEUDA = Cast("monto_total", BigIntegerField()) - Cast(
    "monto_pagado", BigIntegerField()
)


def hoy_chile():
    return timezone.localdate(timezone=SANTIAGO)


def indicadores(auditadas, vencidas, hoy):
    totales = auditadas.aggregate(
        saldo=Sum(IMPORTE_DEUDA, filter=fiados.PENDIENTES, default=0),
        vencido=Sum(IMPORTE_DEUDA, filter=vencidas, default=0),
        clientes=Count("cliente", filter=fiados.PENDIENTES, distinct=True),
        pendientes=Count("pk", filter=fiados.PENDIENTES),
        inconsistentes=Count("pk", filter=Q(inconsistente=True)),
    )
    abonos_hoy = PagoCliente.objects.filter(fecha_pago=hoy)
    recibidos = abonos_hoy.aggregate(
        importe=Sum(Cast("monto", BigIntegerField()), default=0),
        requieren_revision=Count(
            "pk",
            filter=Exists(
                auditadas.filter(
                    pk=OuterRef("cuenta_por_cobrar_id"), inconsistente=True
                )
            ),
        ),
    )
    if totales["inconsistentes"]:
        totales["saldo"] = totales["vencido"] = None
    totales["abonos_hoy"] = (
        None if recibidos["requieren_revision"] else recibidos["importe"]
    )
    return totales


def parametros_panel(consulta):
    return {nombre: consulta[nombre] for nombre in FILTROS_PANEL if nombre in consulta}


def lista_url(lista):
    consulta = QueryDict("", mutable=True)
    consulta.update(lista)
    return reverse("fiados_panel") + ("?" + consulta.urlencode() if consulta else "")


def pagina_cursor(request, registros, campo):
    raw = request.GET.get(campo)
    cursor = None
    if raw is not None:
        try:
            if not (raw.isascii() and raw.isdecimal() and len(raw) <= 19):
                raise ValueError
            cursor = int(raw)
            caja.entero(cursor, campo, 1, caja.MAX_ID)
        except (ValueError, caja.ErrorCaja) as error:
            raise Http404("Página inválida.") from error
    pagina, siguiente = caja.pagina_por_id(registros, cursor, LIMITE_PAGINA)
    if siguiente is None:
        return pagina, ""
    parametros = request.GET.copy()
    parametros[campo] = str(siguiente)
    parametros.pop("fragmento", None)
    return pagina, "?" + parametros.urlencode()


@never_cache
@permiso_requerido(fiados.CONSULTAR_CUENTAS)
@require_GET
def panel(request):
    hoy = hoy_chile()
    vencidas = fiados.PENDIENTES & Q(fecha_vencimiento__lt=hoy)
    auditadas = fiados.cuentas_auditadas(CuentaPorCobrar.objects.all())
    propias = auditadas.filter(cliente_id=OuterRef("pk"))
    pendientes = propias.filter(fiados.PENDIENTES)
    saldos = (
        pendientes.order_by()
        .values("cliente_id")
        .annotate(total=Sum(IMPORTE_DEUDA), cantidad=Count("pk"))
    )
    clientes = Cliente.objects.annotate(
        saldo=Coalesce(
            Subquery(saldos.values("total")), 0, output_field=BigIntegerField()
        ),
        pendientes=Coalesce(Subquery(saldos.values("cantidad")), 0),
        vencidas=Exists(propias.filter(vencidas)),
        requiere_conciliacion=Exists(propias.filter(inconsistente=True)),
    )
    filtros = parametros_panel(request.GET)
    q = filtros.get("q", "").strip()[:100]
    if q:
        clientes = clientes.filter(Q(nombre__icontains=q) | Q(rut__icontains=q))
    if filtros.get("deuda") == "1":
        clientes = clientes.filter(Exists(pendientes))
    if filtros.get("vencidas") == "1":
        clientes = clientes.filter(vencidas=True)
    if filtros.get("activo") in {"1", "0"}:
        clientes = clientes.filter(activo=filtros["activo"] == "1")
    orden = (
        ["requiere_conciliacion", "-saldo"] if filtros.get("orden") == "saldo" else []
    )
    pagina = Paginator(clientes.order_by(*orden, "nombre", "pk"), 30).get_page(
        request.GET.get("page")
    )
    consulta = request.GET.copy()
    consulta.pop("page", None)
    return render(
        request,
        "inventario/fiados/panel.html",
        {
            "totales": indicadores(auditadas, vencidas, hoy),
            "hoy": hoy,
            "pagina": pagina,
            "filtros": filtros,
            "q": q,
            "sin_pagina": consulta.urlencode(),
            "lista": request.GET.urlencode(),
        },
    )


def cliente_html(cliente_id):
    try:
        return cliente_existente(cliente_id)
    except caja.ErrorCaja as error:
        raise Http404("Cliente no encontrado.") from error


def cuenta_html(cuenta_id):
    try:
        return fiados.obtener_cuenta(cuenta_id)
    except caja.ErrorCaja as error:
        raise Http404("Cuenta no encontrada.") from error


@never_cache
@permiso_requerido(fiados.CONSULTAR_CUENTAS)
@require_GET
def cliente(request, cliente_id):
    titular = cliente_html(cliente_id)
    lista = request.GET.get("lista", "")
    estado = request.GET.get("estado", "pendientes")
    estado = estado if estado in CUENTAS else "pendientes"
    try:
        situacion = fiados.saldo_cliente(titular)
    except caja.ErrorCaja:
        situacion = None
    cuentas, mas_cuentas = pagina_cursor(
        request,
        fiados.cuentas_auditadas(titular.cuentas_por_cobrar.filter(CUENTAS[estado])),
        "cuentas_antes_de",
    )
    pagos, mas_pagos = pagina_cursor(
        request,
        PagoCliente.objects.filter(cuenta_por_cobrar__cliente=titular).select_related(
            "usuario", "cuenta_por_cobrar"
        ),
        "abonos_antes_de",
    )
    return render(
        request,
        "inventario/fiados/cliente.html",
        {
            "cliente": titular,
            "situacion": situacion,
            "estado": estado,
            "limite_valido": titular.limite_credito >= 0,
            "credito_disponible": (
                max(0, titular.limite_credito - situacion["saldo"])
                if situacion is not None and titular.limite_credito > 0
                else None
            ),
            "cuentas": [cuenta_json(c) for c in cuentas],
            "pagos": pagos,
            "mas_pagos": mas_pagos,
            "mas_cuentas": mas_cuentas,
            "lista": lista,
            "volver": lista_url(parametros_panel(QueryDict(lista))),
        },
    )


@never_cache
@permiso_requerido(fiados.CONSULTAR_CUENTAS)
@require_GET
def cuenta(request, cuenta_id):
    comprobar_cuenta(request)
    registro = cuenta_html(cuenta_id)
    lista = request.GET.get("lista", "")
    pagos, mas_pagos = pagina_cursor(
        request,
        registro.pagos.select_related("usuario", "cuenta_por_cobrar"),
        "abonos_antes_de",
    )
    puede_abonar = request.user.has_perm(fiados.REGISTRAR_ABONO)
    venta = None
    if registro.venta_id:
        venta = (
            ventas_visibles(request.user)
            .filter(pk=registro.venta_id)
            .values("id", "numero_venta")
            .first()
        )
    plantilla = (
        "inventario/fiados/fragmento_cuenta.html"
        if request.GET.get("fragmento") == "abono"
        else "inventario/fiados/cuenta.html"
    )
    datos = cuenta_json(registro)
    return render(
        request,
        plantilla,
        {
            "registro": registro,
            "cuenta": datos,
            "cliente": registro.cliente,
            "venta": venta,
            "pagos": pagos,
            "mas_pagos": mas_pagos,
            "lista": lista,
            "puede_abonar": puede_abonar,
            "caja_abierta": puede_abonar and sesion_activa().exists(),
            "cuenta_pagable": datos["saldo"] is not None and datos["saldo"] > 0,
        },
    )

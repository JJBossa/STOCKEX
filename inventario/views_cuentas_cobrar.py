"""
Vistas para gestión de cuentas por cobrar
"""
from django.shortcuts import render, get_object_or_404
from django.db.models import Q, Sum
from django.core.paginator import Paginator
from django.utils import timezone
from .models import CuentaPorCobrar
from .utils import es_administrador
from .access import operaciones_financieras_suspendidas, permiso_requerido


@permiso_requerido('inventario.view_cuentaporcobrar')
def listar_cuentas_cobrar(request):
    """Lista todas las cuentas por cobrar"""
    cuentas = CuentaPorCobrar.objects.all().select_related('cliente', 'venta')
    
    # Filtros
    estado = request.GET.get('estado', '')
    if estado:
        cuentas = cuentas.filter(estado=estado)
    
    cliente_id = request.GET.get('cliente', '')
    if cliente_id:
        cuentas = cuentas.filter(cliente_id=cliente_id)
    
    vencidas = request.GET.get('vencidas', '')
    if vencidas == '1':
        hoy = timezone.now().date()
        cuentas = cuentas.filter(
            fecha_vencimiento__lt=hoy,
            estado__in=['pendiente', 'parcial']
        )
    
    # Búsqueda
    query = request.GET.get('q', '').strip()
    if query:
        cuentas = cuentas.filter(
            Q(numero_documento__icontains=query) |
            Q(cliente__nombre__icontains=query) |
            Q(cliente__rut__icontains=query)
        )
    
    # Ordenamiento
    orden = request.GET.get('orden', '-fecha_emision')
    cuentas = cuentas.order_by(orden)
    
    # Paginación
    paginator = Paginator(cuentas, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Estadísticas
    total_pendiente = cuentas.filter(estado__in=['pendiente', 'parcial']).aggregate(
        total=Sum('monto_total') - Sum('monto_pagado')
    )['total'] or 0
    
    context = {
        'cuentas': page_obj,
        'query': query,
        'estado': estado,
        'cliente_id': cliente_id,
        'vencidas': vencidas,
        'orden': orden,
        'total_pendiente': max(0, total_pendiente),
        'es_admin': es_administrador(request.user),
    }
    
    return render(request, 'inventario/listar_cuentas_cobrar.html', context)


@permiso_requerido('inventario.view_cuentaporcobrar')
def detalle_cuenta_cobrar(request, cuenta_id):
    """Detalle de una cuenta por cobrar con pagos"""
    cuenta = get_object_or_404(CuentaPorCobrar.objects.select_related('cliente', 'venta'), id=cuenta_id)
    pagos = cuenta.pagos.all().order_by('-fecha_pago')
    
    context = {
        'cuenta': cuenta,
        'pagos': pagos,
        'es_admin': es_administrador(request.user),
    }
    
    return render(request, 'inventario/detalle_cuenta_cobrar.html', context)


@permiso_requerido('inventario.add_pagocliente')
def registrar_pago(request, cuenta_id):
    return operaciones_financieras_suspendidas()


@permiso_requerido('inventario.add_cuentaporcobrar')
def crear_cuenta_cobrar(request, cliente_id=None):
    return operaciones_financieras_suspendidas()

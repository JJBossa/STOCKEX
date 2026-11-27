"""
Vistas para el sistema de devoluciones
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.utils import timezone
from .models import Devolucion
from .utils import es_administrador
from .access import operaciones_financieras_suspendidas, permiso_requerido


@login_required
def listar_devoluciones(request):
    """Lista todas las devoluciones"""
    if not es_administrador(request.user):
        messages.error(request, 'No tienes permisos para acceder a esta sección.')
        return redirect('inicio')
    
    devoluciones = Devolucion.objects.all().select_related('venta', 'cliente', 'procesado_por').order_by('-fecha_solicitud')
    
    # Filtros
    estado = request.GET.get('estado', '')
    venta_id = request.GET.get('venta_id', '')
    fecha_desde = request.GET.get('fecha_desde', '')
    fecha_hasta = request.GET.get('fecha_hasta', '')
    
    if estado:
        devoluciones = devoluciones.filter(estado=estado)
    if venta_id:
        devoluciones = devoluciones.filter(venta_id=venta_id)
    if fecha_desde:
        devoluciones = devoluciones.filter(fecha_solicitud__date__gte=fecha_desde)
    if fecha_hasta:
        devoluciones = devoluciones.filter(fecha_solicitud__date__lte=fecha_hasta)
    
    # Paginación
    paginator = Paginator(devoluciones, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Estadísticas
    total_devoluciones = devoluciones.count()
    pendientes = devoluciones.filter(estado='pendiente').count()
    procesadas = devoluciones.filter(estado='procesada').count()
    monto_total = sum(float(d.monto_devolver) for d in devoluciones.filter(estado='procesada'))
    
    context = {
        'page_obj': page_obj,
        'estado': estado,
        'venta_id': venta_id,
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta,
        'total_devoluciones': total_devoluciones,
        'pendientes': pendientes,
        'procesadas': procesadas,
        'monto_total': monto_total,
        'es_admin': True,
    }
    return render(request, 'inventario/listar_devoluciones.html', context)


@permiso_requerido('inventario.add_devolucion')
def crear_devolucion(request, venta_id=None):
    return operaciones_financieras_suspendidas()


@login_required
def detalle_devolucion(request, devolucion_id):
    """Detalle de una devolución específica"""
    if not es_administrador(request.user):
        messages.error(request, 'No tienes permisos para acceder a esta sección.')
        return redirect('inicio')
    
    devolucion = get_object_or_404(
        Devolucion.objects.select_related('venta', 'cliente', 'procesado_por'),
        id=devolucion_id
    )
    items = devolucion.items.all().select_related('item_venta__producto')
    
    context = {
        'devolucion': devolucion,
        'items': items,
        'es_admin': True,
    }
    return render(request, 'inventario/detalle_devolucion.html', context)


@permiso_requerido('inventario.change_devolucion')
def procesar_devolucion(request, devolucion_id):
    return operaciones_financieras_suspendidas()


@permiso_requerido('inventario.change_devolucion')
def rechazar_devolucion(request, devolucion_id):
    return operaciones_financieras_suspendidas()

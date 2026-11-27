from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Sum
from django.core.paginator import Paginator
from .models import Producto, Cliente
from .utils import es_administrador
from .access import operaciones_financieras_suspendidas, permiso_requerido, ventas_visibles

@permiso_requerido('inventario.view_venta')
def punto_venta(request):
    """Vista de consulta del punto de venta durante la suspensión."""
    
    # Obtener productos activos para búsqueda
    productos = Producto.objects.filter(activo=True).order_by('nombre')
    
    # Obtener clientes activos para selección
    clientes = Cliente.objects.none()
    if request.user.has_perm('inventario.view_cliente'):
        clientes = Cliente.objects.filter(activo=True).order_by('nombre')
    
    context = {
        'productos': productos,
        'clientes': clientes,
        'es_admin': es_administrador(request.user),
    }
    
    return render(request, 'inventario/punto_venta.html', context)

@permiso_requerido('inventario.view_venta')
def buscar_producto_pos(request):
    """API para buscar productos por código de barras en el POS."""
    
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    
    codigo = request.POST.get('codigo', '').strip()
    
    if not codigo:
        return JsonResponse({'error': 'Código requerido'}, status=400)
    
    try:
        # Buscar por SKU (código de barras)
        producto = Producto.objects.get(sku=codigo, activo=True)
        
        # Verificar stock
        if producto.stock <= 0:
            return JsonResponse({
                'encontrado': True,
                'sin_stock': True,
                'producto': {
                    'id': producto.id,
                    'nombre': producto.nombre,
                    'precio': float(producto.precio_promo or producto.precio),
                    'stock': producto.stock,
                },
                'mensaje': 'Producto sin stock disponible'
            })
        
        return JsonResponse({
            'encontrado': True,
            'producto': {
                'id': producto.id,
                'nombre': producto.nombre,
                'precio': float(producto.precio_promo or producto.precio),
                'precio_normal': float(producto.precio),
                'precio_promo': float(producto.precio_promo) if producto.precio_promo else None,
                'stock': producto.stock,
                'sku': producto.sku,
            }
        })
    except Producto.DoesNotExist:
        return JsonResponse({
            'encontrado': False,
            'mensaje': f'Producto con código {codigo} no encontrado'
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@permiso_requerido('inventario.view_venta')
def procesar_venta(request):
    return operaciones_financieras_suspendidas()


@permiso_requerido('inventario.view_venta')
def listar_ventas(request):
    """Lista todas las ventas - Usuarios normales solo ven sus propias ventas"""
    
    ventas = ventas_visibles(request.user).select_related('usuario').prefetch_related('items')
    
    # Filtros
    fecha_desde = request.GET.get('fecha_desde', '')
    fecha_hasta = request.GET.get('fecha_hasta', '')
    metodo_pago = request.GET.get('metodo_pago', '')
    numero_venta = request.GET.get('numero_venta', '')
    
    if fecha_desde:
        ventas = ventas.filter(fecha__gte=fecha_desde)
    if fecha_hasta:
        ventas = ventas.filter(fecha__lte=fecha_hasta)
    if metodo_pago:
        ventas = ventas.filter(metodo_pago=metodo_pago)
    if numero_venta:
        ventas = ventas.filter(numero_venta__icontains=numero_venta)
    
    # Estadísticas
    total_ventas = ventas.aggregate(Sum('total'))['total__sum'] or 0
    total_ventas_count = ventas.count()
    
    # Paginación
    paginator = Paginator(ventas, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'ventas': page_obj,
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta,
        'metodo_pago': metodo_pago,
        'numero_venta': numero_venta,
        'total_ventas': total_ventas,
        'total_ventas_count': total_ventas_count,
        'es_admin': es_administrador(request.user),
    }
    
    return render(request, 'inventario/listar_ventas.html', context)

@permiso_requerido('inventario.view_venta')
def detalle_venta(request, venta_id):
    """Detalle de una venta - Usuarios normales solo ven sus propias ventas"""
    venta = get_object_or_404(ventas_visibles(request.user), id=venta_id)
    items = venta.items.select_related('producto').all()
    
    context = {
        'venta': venta,
        'items': items,
        'es_admin': es_administrador(request.user),
    }
    
    return render(request, 'inventario/detalle_venta.html', context)

@permiso_requerido('inventario.change_venta')
def cancelar_venta(request, venta_id):
    return operaciones_financieras_suspendidas()


@login_required
def limpiar_historial_ventas(request):
    return JsonResponse({'error': 'El historial de ventas no se puede eliminar.'}, status=403)

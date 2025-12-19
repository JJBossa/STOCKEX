"""
Vistas para gestión de almacenes
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Sum, F
from django.core.paginator import Paginator
from django.db import transaction
from django.utils import timezone
from .models import Almacen, StockAlmacen, Producto, Transferencia, ItemTransferencia
from .utils import es_admin_bossa, logger


@login_required
def listar_almacenes(request):
    """Lista todos los almacenes"""
    almacenes = Almacen.objects.all().order_by('nombre')
    
    activo = request.GET.get('activo', '')
    if activo == '1':
        almacenes = almacenes.filter(activo=True)
    elif activo == '0':
        almacenes = almacenes.filter(activo=False)
    
    # Agregar estadísticas
    for almacen in almacenes:
        almacen.productos_count = StockAlmacen.objects.filter(almacen=almacen).count()
        almacen.stock_bajo_count = StockAlmacen.objects.filter(
            almacen=almacen
        ).filter(cantidad__lte=F('stock_minimo')).count()
    
    context = {
        'almacenes': almacenes,
        'activo': activo,
        'es_admin': es_admin_bossa(request.user),
    }
    
    return render(request, 'inventario/listar_almacenes.html', context)


@login_required
def crear_almacen(request):
    """Crear un nuevo almacén"""
    if not es_admin_bossa(request.user):
        messages.error(request, 'No tienes permisos para realizar esta acción.')
        return redirect('listar_almacenes')
    
    if request.method == 'POST':
        nombre = request.POST.get('nombre', '').strip()
        codigo = request.POST.get('codigo', '').strip()
        direccion = request.POST.get('direccion', '').strip() or None
        telefono = request.POST.get('telefono', '').strip() or None
        responsable = request.POST.get('responsable', '').strip() or None
        notas = request.POST.get('notas', '').strip() or None
        
        if not nombre or not codigo:
            messages.error(request, 'El nombre y código son requeridos.')
        else:
            try:
                almacen = Almacen.objects.create(
                    nombre=nombre,
                    codigo=codigo,
                    direccion=direccion,
                    telefono=telefono,
                    responsable=responsable,
                    notas=notas
                )
                messages.success(request, f'Almacén "{almacen.nombre}" creado exitosamente.')
                return redirect('detalle_almacen', almacen_id=almacen.id)
            except Exception as e:
                logger.error(f'Error al crear almacén: {str(e)}')
                messages.error(request, f'Error al crear almacén: {str(e)}')
    
    return render(request, 'inventario/crear_almacen.html', {
        'es_admin': True,
    })


@login_required
def detalle_almacen(request, almacen_id):
    """Detalle de un almacén con stock"""
    almacen = get_object_or_404(Almacen, id=almacen_id)
    
    # Stock del almacén
    stock_items = StockAlmacen.objects.filter(almacen=almacen).select_related('producto')
    
    # Filtros
    stock_bajo = request.GET.get('stock_bajo', '')
    if stock_bajo == '1':
        stock_items = stock_items.filter(cantidad__lte=F('stock_minimo'))
    
    query = request.GET.get('q', '')
    if query:
        stock_items = stock_items.filter(
            Q(producto__nombre__icontains=query) |
            Q(producto__sku__icontains=query)
        )
    
    # Paginación
    paginator = Paginator(stock_items, 30)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Estadísticas
    total_productos = stock_items.count()
    productos_stock_bajo = stock_items.filter(cantidad__lte=F('stock_minimo')).count()
    
    context = {
        'almacen': almacen,
        'stock_items': page_obj,
        'query': query,
        'stock_bajo': stock_bajo,
        'total_productos': total_productos,
        'productos_stock_bajo': productos_stock_bajo,
        'es_admin': es_admin_bossa(request.user),
    }
    
    return render(request, 'inventario/detalle_almacen.html', context)


@login_required
def editar_almacen(request, almacen_id):
    """Editar un almacén"""
    if not es_admin_bossa(request.user):
        messages.error(request, 'No tienes permisos para realizar esta acción.')
        return redirect('listar_almacenes')
    
    almacen = get_object_or_404(Almacen, id=almacen_id)
    
    if request.method == 'POST':
        almacen.nombre = request.POST.get('nombre', '').strip()
        almacen.codigo = request.POST.get('codigo', '').strip()
        almacen.direccion = request.POST.get('direccion', '').strip() or None
        almacen.telefono = request.POST.get('telefono', '').strip() or None
        almacen.responsable = request.POST.get('responsable', '').strip() or None
        almacen.activo = request.POST.get('activo') == 'on'
        almacen.notas = request.POST.get('notas', '').strip() or None
        
        try:
            almacen.save()
            messages.success(request, f'Almacén "{almacen.nombre}" actualizado exitosamente.')
            return redirect('detalle_almacen', almacen_id=almacen.id)
        except Exception as e:
            logger.error(f'Error al editar almacén: {str(e)}')
            messages.error(request, f'Error al actualizar almacén: {str(e)}')
    
    return render(request, 'inventario/editar_almacen.html', {
        'almacen': almacen,
        'es_admin': True,
    })


@login_required
def crear_transferencia(request):
    """Crear una transferencia entre almacenes"""
    if request.method == 'POST':
        almacen_origen_id = request.POST.get('almacen_origen')
        almacen_destino_id = request.POST.get('almacen_destino')
        notas = request.POST.get('notas', '').strip() or None
        
        if almacen_origen_id == almacen_destino_id:
            messages.error(request, 'El almacén origen y destino no pueden ser el mismo.')
        else:
            try:
                almacen_origen = get_object_or_404(Almacen, id=almacen_origen_id)
                almacen_destino = get_object_or_404(Almacen, id=almacen_destino_id)
                
                with transaction.atomic():
                    transferencia = Transferencia.objects.create(
                        almacen_origen=almacen_origen,
                        almacen_destino=almacen_destino,
                        usuario=request.user,
                        notas=notas
                    )
                    
                    # Procesar items
                    items_data = request.POST.get('items', '[]')
                    import json
                    items = json.loads(items_data)
                    
                    for item in items:
                        producto_id = item.get('producto_id')
                        cantidad = int(item.get('cantidad', 0))
                        
                        if cantidad > 0:
                            producto = get_object_or_404(Producto, id=producto_id)
                            
                            # Verificar stock en origen
                            stock_origen, created = StockAlmacen.objects.get_or_create(
                                producto=producto,
                                almacen=almacen_origen,
                                defaults={'cantidad': 0, 'stock_minimo': producto.stock_minimo}
                            )
                            
                            if stock_origen.cantidad < cantidad:
                                raise ValueError(f'Stock insuficiente de {producto.nombre} en {almacen_origen.nombre}')
                            
                            # Crear item de transferencia
                            ItemTransferencia.objects.create(
                                transferencia=transferencia,
                                producto=producto,
                                cantidad=cantidad
                            )
                    
                    messages.success(request, f'Transferencia creada exitosamente.')
                    return redirect('detalle_transferencia', transferencia_id=transferencia.id)
            except ValueError as e:
                messages.error(request, str(e))
            except Exception as e:
                logger.error(f'Error al crear transferencia: {str(e)}')
                messages.error(request, f'Error al crear transferencia: {str(e)}')
    
    almacenes = Almacen.objects.filter(activo=True).order_by('nombre')
    productos = Producto.objects.filter(activo=True).order_by('nombre')
    
    return render(request, 'inventario/crear_transferencia.html', {
        'almacenes': almacenes,
        'productos': productos,
        'es_admin': es_admin_bossa(request.user),
    })


@login_required
def detalle_transferencia(request, transferencia_id):
    """Detalle de una transferencia"""
    transferencia = get_object_or_404(
        Transferencia.objects.select_related('almacen_origen', 'almacen_destino', 'usuario'),
        id=transferencia_id
    )
    items = transferencia.items.all().select_related('producto')
    
    context = {
        'transferencia': transferencia,
        'items': items,
        'es_admin': es_admin_bossa(request.user),
    }
    
    return render(request, 'inventario/detalle_transferencia.html', context)


@login_required
def completar_transferencia(request, transferencia_id):
    """Completar una transferencia (actualizar stock)"""
    if not es_admin_bossa(request.user):
        messages.error(request, 'No tienes permisos para realizar esta acción.')
        return redirect('listar_almacenes')
    
    transferencia = get_object_or_404(Transferencia, id=transferencia_id)
    
    if transferencia.estado != 'pendiente':
        messages.error(request, 'Solo se pueden completar transferencias pendientes.')
        return redirect('detalle_transferencia', transferencia_id=transferencia.id)
    
    try:
        with transaction.atomic():
            for item in transferencia.items.all():
                # Descontar de origen
                stock_origen, created = StockAlmacen.objects.get_or_create(
                    producto=item.producto,
                    almacen=transferencia.almacen_origen,
                    defaults={'cantidad': 0, 'stock_minimo': item.producto.stock_minimo}
                )
                
                if stock_origen.cantidad < item.cantidad:
                    raise ValueError(f'Stock insuficiente de {item.producto.nombre}')
                
                stock_origen.cantidad -= item.cantidad
                stock_origen.save()
                
                # Agregar a destino
                stock_destino, created = StockAlmacen.objects.get_or_create(
                    producto=item.producto,
                    almacen=transferencia.almacen_destino,
                    defaults={'cantidad': 0, 'stock_minimo': item.producto.stock_minimo}
                )
                stock_destino.cantidad += item.cantidad
                stock_destino.save()
                
                item.cantidad_enviada = item.cantidad
                item.cantidad_recibida = item.cantidad
                item.save()
            
            transferencia.estado = 'completada'
            transferencia.fecha_transferencia = timezone.now()
            transferencia.save()
            
            messages.success(request, 'Transferencia completada exitosamente.')
    except ValueError as e:
        messages.error(request, str(e))
    except Exception as e:
        logger.error(f'Error al completar transferencia: {str(e)}')
        messages.error(request, f'Error al completar transferencia: {str(e)}')
    
    return redirect('detalle_transferencia', transferencia_id=transferencia.id)


"""
Vistas para gestión de compras (órdenes de compra)
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Sum
from django.core.paginator import Paginator
from django.db import transaction
from django.utils import timezone
from .models import Proveedor, OrdenCompra, ItemOrdenCompra, Producto, RecepcionMercancia, Almacen, StockAlmacen
from .utils import es_admin_bossa, logger


@login_required
def listar_ordenes_compra(request):
    """Lista todas las órdenes de compra"""
    ordenes = OrdenCompra.objects.all().select_related('proveedor', 'usuario')
    
    # Filtros
    estado = request.GET.get('estado', '')
    if estado:
        ordenes = ordenes.filter(estado=estado)
    
    proveedor_id = request.GET.get('proveedor', '')
    if proveedor_id:
        ordenes = ordenes.filter(proveedor_id=proveedor_id)
    
    # Búsqueda
    query = request.GET.get('q', '').strip()
    if query:
        ordenes = ordenes.filter(
            Q(numero_orden__icontains=query) |
            Q(proveedor__nombre__icontains=query)
        )
    
    # Ordenamiento
    orden = request.GET.get('orden', '-fecha_creacion')
    ordenes = ordenes.order_by(orden)
    
    # Paginación
    paginator = Paginator(ordenes, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    proveedores = Proveedor.objects.all().order_by('nombre')
    
    context = {
        'ordenes': page_obj,
        'query': query,
        'estado': estado,
        'proveedor_id': proveedor_id,
        'proveedores': proveedores,
        'es_admin': es_admin_bossa(request.user),
    }
    
    return render(request, 'inventario/listar_ordenes_compra.html', context)


@login_required
def crear_orden_compra(request):
    """Crear una nueva orden de compra"""
    if not es_admin_bossa(request.user):
        messages.error(request, 'No tienes permisos para realizar esta acción.')
        return redirect('listar_ordenes_compra')
    
    if request.method == 'POST':
        proveedor_id = request.POST.get('proveedor')
        fecha_orden = request.POST.get('fecha_orden', '')
        fecha_esperada = request.POST.get('fecha_esperada', '')
        notas = request.POST.get('notas', '').strip() or None
        
        try:
            proveedor = get_object_or_404(Proveedor, id=proveedor_id)
            
            from datetime import datetime
            if not fecha_orden:
                fecha_orden = timezone.now().date()
            else:
                fecha_orden = datetime.strptime(fecha_orden, '%Y-%m-%d').date()
            
            if not fecha_esperada:
                fecha_esperada = fecha_orden
            else:
                fecha_esperada = datetime.strptime(fecha_esperada, '%Y-%m-%d').date()
            
            with transaction.atomic():
                orden = OrdenCompra.objects.create(
                    proveedor=proveedor,
                    fecha_orden=fecha_orden,
                    fecha_esperada=fecha_esperada,
                    usuario=request.user,
                    notas=notas
                )
                
                # Procesar items
                items_data = request.POST.get('items', '[]')
                import json
                items = json.loads(items_data)
                
                subtotal = 0
                for item in items:
                    producto_id = item.get('producto_id')
                    cantidad = int(item.get('cantidad', 0))
                    precio_unitario = float(item.get('precio_unitario', 0))
                    
                    if cantidad > 0 and precio_unitario > 0:
                        producto = get_object_or_404(Producto, id=producto_id)
                        item_orden = ItemOrdenCompra.objects.create(
                            orden=orden,
                            producto=producto,
                            cantidad=cantidad,
                            precio_unitario=precio_unitario
                        )
                        subtotal += item_orden.subtotal
                
                orden.subtotal = subtotal
                orden.total = subtotal - orden.descuento
                orden.save()
                
                messages.success(request, f'Orden de compra #{orden.numero_orden} creada exitosamente.')
                return redirect('detalle_orden_compra', orden_id=orden.id)
        except ValueError as e:
            messages.error(request, f'Error en los datos: {str(e)}')
        except Exception as e:
            logger.error(f'Error al crear orden de compra: {str(e)}')
            messages.error(request, f'Error al crear orden de compra: {str(e)}')
    
    proveedores = Proveedor.objects.all().order_by('nombre')
    productos = Producto.objects.filter(activo=True).order_by('nombre')
    
    return render(request, 'inventario/crear_orden_compra.html', {
        'proveedores': proveedores,
        'productos': productos,
        'es_admin': True,
    })


@login_required
def detalle_orden_compra(request, orden_id):
    """Detalle de una orden de compra"""
    orden = get_object_or_404(
        OrdenCompra.objects.select_related('proveedor', 'usuario'),
        id=orden_id
    )
    items = orden.items.all().select_related('producto')
    recepciones = orden.recepciones.all().select_related('almacen', 'usuario')
    
    context = {
        'orden': orden,
        'items': items,
        'recepciones': recepciones,
        'es_admin': es_admin_bossa(request.user),
    }
    
    return render(request, 'inventario/detalle_orden_compra.html', context)


@login_required
def recibir_mercancia(request, orden_id):
    """Recibir mercancía de una orden de compra"""
    if not es_admin_bossa(request.user):
        messages.error(request, 'No tienes permisos para realizar esta acción.')
        return redirect('listar_ordenes_compra')
    
    orden = get_object_or_404(OrdenCompra, id=orden_id)
    
    if request.method == 'POST':
        almacen_id = request.POST.get('almacen')
        notas = request.POST.get('notas', '').strip() or None
        
        try:
            almacen = get_object_or_404(Almacen, id=almacen_id)
            
            with transaction.atomic():
                recepcion = RecepcionMercancia.objects.create(
                    orden_compra=orden,
                    almacen=almacen,
                    usuario=request.user,
                    notas=notas
                )
                
                # Procesar recepción de items
                items_data = request.POST.get('items', '[]')
                import json
                items = json.loads(items_data)
                
                total_recibido = 0
                for item_data in items:
                    item_id = item_data.get('item_id')
                    cantidad_recibida = int(item_data.get('cantidad_recibida', 0))
                    
                    if cantidad_recibida > 0:
                        item = get_object_or_404(ItemOrdenCompra, id=item_id, orden=orden)
                        
                        if cantidad_recibida > item.cantidad:
                            raise ValueError(f'Cantidad recibida no puede ser mayor a la solicitada para {item.producto.nombre}')
                        
                        item.cantidad_recibida += cantidad_recibida
                        item.save()
                        
                        # Actualizar stock
                        stock, created = StockAlmacen.objects.get_or_create(
                            producto=item.producto,
                            almacen=almacen,
                            defaults={'cantidad': 0, 'stock_minimo': item.producto.stock_minimo}
                        )
                        stock.cantidad += cantidad_recibida
                        stock.save()
                        
                        # Actualizar stock general del producto
                        item.producto.stock += cantidad_recibida
                        item.producto.save()
                        
                        total_recibido += cantidad_recibida
                
                # Actualizar estado de la orden
                total_solicitado = sum(item.cantidad for item in orden.items.all())
                total_recibido_orden = sum(item.cantidad_recibida for item in orden.items.all())
                
                if total_recibido_orden == 0:
                    orden.estado = 'pendiente'
                elif total_recibido_orden >= total_solicitado:
                    orden.estado = 'completada'
                else:
                    orden.estado = 'parcial'
                
                orden.save()
                
                messages.success(request, f'Recepción de mercancía registrada exitosamente.')
                return redirect('detalle_orden_compra', orden_id=orden.id)
        except ValueError as e:
            messages.error(request, str(e))
        except Exception as e:
            logger.error(f'Error al recibir mercancía: {str(e)}')
            messages.error(request, f'Error al recibir mercancía: {str(e)}')
    
    almacenes = Almacen.objects.filter(activo=True).order_by('nombre')
    items = orden.items.all().select_related('producto')
    
    return render(request, 'inventario/recibir_mercancia.html', {
        'orden': orden,
        'items': items,
        'almacenes': almacenes,
        'es_admin': True,
    })


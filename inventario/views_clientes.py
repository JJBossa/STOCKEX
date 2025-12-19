"""
Vistas para gestión de clientes
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Sum, Count
from django.core.paginator import Paginator
from django.http import JsonResponse
from .models import Cliente, Venta, CuentaPorCobrar
from .utils import es_admin_bossa, normalizar_texto, logger


@login_required
def listar_clientes(request):
    """Lista todos los clientes con búsqueda y filtros"""
    clientes = Cliente.objects.all()
    
    # Búsqueda
    query = request.GET.get('q', '').strip()
    if query:
        query_normalizado = normalizar_texto(query)
        q_objects = Q(nombre__icontains=query) | Q(rut__icontains=query) | Q(email__icontains=query)
        clientes = clientes.filter(q_objects)
    
    # Filtros
    tipo_cliente = request.GET.get('tipo', '')
    if tipo_cliente:
        clientes = clientes.filter(tipo_cliente=tipo_cliente)
    
    activo = request.GET.get('activo', '')
    if activo == '1':
        clientes = clientes.filter(activo=True)
    elif activo == '0':
        clientes = clientes.filter(activo=False)
    
    # Ordenamiento
    orden = request.GET.get('orden', 'nombre')
    if orden == 'nombre':
        clientes = clientes.order_by('nombre')
    elif orden == 'total_compras':
        clientes = clientes.annotate(total=Sum('ventas__total')).order_by('-total')
    elif orden == 'saldo_pendiente':
        # Ordenar por saldo pendiente (más complejo, se hace después)
        pass
    
    # Paginación
    paginator = Paginator(clientes, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'clientes': page_obj,
        'query': query,
        'tipo_cliente': tipo_cliente,
        'activo': activo,
        'orden': orden,
        'es_admin': es_admin_bossa(request.user),
    }
    
    return render(request, 'inventario/listar_clientes.html', context)


@login_required
def crear_cliente(request):
    """Crear un nuevo cliente"""
    if not es_admin_bossa(request.user):
        messages.error(request, 'No tienes permisos para realizar esta acción.')
        return redirect('listar_clientes')
    
    if request.method == 'POST':
        nombre = request.POST.get('nombre', '').strip()
        rut = request.POST.get('rut', '').strip() or None
        tipo_cliente = request.POST.get('tipo_cliente', 'natural')
        email = request.POST.get('email', '').strip() or None
        telefono = request.POST.get('telefono', '').strip() or None
        direccion = request.POST.get('direccion', '').strip() or None
        contacto = request.POST.get('contacto', '').strip() or None
        limite_credito = request.POST.get('limite_credito', '0') or '0'
        notas = request.POST.get('notas', '').strip() or None
        
        if not nombre:
            messages.error(request, 'El nombre es requerido.')
        else:
            try:
                cliente = Cliente.objects.create(
                    nombre=nombre,
                    rut=rut,
                    tipo_cliente=tipo_cliente,
                    email=email,
                    telefono=telefono,
                    direccion=direccion,
                    contacto=contacto,
                    limite_credito=float(limite_credito) if limite_credito else 0,
                    notas=notas
                )
                messages.success(request, f'Cliente "{cliente.nombre}" creado exitosamente.')
                return redirect('detalle_cliente', cliente_id=cliente.id)
            except Exception as e:
                logger.error(f'Error al crear cliente: {str(e)}')
                messages.error(request, f'Error al crear cliente: {str(e)}')
    
    return render(request, 'inventario/crear_cliente.html', {
        'es_admin': True,
    })


@login_required
def detalle_cliente(request, cliente_id):
    """Detalle de un cliente con historial"""
    cliente = get_object_or_404(Cliente, id=cliente_id)
    
    # Ventas del cliente
    ventas = Venta.objects.filter(cliente=cliente, cancelada=False).order_by('-fecha')[:10]
    
    # Cuentas por cobrar
    cuentas_por_cobrar = CuentaPorCobrar.objects.filter(cliente=cliente).order_by('-fecha_emision')[:10]
    
    # Estadísticas
    total_ventas = cliente.total_compras
    cantidad_ventas = cliente.cantidad_ventas
    saldo_pendiente = cliente.saldo_pendiente
    
    context = {
        'cliente': cliente,
        'ventas': ventas,
        'cuentas_por_cobrar': cuentas_por_cobrar,
        'total_ventas': total_ventas,
        'cantidad_ventas': cantidad_ventas,
        'saldo_pendiente': saldo_pendiente,
        'es_admin': es_admin_bossa(request.user),
    }
    
    return render(request, 'inventario/detalle_cliente.html', context)


@login_required
def editar_cliente(request, cliente_id):
    """Editar un cliente existente"""
    if not es_admin_bossa(request.user):
        messages.error(request, 'No tienes permisos para realizar esta acción.')
        return redirect('listar_clientes')
    
    cliente = get_object_or_404(Cliente, id=cliente_id)
    
    if request.method == 'POST':
        cliente.nombre = request.POST.get('nombre', '').strip()
        cliente.rut = request.POST.get('rut', '').strip() or None
        cliente.tipo_cliente = request.POST.get('tipo_cliente', 'natural')
        cliente.email = request.POST.get('email', '').strip() or None
        cliente.telefono = request.POST.get('telefono', '').strip() or None
        cliente.direccion = request.POST.get('direccion', '').strip() or None
        cliente.contacto = request.POST.get('contacto', '').strip() or None
        limite_credito = request.POST.get('limite_credito', '0') or '0'
        cliente.limite_credito = float(limite_credito) if limite_credito else 0
        cliente.activo = request.POST.get('activo') == 'on'
        cliente.notas = request.POST.get('notas', '').strip() or None
        
        try:
            cliente.save()
            messages.success(request, f'Cliente "{cliente.nombre}" actualizado exitosamente.')
            return redirect('detalle_cliente', cliente_id=cliente.id)
        except Exception as e:
            logger.error(f'Error al editar cliente: {str(e)}')
            messages.error(request, f'Error al actualizar cliente: {str(e)}')
    
    return render(request, 'inventario/editar_cliente.html', {
        'cliente': cliente,
        'es_admin': True,
    })


@login_required
def eliminar_cliente(request, cliente_id):
    """Eliminar un cliente (solo si no tiene ventas)"""
    if not es_admin_bossa(request.user):
        messages.error(request, 'No tienes permisos para realizar esta acción.')
        return redirect('listar_clientes')
    
    cliente = get_object_or_404(Cliente, id=cliente_id)
    
    if request.method == 'POST':
        # Verificar si tiene ventas
        if Venta.objects.filter(cliente=cliente).exists():
            messages.error(request, f'No se puede eliminar el cliente "{cliente.nombre}" porque tiene ventas asociadas.')
            return redirect('detalle_cliente', cliente_id=cliente.id)
        
        nombre = cliente.nombre
        cliente.delete()
        messages.success(request, f'Cliente "{nombre}" eliminado exitosamente.')
        return redirect('listar_clientes')
    
    return render(request, 'inventario/eliminar_cliente.html', {
        'cliente': cliente,
        'es_admin': True,
    })


@login_required
def buscar_cliente_api(request):
    """API para buscar clientes (autocompletado)"""
    query = request.GET.get('q', '').strip()
    
    if len(query) < 2:
        return JsonResponse({'clientes': []})
    
    try:
        clientes = Cliente.objects.filter(
            Q(nombre__icontains=query) | Q(rut__icontains=query)
        ).filter(activo=True)[:10]
        
        resultados = []
        for cliente in clientes:
            resultados.append({
                'id': cliente.id,
                'nombre': cliente.nombre,
                'rut': cliente.rut or '',
                'email': cliente.email or '',
                'telefono': cliente.telefono or '',
            })
        
        return JsonResponse({'clientes': resultados})
    except Exception as e:
        logger.error(f'Error en búsqueda de clientes: {str(e)}')
        return JsonResponse({'clientes': [], 'error': str(e)})


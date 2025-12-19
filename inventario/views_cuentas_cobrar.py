"""
Vistas para gestión de cuentas por cobrar
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Sum
from django.core.paginator import Paginator
from django.utils import timezone
from datetime import timedelta
from django.db.models import Sum
from .models import Cliente, CuentaPorCobrar, PagoCliente, Venta
from .utils import es_admin_bossa, logger


@login_required
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
        'es_admin': es_admin_bossa(request.user),
    }
    
    return render(request, 'inventario/listar_cuentas_cobrar.html', context)


@login_required
def detalle_cuenta_cobrar(request, cuenta_id):
    """Detalle de una cuenta por cobrar con pagos"""
    cuenta = get_object_or_404(CuentaPorCobrar.objects.select_related('cliente', 'venta'), id=cuenta_id)
    pagos = cuenta.pagos.all().order_by('-fecha_pago')
    
    context = {
        'cuenta': cuenta,
        'pagos': pagos,
        'es_admin': es_admin_bossa(request.user),
    }
    
    return render(request, 'inventario/detalle_cuenta_cobrar.html', context)


@login_required
def registrar_pago(request, cuenta_id):
    """Registrar un pago a una cuenta por cobrar"""
    cuenta = get_object_or_404(CuentaPorCobrar, id=cuenta_id)
    
    if request.method == 'POST':
        monto = request.POST.get('monto', '0')
        fecha_pago = request.POST.get('fecha_pago', '')
        metodo_pago = request.POST.get('metodo_pago', 'efectivo')
        referencia = request.POST.get('referencia', '').strip() or None
        notas = request.POST.get('notas', '').strip() or None
        
        try:
            monto = float(monto)
            if monto <= 0:
                messages.error(request, 'El monto debe ser mayor a cero.')
            elif monto > cuenta.saldo_pendiente:
                messages.error(request, f'El monto no puede ser mayor al saldo pendiente (${cuenta.saldo_pendiente:,.0f}).')
            else:
                if not fecha_pago:
                    fecha_pago = timezone.now().date()
                else:
                    from datetime import datetime
                    fecha_pago = datetime.strptime(fecha_pago, '%Y-%m-%d').date()
                
                pago = PagoCliente.objects.create(
                    cuenta_por_cobrar=cuenta,
                    monto=monto,
                    fecha_pago=fecha_pago,
                    metodo_pago=metodo_pago,
                    referencia=referencia,
                    notas=notas,
                    usuario=request.user
                )
                
                # Actualizar cuenta
                cuenta.refresh_from_db()
                
                messages.success(request, f'Pago de ${monto:,.0f} registrado exitosamente.')
                return redirect('detalle_cuenta_cobrar', cuenta_id=cuenta.id)
        except ValueError:
            messages.error(request, 'Monto inválido.')
        except Exception as e:
            logger.error(f'Error al registrar pago: {str(e)}')
            messages.error(request, f'Error al registrar pago: {str(e)}')
    
    return redirect('detalle_cuenta_cobrar', cuenta_id=cuenta.id)


@login_required
def crear_cuenta_cobrar(request, cliente_id=None):
    """Crear una cuenta por cobrar manualmente"""
    if not es_admin_bossa(request.user):
        messages.error(request, 'No tienes permisos para realizar esta acción.')
        return redirect('listar_cuentas_cobrar')
    
    cliente = None
    if cliente_id:
        cliente = get_object_or_404(Cliente, id=cliente_id)
    
    if request.method == 'POST':
        cliente_id_post = request.POST.get('cliente') or cliente_id
        if not cliente_id_post:
            messages.error(request, 'Debes seleccionar un cliente.')
        else:
            cliente = get_object_or_404(Cliente, id=cliente_id_post)
            monto_total = request.POST.get('monto_total', '0')
            fecha_emision = request.POST.get('fecha_emision', '')
            fecha_vencimiento = request.POST.get('fecha_vencimiento', '')
            notas = request.POST.get('notas', '').strip() or None
            
            try:
                monto_total = float(monto_total)
                if monto_total <= 0:
                    messages.error(request, 'El monto debe ser mayor a cero.')
                else:
                    from datetime import datetime
                    if not fecha_emision:
                        fecha_emision = timezone.now().date()
                    else:
                        fecha_emision = datetime.strptime(fecha_emision, '%Y-%m-%d').date()
                    
                    if not fecha_vencimiento:
                        fecha_vencimiento = fecha_emision + timedelta(days=30)
                    else:
                        fecha_vencimiento = datetime.strptime(fecha_vencimiento, '%Y-%m-%d').date()
                    
                    cuenta = CuentaPorCobrar.objects.create(
                        cliente=cliente,
                        monto_total=monto_total,
                        fecha_emision=fecha_emision,
                        fecha_vencimiento=fecha_vencimiento,
                        notas=notas
                )
                
                messages.success(request, f'Cuenta por cobrar creada exitosamente.')
                return redirect('detalle_cuenta_cobrar', cuenta_id=cuenta.id)
            except ValueError:
                messages.error(request, 'Datos inválidos.')
            except Exception as e:
                logger.error(f'Error al crear cuenta por cobrar: {str(e)}')
                messages.error(request, f'Error al crear cuenta por cobrar: {str(e)}')
    
    clientes = Cliente.objects.filter(activo=True).order_by('nombre')
    return render(request, 'inventario/crear_cuenta_cobrar.html', {
        'cliente': cliente,
        'clientes': clientes,
        'es_admin': True,
    })


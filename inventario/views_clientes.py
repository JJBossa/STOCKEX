"""
Vistas para gestión de clientes
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models.deletion import ProtectedError
from django.db.models import Q, Sum, Count
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.views.decorators.cache import never_cache
from .models import Cliente, Venta, CuentaPorCobrar
from .utils import es_administrador, normalizar_texto, logger
from .access import permiso_requerido
from .caja import ErrorCaja, transaccion_caja
from .fiados import validar_limite_credito


@never_cache
@permiso_requerido('inventario.view_cliente', administrativo=True)
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
    orden = request.GET.get("orden", "nombre")
    if orden == "nombre":
        clientes = clientes.order_by("nombre")
    elif orden == "total_compras":
        clientes = clientes.annotate(
            total=Sum("ventas__total", filter=Q(ventas__cancelada=False), default=0)
        ).order_by("-total", "nombre", "pk")
    elif orden == "saldo_pendiente":
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
        'es_admin': es_administrador(request.user),
    }

    return render(request, "inventario/listar_clientes.html", context)


@permiso_requerido("inventario.add_cliente", administrativo=True)
def crear_cliente(request):
    """Crear un nuevo cliente"""
    if request.method == "POST":
        nombre = request.POST.get("nombre", "").strip()
        rut = request.POST.get("rut", "").strip() or None
        tipo_cliente = request.POST.get("tipo_cliente", "natural")
        email = request.POST.get("email", "").strip() or None
        telefono = request.POST.get("telefono", "").strip() or None
        direccion = request.POST.get("direccion", "").strip() or None
        contacto = request.POST.get("contacto", "").strip() or None
        limite_credito = request.POST.get("limite_credito", "0") or "0"
        notas = request.POST.get("notas", "").strip() or None

        if not nombre:
            messages.error(request, "El nombre es requerido.")
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
                    limite_credito=Cliente._meta.get_field("limite_credito").clean(
                        limite_credito, None
                    ),
                    notas=notas,
                )
                messages.success(
                    request, f'Cliente "{cliente.nombre}" creado exitosamente.'
                )
                return redirect("detalle_cliente", cliente_id=cliente.id)
            except ValidationError as error:
                messages.error(request, " ".join(error.messages))
            except IntegrityError:
                messages.error(
                    request, "Revisa que el RUT no esté registrado para otro cliente."
                )

    return render(
        request,
        "inventario/crear_cliente.html",
        {
            "es_admin": True,
        },
    )


@never_cache
@permiso_requerido("inventario.view_cliente", administrativo=True)
def detalle_cliente(request, cliente_id):
    """Detalle de un cliente con historial"""
    cliente = get_object_or_404(Cliente, id=cliente_id)

    # Ventas del cliente
    ventas = Venta.objects.filter(cliente=cliente, cancelada=False).order_by("-fecha")[
        :10
    ]

    # Cuentas por cobrar
    cuentas_por_cobrar = CuentaPorCobrar.objects.filter(cliente=cliente).order_by(
        "-fecha_emision"
    )[:10]

    # Estadísticas
    total_ventas = cliente.total_compras
    cantidad_ventas = cliente.cantidad_ventas
    saldo_pendiente = cliente.saldo_pendiente

    context = {
        "cliente": cliente,
        "ventas": ventas,
        "cuentas_por_cobrar": cuentas_por_cobrar,
        "total_ventas": total_ventas,
        "cantidad_ventas": cantidad_ventas,
        "saldo_pendiente": saldo_pendiente,
        "es_admin": es_administrador(request.user),
    }

    return render(request, "inventario/detalle_cliente.html", context)


@permiso_requerido("inventario.change_cliente", administrativo=True)
def editar_cliente(request, cliente_id):
    if request.method == "POST":
        try:
            with transaccion_caja():
                cliente = get_object_or_404(Cliente, pk=cliente_id)
                limite = Cliente._meta.get_field("limite_credito").clean(
                    request.POST.get("limite_credito") or "0", cliente
                )
                validar_limite_credito(cliente, limite)
                cliente.limite_credito = limite
                cliente.nombre = request.POST.get("nombre", "").strip()
                if not cliente.nombre:
                    raise ValidationError("El nombre es requerido.")
                cliente.tipo_cliente = request.POST.get("tipo_cliente", "natural")
                for campo in (
                    "rut",
                    "email",
                    "telefono",
                    "direccion",
                    "contacto",
                    "notas",
                ):
                    setattr(cliente, campo, request.POST.get(campo, "").strip() or None)
                cliente.activo = request.POST.get("activo") == "on"
                cliente.save()
            messages.success(
                request, f'Cliente "{cliente.nombre}" actualizado exitosamente.'
            )
            return redirect("detalle_cliente", cliente_id=cliente_id)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        except ErrorCaja as error:
            messages.error(request, error.datos["mensaje"])
            if error.estado == 503:
                return HttpResponse(
                    error.datos["mensaje"], status=503, headers={"Retry-After": "1"}
                )
        except IntegrityError:
            messages.error(
                request, "Revisa que el RUT no esté registrado para otro cliente."
            )

    cliente = get_object_or_404(Cliente, pk=cliente_id)
    return render(
        request,
        "inventario/editar_cliente.html",
        {"cliente": cliente, "es_admin": True},
    )


@permiso_requerido("inventario.delete_cliente", administrativo=True)
def eliminar_cliente(request, cliente_id):
    """Eliminar un cliente (solo si no tiene ventas)"""
    cliente = get_object_or_404(Cliente, id=cliente_id)

    if request.method == "POST":
        try:
            with transaccion_caja():
                cliente = get_object_or_404(Cliente, pk=cliente_id)
                cliente.delete()
        except ProtectedError:
            messages.error(
                request, "No se puede eliminar un cliente con historial financiero."
            )
            return redirect("detalle_cliente", cliente_id=cliente_id)
        except ErrorCaja as error:
            return HttpResponse(
                error.datos["mensaje"],
                status=error.estado,
                headers={"Retry-After": "1"},
            )
        messages.success(request, f'Cliente "{cliente.nombre}" eliminado exitosamente.')
        return redirect("listar_clientes")

    return render(
        request,
        "inventario/eliminar_cliente.html",
        {
            "cliente": cliente,
            "es_admin": True,
        },
    )


@never_cache
@permiso_requerido("inventario.view_cliente")
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

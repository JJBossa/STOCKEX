from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST, require_safe
from django.views.decorators.vary import vary_on_headers
from .anulacion_ventas import (
    MAX_MOTIVO,
    PERMISO_ANULAR_VENTA,
    ErrorAnulacion,
    anular_venta,
    impedimento_anulacion,
    tiene_permiso_anulacion,
)
from .historial_ventas import FiltrosHistorialVentas, resumir_ventas
from .models import Producto
from .registro_ventas import PERMISO_REGISTRAR_VENTA
from .utils import es_administrador
from .access import (
    operaciones_financieras_suspendidas,
    permiso_requerido,
    ventas_visibles,
)


@never_cache
@permiso_requerido(PERMISO_REGISTRAR_VENTA)
@require_safe
def punto_venta(request):
    return render(request, "inventario/punto_venta.html")

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
        return JsonResponse({"error": str(e)}, status=500)


@permiso_requerido("inventario.view_venta")
def procesar_venta(request):
    return operaciones_financieras_suspendidas()


@never_cache
@vary_on_headers("X-Historial-Parcial")
@permiso_requerido("inventario.view_venta")
@require_safe
def listar_ventas(request):
    es_admin = es_administrador(request.user)
    formulario = FiltrosHistorialVentas(request.GET, es_admin=es_admin)
    ventas = formulario.aplicar(ventas_visibles(request.user))
    resumen = resumir_ventas(ventas)
    resultados = ventas.order_by("-fecha", "-pk")
    if es_admin:
        resultados = resultados.select_related("usuario")
    paginador = Paginator(resultados, 50)
    # El agregado ya contó todos los registros, con los mismos filtros.
    paginador.count = resumen.cantidad_vigente + resumen.cantidad_anulada
    pagina = paginador.get_page(request.GET.get("page"))
    contexto = {
        "formulario": formulario,
        "ventas": pagina,
        "resumen": resumen,
        "es_admin": es_admin,
        "filtros_url": formulario.parametros(incluir_pagina=False),
    }
    plantilla = (
        "inventario/fragmentos/historial_ventas.html"
        if request.headers.get("X-Historial-Parcial") == "1"
        else "inventario/listar_ventas.html"
    )
    return render(request, plantilla, contexto)


@never_cache
@permiso_requerido("inventario.view_venta")
@require_safe
def detalle_venta(request, venta_id):
    return mostrar_detalle_venta(request, venta_id)


def parametros_historial(request):
    filtros = FiltrosHistorialVentas(
        request.GET, es_admin=es_administrador(request.user)
    )
    return filtros.parametros().urlencode()


def url_historial(parametros, nombre, *args):
    url = reverse(nombre, args=args)
    return f"{url}?{parametros}" if parametros else url


def mostrar_detalle_venta(request, venta_id, *, error=None, motivo="", estado=200):
    venta = get_object_or_404(
        ventas_visibles(request.user).select_related(
            "usuario", "anulacion__usuario", "sesion_caja"
        ),
        id=venta_id,
    )
    autorizada = not venta.cancelada and tiene_permiso_anulacion(request.user)
    impedimento = impedimento_anulacion(venta) if autorizada else None
    parametros = parametros_historial(request)
    contexto = {
        "venta": venta,
        "items": venta.items.all(),
        "regreso": url_historial(parametros, "listar_ventas"),
        "anulacion": getattr(venta, "anulacion", None),
        "puede_anular": autorizada and not impedimento,
        "impedimento": impedimento,
        "url_anular": url_historial(parametros, "cancelar_venta", venta_id),
        "url_detalle": url_historial(parametros, "detalle_venta", venta_id),
        "error_anulacion": error,
        "motivo": motivo,
        "max_motivo": MAX_MOTIVO,
    }
    return render(request, "inventario/detalle_venta.html", contexto, status=estado)


@never_cache
@csrf_protect
@permiso_requerido(PERMISO_ANULAR_VENTA)
@require_POST
def cancelar_venta(request, venta_id):
    solicita_json = request.headers.get("Accept") == "application/json"
    motivo = request.POST.get("motivo", "")
    try:
        resultado = anular_venta(request.user, venta_id, motivo)
    except ErrorAnulacion as error:
        if solicita_json:
            respuesta = JsonResponse(
                {"error": error.codigo, "mensaje": str(error)}, status=error.estado
            )
        else:
            respuesta = mostrar_detalle_venta(
                request,
                venta_id,
                error=str(error),
                motivo=motivo[:MAX_MOTIVO],
                estado=error.estado,
            )
        if error.estado == 503:
            respuesta["Retry-After"] = "1"
        return respuesta
    if solicita_json:
        return JsonResponse(
            {"id": venta_id, "cancelada": True, "repetida": resultado.repetida},
            status=200 if resultado.repetida else 201,
        )
    return redirect(
        url_historial(parametros_historial(request), "detalle_venta", venta_id)
    )


@login_required
def limpiar_historial_ventas(request):
    return JsonResponse({'error': 'El historial de ventas no se puede eliminar.'}, status=403)

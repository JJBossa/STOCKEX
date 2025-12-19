"""
Vistas API para funcionalidades AJAX y autocompletado
"""
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from .models import Producto
from .utils import normalizar_texto, logger

@login_required
def buscar_productos_api(request):
    """API para autocompletado de búsqueda de productos"""
    query = request.GET.get('q', '').strip()
    
    if len(query) < 2:
        return JsonResponse({'productos': []})
    
    try:
        # Buscar productos activos
        productos = Producto.objects.filter(activo=True).select_related('categoria')
        
        # Búsqueda optimizada
        q_objects = Q(nombre__icontains=query) | Q(sku__icontains=query)
        
        productos_filtrados = productos.filter(q_objects)[:10]  # Limitar a 10 resultados
        
        resultados = []
        for producto in productos_filtrados:
            resultados.append({
                'id': producto.id,
                'nombre': producto.nombre,
                'sku': producto.sku or '',
                'precio': float(producto.precio_promo or producto.precio),
                'stock': producto.stock,
                'categoria': producto.categoria.nombre if producto.categoria else '',
            })
        
        return JsonResponse({'productos': resultados})
        
    except Exception as e:
        logger.error(f'Error en búsqueda API: {str(e)}', extra={'user': request.user.username})
        return JsonResponse({'productos': [], 'error': str(e)})


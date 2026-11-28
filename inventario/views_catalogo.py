from hashlib import sha256

from django.http import HttpResponseNotModified, JsonResponse
from django.utils.http import parse_etags
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe
from django.views.decorators.vary import vary_on_cookie

from .access import permiso_requerido
from .models import Producto


@never_cache
@vary_on_cookie
@permiso_requerido("inventario.view_producto")
@require_safe
def catalogo_productos(request):
    filas = (
        Producto.objects.filter(activo=True)
        .order_by("pk")
        .values_list("pk", "sku", "nombre", "categoria__nombre", "precio")
    )
    respuesta = JsonResponse(
        {
            "productos": [
                {
                    "id": pk,
                    "sku": sku,
                    "nombre": nombre,
                    "categoria": categoria,
                    "precio": int(precio),
                }
                for pk, sku, nombre, categoria, precio in filas
            ]
        },
        json_dumps_params={"ensure_ascii": False, "separators": (",", ":")},
    )
    etag = f'"{sha256(respuesta.content).hexdigest()}"'
    etiquetas = parse_etags(request.headers.get("If-None-Match", ""))
    if any(etiqueta.removeprefix("W/") in (etag, "*") for etiqueta in etiquetas):
        respuesta = HttpResponseNotModified()
    respuesta["ETag"] = etag
    return respuesta

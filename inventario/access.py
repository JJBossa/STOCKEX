from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse

from .models import Venta
from .utils import es_administrador


def permiso_requerido(permiso, *, administrativo=False):
    """Redirige al visitante anónimo y deniega al usuario sin permiso."""
    def decorator(view):
        @login_required
        @wraps(view)
        def protegida(request, *args, **kwargs):
            if not request.user.has_perm(permiso):
                raise PermissionDenied
            if administrativo and not es_administrador(request.user):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return protegida

    return decorator


def ventas_visibles(user):
    ventas = Venta.objects.all()
    if not user.has_perm('inventario.view_venta'):
        return ventas.none()
    if es_administrador(user):
        return ventas
    return ventas.filter(usuario=user)


def operaciones_financieras_suspendidas():
    return JsonResponse(
        {'error': 'Operación suspendida hasta habilitar el registro financiero seguro.'},
        status=423,
    )

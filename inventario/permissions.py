from rest_framework.permissions import BasePermission, DjangoModelPermissions
from rest_framework.permissions import SAFE_METHODS

from .utils import es_administrador


class PermisosModelo(DjangoModelPermissions):
    """Exige también el permiso de lectura, que DRF omite por defecto."""

    perms_map = {
        **DjangoModelPermissions.perms_map,
        'GET': ['%(app_label)s.view_%(model_name)s'],
        'HEAD': ['%(app_label)s.view_%(model_name)s'],
        'OPTIONS': ['%(app_label)s.view_%(model_name)s'],
    }


class PermisosCatalogo(PermisosModelo):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and (
            request.method in SAFE_METHODS or es_administrador(request.user)
        )


class PermisoAccionAdministrativa(BasePermission):
    def has_permission(self, request, view):
        return (
            es_administrador(request.user) and request.user.has_perm(view.permiso_accion)
        )

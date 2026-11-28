from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


VENDEDOR = {
    "inventario": {"view_producto", "view_categoria", "view_venta", "registrar_venta"},
}
ADMINISTRADOR = {
    'auth': {'view_user', 'add_user', 'change_user'},
    'inventario': VENDEDOR['inventario'] | {
        'add_producto', 'change_producto', 'delete_producto',
        'add_categoria', 'change_categoria', 'delete_categoria',
        'view_movimientostock', 'add_movimientostock',
        'view_notificacionstock', 'change_notificacionstock',
        'view_cliente', 'add_cliente', 'change_cliente', 'delete_cliente',
        'view_cuentaporcobrar', 'view_pagocliente',
        'view_cotizacion', 'add_cotizacion', 'change_cotizacion', 'delete_cotizacion',
        'view_proveedor', 'add_proveedor', 'change_proveedor', 'delete_proveedor',
        'add_transferencia',
    },
}
ADMINISTRADOR["inventario"].add("anular_venta")
ADMINISTRADOR["inventario"].update(
    {
        "consultar_caja",
        "abrir_caja",
        "registrar_movimiento_caja",
        "cerrar_caja",
        "consultar_cierres_caja",
    }
)


class Command(BaseCommand):
    help = 'Configura los permisos de los grupos Administrador y Vendedor.'

    @transaction.atomic
    def handle(self, *args, **options):
        for nombre, matriz in (('Administrador', ADMINISTRADOR), ('Vendedor', VENDEDOR)):
            grupo, _ = Group.objects.get_or_create(name=nombre)
            permisos = []
            for app, codigos in matriz.items():
                encontrados = list(Permission.objects.filter(
                    content_type__app_label=app, codename__in=codigos,
                ))
                if {p.codename for p in encontrados} != codigos:
                    raise CommandError('Faltan permisos de Django. Ejecuta migrate primero.')
                permisos.extend(encontrados)
            grupo.permissions.set(permisos)
        self.stdout.write(self.style.SUCCESS('Permisos de Administrador y Vendedor configurados.'))

"""Datos sintéticos para ejecutar el navegador contra una base SQLite temporal."""

from django.contrib.auth.models import Group, Permission, User
from django.core.management import call_command

from inventario.models import Categoria, Producto


def preparar_datos():
    call_command("crear_grupos_permisos", verbosity=0)
    for nombre, grupo in (
        ("pos-vendedor-a", "Vendedor"),
        ("pos-vendedor-b", "Vendedor"),
        ("pos-administrador", "Administrador"),
        ("pos-consulta", None),
    ):
        usuario = User.objects.create_user(nombre, password="Prueba-local-STK04B!")
        if grupo:
            usuario.groups.add(Group.objects.get(name=grupo))
        else:
            usuario.user_permissions.add(Permission.objects.get(codename="view_venta"))

    bebidas = Categoria.objects.create(nombre="Bebidas frías")
    Producto.objects.bulk_create(
        [
            Producto(
                nombre="Agua con gas",
                sku="000019",
                categoria=bebidas,
                precio=1,
                stock=0,
            ),
            Producto(
                nombre="Jugo de manzana",
                sku="000020",
                categoria=bebidas,
                precio=1700,
                stock=5,
            ),
            Producto(
                nombre="Caja <b data-producto-prueba>Frágil</b>",
                sku="000021",
                precio=450,
                stock=3,
            ),
            *[
                Producto(
                    nombre=f"Bebida sintética {i}",
                    sku=f"STK04B-{i:04}",
                    categoria=bebidas,
                    precio=1200,
                )
                for i in range(528)
            ],
        ]
    )

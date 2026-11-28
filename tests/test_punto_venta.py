from io import StringIO
from uuid import uuid4

import pytest
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("rol", ["Administrador", "Vendedor"])
def test_pos_disponible_para_roles_de_venta(client, normal_user, producto, rol):
    call_command("crear_grupos_permisos", stdout=StringIO())
    normal_user.groups.add(Group.objects.get(name=rol))
    client.force_login(normal_user)
    respuesta = client.get(reverse("punto_venta"))
    assert respuesta.status_code == 200
    assert "no-store" in respuesta.headers["Cache-Control"]
    assert reverse("registrar_venta_pos") in respuesta.content.decode()
    assert producto.nombre not in respuesta.content.decode()
    assert "pos-mejoras.js" not in respuesta.content.decode()
    assert client.post(reverse("punto_venta")).status_code == 405
    venta = client.post(
        reverse("registrar_venta_pos"),
        {"modalidad": "rapida", "monto": 1, "metodo_pago": "efectivo"},
        content_type="application/json",
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert venta.status_code == 201
    assert venta.json()["usuario_id"] == normal_user.pk


def test_pos_exige_permiso_de_registro_y_conserva_acceso_al_historial(
    client, normal_user
):
    normal_user.user_permissions.add(Permission.objects.get(codename="view_venta"))
    client.force_login(normal_user)
    assert client.get(reverse("punto_venta")).status_code == 403
    respuesta = client.get(reverse("listar_ventas"))
    assert respuesta.status_code == 200
    assert f'href="{reverse("punto_venta")}"' not in respuesta.content.decode()

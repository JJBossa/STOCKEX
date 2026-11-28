from statistics import median
from time import perf_counter

import pytest
from django.contrib.auth.models import Permission
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from inventario.models import Categoria, Producto


@pytest.mark.django_db
def test_permiso_catalogo(client, normal_user):
    url = reverse("catalogo_productos")
    assert client.get(url).status_code == 302
    client.force_login(normal_user)
    assert client.get(url).status_code == 403
    normal_user.user_permissions.add(Permission.objects.get(codename="view_producto"))
    assert client.get(url).status_code == 200
    assert client.post(url).status_code == 405


@pytest.mark.django_db
def test_catalogo_minimo_y_privado(client, admin_user):
    categoria = Categoria.objects.create(nombre="Bebidas frías")
    producto = Producto.objects.create(
        sku="000019",
        nombre="Bebida limón",
        precio=1900,
        precio_compra=500,
        stock=0,
        categoria=categoria,
    )
    Producto.objects.create(sku="oculto", nombre="Inactivo", precio=100, activo=False)
    client.force_login(admin_user)
    response = client.get(reverse("catalogo_productos"))
    assert response.json() == {
        "productos": [
            {
                "id": producto.pk,
                "sku": "000019",
                "nombre": "Bebida limón",
                "categoria": "Bebidas frías",
                "precio": 1900,
            }
        ]
    }
    assert "private" in response["Cache-Control"]
    assert "no-store" in response["Cache-Control"]
    assert "Cookie" in response["Vary"]


@pytest.mark.django_db
def test_version_desde_estado_actual_incluso_con_cambios_masivos(client, admin_user):
    client.force_login(admin_user)
    url = reverse("catalogo_productos")
    categoria = Categoria.objects.create(nombre="Anterior")
    producto = Producto.objects.create(
        sku="001", nombre="Prueba", precio=1, categoria=categoria
    )
    inicial = client.get(url)
    repetido = client.get(url, HTTP_IF_NONE_MATCH=inicial["ETag"])
    assert repetido.status_code == 304
    assert repetido.content == b""
    assert "no-store" in repetido["Cache-Control"]

    Producto.objects.filter(pk=producto.pk).update(precio=995)
    Categoria.objects.filter(pk=categoria.pk).update(nombre="Nuevo")
    actualizado = client.get(url, HTTP_IF_NONE_MATCH=inicial["ETag"])
    assert actualizado.status_code == 200
    assert actualizado.json()["productos"][0]["precio"] == 995
    assert actualizado.json()["productos"][0]["categoria"] == "Nuevo"

    Producto.objects.filter(pk=producto.pk).update(activo=False)
    Producto.objects.create(sku="002", nombre="Alta", precio=10)
    cambio = client.get(url, HTTP_IF_NONE_MATCH=actualizado["ETag"])
    assert cambio.status_code == 200
    assert [item["sku"] for item in cambio.json()["productos"]] == ["002"]
    client.logout()
    assert client.get(url, HTTP_IF_NONE_MATCH=cambio["ETag"]).status_code == 302


@pytest.mark.django_db
@pytest.mark.parametrize("cantidad", [531, 5000])
def test_catalogo_consultas_y_medicion(client, admin_user, cantidad):
    categoria = Categoria.objects.create(nombre="Bebidas frías")
    Producto.objects.bulk_create(
        [
            Producto(
                sku=f"{i:07}",
                nombre=f"Bebida sintética {i:04}",
                precio=1500 + i,
                categoria=categoria,
            )
            for i in range(cantidad)
        ]
    )
    client.force_login(admin_user)
    url = reverse("catalogo_productos")
    tiempos = []
    for _ in range(5):
        inicio = perf_counter()
        with CaptureQueriesContext(connection) as consultas:
            response = client.get(url)
        tiempos.append((perf_counter() - inicio) * 1000)
        catalogo = [q for q in consultas if "inventario_producto" in q["sql"]]
        assert len(catalogo) == 1
        assert len(consultas) <= 5
        assert len(response.json()["productos"]) == cantidad
    print(
        f"STK-03 {connection.vendor} {cantidad}: {len(response.content)} B, "
        f"{len(consultas)} SQL total, p50 {median(tiempos):.2f} ms"
    )
    if cantidad == 531:
        inicio = client.get(reverse("inicio"))
        assert b"data-buscador-productos" in inicio.content
        assert b"buscador-productos.js" in inicio.content
        assert b"Bebida sint\xc3\xa9tica 0530" not in inicio.content

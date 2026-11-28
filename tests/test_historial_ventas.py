from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from io import StringIO
from urllib.parse import parse_qs, urlsplit

import pytest
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from inventario.historial_ventas import SANTIAGO, limites_periodo, resumir_ventas
from inventario.models import ItemVenta, Producto, Venta

pytestmark = pytest.mark.django_db
HOY = date(2026, 9, 7)


@pytest.fixture(autouse=True)
def fecha_actual(monkeypatch):
    monkeypatch.setattr(
        "inventario.historial_ventas.timezone.localdate", lambda **kw: HOY
    )


@pytest.fixture
def vendedores(django_user_model):
    call_command("crear_grupos_permisos", stdout=StringIO())
    grupo = Group.objects.get(name="Vendedor")
    usuarios = tuple(
        django_user_model.objects.create_user(nombre)
        for nombre in ("vendedor-a", "vendedor-b")
    )
    for usuario in usuarios:
        usuario.groups.add(grupo)
    return usuarios


def venta(
    usuario,
    numero,
    *,
    fecha=None,
    total=100,
    metodo_pago="efectivo",
    modalidad="rapida",
    **datos,
):
    resultado = Venta.objects.create(
        usuario=usuario,
        numero_venta=numero,
        total=total,
        metodo_pago=metodo_pago,
        modalidad=modalidad,
        **datos,
    )
    fecha = fecha or datetime(2026, 9, 7, 14, tzinfo=UTC)
    Venta.objects.filter(pk=resultado.pk).update(fecha=fecha)
    return resultado


def historial(client, **filtros):
    return client.get(reverse("listar_ventas"), filtros)


def test_historial_vacio_y_hoy_por_defecto(client, vendedores):
    client.force_login(vendedores[0])
    respuesta = historial(client)
    assert respuesta.status_code == 200
    assert respuesta.context["formulario"]["periodo"].value() == "hoy"
    assert respuesta.context["resumen"].total_vigente == 0
    assert respuesta.context["resumen"].promedio == 0
    assert "No hay ventas que coincidan" in respuesta.content.decode()
    venta(vendedores[0], "OTRO-DIA", fecha=datetime(2026, 9, 7, 2, 59, tzinfo=UTC))
    actual = venta(vendedores[0], "ACTUAL", fecha=datetime(2026, 9, 7, 3, tzinfo=UTC))
    assert list(historial(client).context["ventas"].object_list) == [actual]


def test_totales_exactos_pagos_historicos_y_anuladas(client, vendedores):
    usuario = vendedores[0]
    client.force_login(usuario)
    venta(usuario, "EFECTIVO", total=900, monto_recibido=2000, cambio=1100)
    venta(usuario, "TARJETA", total=200, metodo_pago="tarjeta", modalidad="detallada")
    venta(usuario, "TRANSFERENCIA", total=300, metodo_pago="transferencia")
    venta(usuario, "CREDITO", total=400, metodo_pago="credito", modalidad=None)
    venta(usuario, "MIXTO", total=500, metodo_pago="mixto", modalidad=None)
    venta(usuario, "ANULADA", total=725, cancelada=True)
    venta(usuario, "ANULADA-T", total=1, cancelada=True, metodo_pago="tarjeta")

    respuesta = historial(client)
    resumen = respuesta.context["resumen"]
    assert (resumen.total_vigente, resumen.cantidad_vigente, resumen.promedio) == (
        2300,
        5,
        Decimal("460.00"),
    )
    assert (resumen.monto_anulado, resumen.cantidad_anulada) == (726, 2)
    assert {p.metodo: (p.total, p.cantidad) for p in resumen.pagos} == {
        "efectivo": (900, 1),
        "tarjeta": (200, 1),
        "transferencia": (300, 1),
        "credito": (400, 1),
        "mixto": (500, 1),
    }
    assert "Histórica sin clasificar" in respuesta.content.decode()
    assert "Detallada" in respuesta.content.decode()
    assert len(respuesta.context["ventas"].object_list) == 7

    resumen = historial(client, estado="anulada").context["resumen"]
    assert (resumen.total_vigente, resumen.cantidad_vigente, resumen.monto_anulado) == (
        0,
        0,
        726,
    )


def test_sumatoria_entera_y_promedio_decimal(vendedores):
    usuario = vendedores[0]
    venta(usuario, "MAXIMO", total=999_999_999_999)
    venta(usuario, "MEDIO", total=999_999_999_998)
    venta(usuario, "MINIMO", total=1)
    resumen = resumir_ventas(Venta.objects.all())
    assert resumen.total_vigente == 1_999_999_999_998
    assert resumen.promedio == Decimal("666666666666.00")
    venta(usuario, "FRACCION", total=3)
    assert resumir_ventas(Venta.objects.all()).promedio == Decimal("500000000000.25")


@pytest.mark.parametrize(
    "periodo,primer,ultimo",
    [
        ("hoy", date(2026, 9, 7), date(2026, 9, 8)),
        ("ayer", date(2026, 9, 6), date(2026, 9, 7)),
        ("semana", date(2026, 9, 1), date(2026, 9, 8)),
        ("mes", date(2026, 9, 1), date(2026, 10, 1)),
        ("todas", None, None),
    ],
)
def test_periodos(periodo, primer, ultimo):
    desde, hasta = limites_periodo(periodo)
    assert (desde.astimezone(SANTIAGO).date() if desde else None) == primer
    assert (hasta.astimezone(SANTIAGO).date() if hasta else None) == ultimo


@pytest.mark.parametrize("dia,horas", [(date(2026, 4, 4), 25), (date(2026, 9, 6), 23)])
def test_limites_dst_medianoche_inclusion_de_ultimo_dia(client, vendedores, dia, horas):
    ini, fin = limites_periodo("personalizado", dia, dia)
    assert fin - ini == timedelta(hours=horas)
    usuario = vendedores[0]
    client.force_login(usuario)
    venta(usuario, "ANTES", fecha=ini - timedelta(microseconds=1))
    primera = venta(usuario, "PRIMERA", fecha=ini)
    ultima = venta(usuario, "ULTIMA", fecha=fin - timedelta(microseconds=1))
    venta(usuario, "DESPUES", fecha=fin)
    respuesta = historial(
        client,
        periodo="personalizado",
        fecha_desde=dia.isoformat(),
        fecha_hasta=dia.isoformat(),
    )
    assert list(respuesta.context["ventas"].object_list) == [ultima, primera]


def test_filtros_combinados_y_alcance_de_vendedor(client, vendedores, admin_user):
    usuario, otro = vendedores
    antigua = datetime(2026, 9, 5, 15, tzinfo=UTC)
    coincide = venta(
        otro,
        "REG-T-001",
        fecha=antigua,
        metodo_pago="tarjeta",
        modalidad="detallada",
        total=27,
    )
    venta(
        usuario,
        "REG-T-002",
        fecha=antigua,
        metodo_pago="tarjeta",
        modalidad="detallada",
        total=35,
    )
    venta(
        otro, "REG-E-001", fecha=antigua, metodo_pago="efectivo", modalidad="detallada"
    )
    venta(
        otro,
        "REG-T-003",
        fecha=antigua,
        metodo_pago="tarjeta",
        modalidad="detallada",
        cancelada=True,
    )
    venta(otro, "REG-T-004", metodo_pago="tarjeta", modalidad="detallada")
    venta(otro, "REG-T-005", fecha=antigua, metodo_pago="tarjeta", modalidad=None)

    filtros = {
        "fecha_desde": "2026-09-05",
        "fecha_hasta": "2026-09-06",
        "numero_venta": "reg-t",
        "vendedor": otro.pk,
        "estado": "vigente",
        "metodo_pago": "tarjeta",
        "modalidad": "detallada",
    }
    client.force_login(admin_user)
    respuesta = historial(client, **filtros)
    assert list(respuesta.context["ventas"].object_list) == [coincide]
    assert respuesta.context["resumen"].total_vigente == 27
    assert "Vendedor" in respuesta.content.decode()
    assert (
        list(
            historial(client, periodo="todas", modalidad="historica")
            .context["ventas"]
            .object_list
        )[0].modalidad
        is None
    )

    client.force_login(usuario)
    respuesta = client.get(
        reverse("listar_ventas"), filtros, headers={"X-Historial-Parcial": "1"}
    )
    assert respuesta.context["resumen"].total_vigente == 35
    assert "Vendedor" not in respuesta.content.decode()
    assert "REG-T-001" not in respuesta.content.decode()
    assert "<!DOCTYPE html>" not in respuesta.content.decode()
    assert "no-store" in respuesta.headers["Cache-Control"]
    assert "X-Historial-Parcial" in respuesta.headers["Vary"]
    assert client.get(reverse("detalle_venta", args=[coincide.pk])).status_code == 404


@pytest.mark.parametrize(
    "filtros",
    [
        {"periodo": "desconocido"},
        {"fecha_desde": "no-es-fecha"},
        {"fecha_hasta": "2026-02-30"},
        {"fecha_desde": "2026-09-07", "fecha_hasta": "2026-09-06"},
        {"periodo": "personalizado"},
        {"fecha_hasta": "9999-12-31"},
        {"metodo_pago": "nuevo"},
        {"modalidad": "nueva"},
        {"estado": "nuevo"},
        {"numero_venta": "x" * 51},
        {"vendedor": "x"},
    ],
)
def test_filtros_invalidos_muestran_error_sin_ampliar_alcance(
    client, admin_user, filtros
):
    venta(admin_user, "UNICA")
    client.force_login(admin_user)
    respuesta = historial(client, **filtros)
    assert respuesta.status_code == 200
    assert respuesta.context["formulario"].errors
    assert respuesta.context["resumen"].cantidad_vigente == 0
    assert not respuesta.context["ventas"].object_list


def test_orden_estable_paginacion_y_enlaces_de_regreso(client, vendedores):
    usuario = vendedores[0]
    client.force_login(usuario)
    ventas = Venta.objects.bulk_create(
        [
            Venta(
                usuario=usuario,
                numero_venta=f"LOTE-{i}",
                total=i,
                metodo_pago="tarjeta",
            )
            for i in range(1, 102)
        ]
    )
    Venta.objects.update(fecha=datetime(2026, 9, 7, 14, tzinfo=UTC))
    filtros = {
        "periodo": "todas",
        "metodo_pago": "tarjeta",
        "numero_venta": "LOTE",
        "modalidad": "historica",
    }
    ids = []
    for pagina in (1, 2, 3):
        respuesta = historial(client, **filtros, page=pagina)
        assert respuesta.context["resumen"].total_vigente == sum(range(1, 102))
        ids.extend(v.pk for v in respuesta.context["ventas"])
        assert respuesta.context["ventas"].number == pagina
        assert f"page={pagina}" in respuesta.content.decode()
    assert ids == sorted((v.pk for v in ventas), reverse=True)
    detalle = client.get(
        reverse("detalle_venta", args=[ids[50]]),
        {**filtros, "page": "2", "vendedor": "1"},
    )
    assert "No registrada" in detalle.content.decode()
    assert parse_qs(urlsplit(detalle.context["regreso"]).query) == {
        campo: [valor] for campo, valor in {**filtros, "page": "2"}.items()
    }


def test_detalle_usa_snapshot_y_consultas_sin_escrituras(client, vendedores):
    usuario = vendedores[0]
    rapida = venta(usuario, "RAPIDA", monto_recibido=300, cambio=200)
    detallada = venta(usuario, "DETALLADA", modalidad="detallada")
    producto = Producto.objects.create(nombre="Nuevo nombre", precio=500)
    item = ItemVenta.objects.create(
        venta=detallada,
        producto=producto,
        nombre_producto="Nombre registrado",
        precio_unitario=25,
        cantidad=4,
    )
    ItemVenta.objects.filter(pk=item.pk).update(subtotal=98)
    client.force_login(usuario)
    with CaptureQueriesContext(connection) as consultas:
        assert (
            "sin detalle de productos"
            in client.get(reverse("detalle_venta", args=[rapida.pk])).content.decode()
        )
        respuesta = client.get(reverse("detalle_venta", args=[detallada.pk]))
        tabla = respuesta.content.decode()
        assert "Nombre registrado" in tabla and "Nuevo nombre" not in tabla
        assert "$25" in tabla and "$98" in tabla and "$500" not in tabla
        assert "no-store" in respuesta.headers["Cache-Control"]
        assert historial(client).status_code == 200
    assert not any(
        q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        for q in consultas
    )
    assert not any('JOIN "inventario_producto"' in q["sql"] for q in consultas)


def test_api_lectura_con_mismo_alcance_administrativo_y_no_store(
    client, vendedores, admin_user
):
    usuario, otro = vendedores
    propia = venta(usuario, "PROPIA")
    ajena = venta(otro, "AJENA")
    ruta = reverse("api:venta-list")
    client.force_login(usuario)
    respuesta = client.get(ruta, {"usuario": otro.pk})
    assert [fila["id"] for fila in respuesta.json()["results"]] == [propia.pk]
    assert "no-store" in respuesta.headers["Cache-Control"]
    assert client.get(reverse("api:venta-detail", args=[ajena.pk])).status_code == 404

    client.force_login(admin_user)
    assert [
        fila["id"] for fila in client.get(ruta, {"usuario": otro.pk}).json()["results"]
    ] == [ajena.pk]
    assert client.get(ruta, {"usuario": "1.5"}).status_code == 400


def test_permiso_explicitamente_requerido_para_historial_parcial(client, normal_user):
    ruta = reverse("listar_ventas")
    assert client.get(ruta, headers={"X-Historial-Parcial": "1"}).status_code == 302
    normal_user.user_permissions.add(Permission.objects.get(codename="registrar_venta"))
    client.force_login(normal_user)
    assert client.get(ruta, headers={"X-Historial-Parcial": "1"}).status_code == 403
    assert client.get(reverse("detalle_venta", args=[1])).status_code == 403

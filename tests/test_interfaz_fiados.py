from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from inventario.historial_ventas import SANTIAGO
from inventario.models import Cliente, CuentaPorCobrar, PagoCliente, Venta

from .test_fiados import fiar, pagar

pytestmark = pytest.mark.django_db


def test_panel_dia_chileno_filtros_y_posiciones(client, admin_user, caja_abierta):
    hoy = timezone.localdate(timezone=SANTIAGO)
    titular = Cliente.objects.create(nombre="Cliente con deuda vencida", rut="11")
    _, deuda = fiar(admin_user, titular, 1500)
    CuentaPorCobrar.objects.filter(pk=deuda.pk).update(
        fecha_vencimiento=hoy - timedelta(days=1)
    )
    pagar(admin_user, deuda, 500)
    otro = Cliente.objects.create(nombre="Cliente inactivo", activo=False)
    cuenta_antigua = CuentaPorCobrar.objects.create(
        cliente=otro,
        monto_total=400,
        monto_pagado=50,
        estado="parcial",
        fecha_emision=hoy,
    )
    PagoCliente.objects.create(
        cuenta_por_cobrar=cuenta_antigua,
        metodo_pago="cheque",
        monto=50,
        fecha_pago=hoy - timedelta(days=1),
    )
    Cliente.objects.bulk_create([Cliente(nombre=f"Cliente {i:02}") for i in range(31)])
    client.force_login(admin_user)
    ruta = reverse("fiados_panel")
    with CaptureQueriesContext(connection) as consultas:
        respuesta = client.get(ruta)
    assert respuesta.status_code == 200
    assert respuesta.context["totales"] == {
        "saldo": 1350,
        "vencido": 1000,
        "clientes": 2,
        "pendientes": 2,
        "inconsistentes": 0,
        "abonos_hoy": 500,
    }
    assert len(respuesta.context["pagina"]) == 30
    with CaptureQueriesContext(connection) as filtradas:
        resultado = client.get(ruta, {"activo": "0", "deuda": "1", "orden": "saldo"})
    assert len(filtradas) <= len(consultas)
    assert list(resultado.context["pagina"]) == [otro]
    assert list(client.get(ruta, {"vencidas": "1", "q": "11"}).context["pagina"]) == [
        titular
    ]
    assert len(client.get(ruta, {"page": "2"}).context["pagina"]) == 3
    detalle = client.get(
        reverse("fiados_cliente_html", args=[otro.pk]),
        {"lista": "deuda=1&activo=0&page=2"},
    )
    assert detalle.context["volver"] == ruta + "?deuda=1&activo=0&page=2"
    assert (
        "Cheque" in detalle.content.decode()
        and "Sin sesión registrada" in detalle.content.decode()
    )

    mal = CuentaPorCobrar.objects.create(
        cliente=otro,
        monto_total=400,
        monto_pagado=999,
        estado="parcial",
        fecha_emision=hoy,
    )
    mala = client.get(reverse("fiados_cuenta_html", args=[mal.pk]))
    assert "Requiere conciliación" in mala.content.decode()
    assert mala.context["cuenta"]["saldo"] is None
    respuesta = client.get(ruta)
    assert respuesta.context["totales"]["saldo"] is None
    assert respuesta.context["totales"]["vencido"] is None
    assert "por conciliar" in respuesta.content.decode()


def test_lecturas_paginadas_estado_y_escapado(
    client, admin_user, caja_abierta, monkeypatch
):
    hoy = timezone.localdate(timezone=SANTIAGO)
    titular = Cliente.objects.create(nombre="Cliente <em>fiado</em>")
    _, deuda = fiar(admin_user, titular, 300)
    for _ in range(3):
        pagar(admin_user, deuda, 100)
    # Una anotación libre histórica se presenta como texto en ambas vistas.
    PagoCliente.objects.filter(cuenta_por_cobrar=deuda).update(
        referencia="<img src=x>", notas="<script>x</script>"
    )
    CuentaPorCobrar.objects.create(
        cliente=titular, monto_total=100, fecha_emision=hoy, estado="cancelado"
    )
    client.force_login(admin_user)
    monkeypatch.setattr("inventario.views_panel_fiados.LIMITE_PAGINA", 2)
    ruta = reverse("fiados_cliente_html", args=[titular.pk])
    pagadas = client.get(ruta, {"estado": "pagadas"})
    assert [cuenta["id"] for cuenta in pagadas.context["cuentas"]] == [deuda.pk]
    assert "Cliente &lt;em&gt;fiado&lt;/em&gt;" in pagadas.content.decode()
    assert "&lt;script&gt;x&lt;/script&gt;" in pagadas.content.decode()
    assert "&lt;img src=x&gt;" in pagadas.content.decode()
    assert len(pagadas.context["pagos"]) == 2
    assert len(client.get(ruta + pagadas.context["mas_pagos"]).context["pagos"]) == 1
    assert len(client.get(ruta, {"estado": "canceladas"}).context["cuentas"]) == 1
    assert not client.get(ruta).context["cuentas"]
    assert client.get(ruta, {"abonos_antes_de": "inf"}).status_code == 404
    cuenta_url = reverse("fiados_cuenta_html", args=[deuda.pk])
    fragmento = client.get(cuenta_url, {"fragmento": "abono"})
    assert "no-store" in fragmento["Cache-Control"]
    assert "fiados-datos-cuenta" in fragmento.content.decode()
    assert "fiados-pagos" in fragmento.content.decode()
    assert fragmento.context["cuenta_pagable"] is False


def test_permiso_credito_independiente_del_saldo_y_alcance_de_venta(
    client, admin_user, normal_user, caja_abierta
):
    titular = Cliente.objects.create(nombre="Titular")
    venta, deuda = fiar(admin_user, titular)
    normal_user.user_permissions.add(
        *Permission.objects.filter(
            content_type__app_label="inventario",
            codename__in=["registrar_venta", "registrar_venta_fiada", "view_venta"],
        )
    )
    client.force_login(normal_user)
    assert b"pos-credito" in client.get(reverse("punto_venta")).content
    assert b"data-saldo=" not in client.get(reverse("punto_venta")).content
    assert b"pos-alta-cliente" not in client.get(reverse("punto_venta")).content
    assert (
        client.get(reverse("fiados_buscar_clientes"), {"q": "Ti"}).json()["clientes"][
            0
        ]["id"]
        == titular.pk
    )
    assert client.get(reverse("fiados_panel")).status_code == 403
    assert client.get(reverse("fiados_saldo", args=[titular.pk])).status_code == 403
    normal_user.user_permissions.add(
        Permission.objects.get(codename="consultar_cuentas_por_cobrar")
    )
    urls = [
        reverse(nombre, args=[deuda.pk])
        for nombre in ("fiados_cuenta_html", "detalle_cuenta_cobrar")
    ]
    for url in urls:
        respuesta = client.get(url)
        assert (
            respuesta.status_code == 200
            and venta.numero_venta.encode() not in respuesta.content
        )
        assert b"abono-formulario" not in respuesta.content
    assert (
        client.get(reverse("fiados_detalle", args=[deuda.pk])).json()["venta_id"]
        is None
    )
    assert (
        client.get(reverse("fiados_pendientes", args=[titular.pk])).json()["cuentas"][
            0
        ]["venta_id"]
        is None
    )
    Venta.objects.filter(pk=venta.pk).update(usuario=normal_user)
    assert venta.numero_venta in client.get(urls[0]).content.decode()
    assert (
        client.get(reverse("fiados_detalle", args=[deuda.pk])).json()["venta_id"]
        == venta.pk
    )


def test_alta_cliente_misma_clave_y_permisos(admin_user, normal_user):
    navegador = Client(enforce_csrf_checks=True)
    navegador.force_login(admin_user)
    ruta = reverse("crear_cliente")
    formulario = navegador.get(ruta)
    token = formulario.cookies["csrftoken"].value
    clave = str(uuid4())
    headers = {
        "Idempotency-Key": clave,
        "X-CSRFToken": token,
        "X-Stockex-Account": str(admin_user.pk),
    }

    def crear(datos, cabeceras=headers):
        return navegador.post(
            ruta, datos, content_type="application/json", headers=cabeceras
        )

    datos = {"nombre": "Sin RUT", "limite_credito": ""}
    assert crear(datos, {"Idempotency-Key": clave}).status_code == 403
    primero = crear(datos)
    assert primero.status_code == 201 and primero.json()["rut"] is None
    assert "no-store" in primero["Cache-Control"]
    duplicado = crear(datos)
    assert duplicado.status_code == 200
    assert duplicado.json() == {**primero.json(), "repetida": True}
    assert crear({"nombre": "Otro"}).json()["error"] == "clave_en_conflicto"
    assert Cliente.objects.get().limite_credito == 0
    assert crear(datos, {**headers, "Idempotency-Key": str(uuid4())}).status_code == 201
    assert Cliente.objects.filter(nombre="Sin RUT").count() == 2
    formulario_native = {
        "nombre": "Desde HTML",
        "clave_alta": formulario.context["clave_alta"],
    }
    for _ in range(2):
        assert (
            navegador.post(
                ruta, formulario_native, headers={"X-CSRFToken": token}
            ).status_code
            == 302
        )
    assert Cliente.objects.filter(nombre="Desde HTML").count() == 1
    navegador.force_login(normal_user)
    assert crear(datos).status_code == 403

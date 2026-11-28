from datetime import timedelta
from io import StringIO
from uuid import uuid4

import pytest
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from inventario import caja
from inventario.historial_ventas import SANTIAGO
from inventario.models import (
    ItemVenta,
    MovimientoCaja,
    MovimientoStock,
    RegistroVenta,
    Venta,
)

from .test_caja import abrir, datos_cierre, movimiento, post

pytestmark = pytest.mark.django_db


def test_pos_cerrado_solo_expone_estado_y_revierte_escrituras(
    client, admin_user, normal_user, producto
):
    call_command("crear_grupos_permisos", stdout=StringIO())
    normal_user.groups.add(Group.objects.get(name="Vendedor"))
    client.force_login(normal_user)
    estado = reverse("pos_estado_caja")
    registro = reverse("registrar_venta_pos")
    pos = reverse("punto_venta")
    solicitud = {
        "modalidad": "detallada",
        "metodo_pago": "efectivo",
        "items": [{"producto_id": producto.pk, "precio_visto": 10000, "cantidad": 1}],
    }
    clave = str(uuid4())

    def enviar(**headers):
        return client.post(
            registro,
            solicitud,
            content_type="application/json",
            headers={"Idempotency-Key": clave, **headers},
        )

    assert client.get(estado).json() == {"abierta": False}
    assert "no-store" in client.get(estado)["Cache-Control"]
    assert client.get(pos).context["caja_abierta"] is False
    assert reverse("caja_gestion") not in client.get(pos).content.decode()
    assert client.get(reverse("caja_activa")).status_code == 403
    assert client.get(reverse("caja_gestion")).status_code == 403
    assert client.get(reverse("caja_historial")).status_code == 403
    rechazo = enviar()
    assert (rechazo.status_code, rechazo.json()["error"]) == (409, "caja_no_abierta")
    assert not any(
        modelo.objects.exists()
        for modelo in (Venta, ItemVenta, RegistroVenta, MovimientoStock)
    )
    sesion = abrir(admin_user)
    assert client.get(estado).json() == {"abierta": True}
    assert enviar(**{"X-Stockex-Account": str(admin_user.pk)}).status_code == 403
    assert not RegistroVenta.objects.exists()
    respuesta = enviar()
    assert respuesta.status_code == 201
    venta = Venta.objects.get(pk=respuesta.json()["id"])
    assert venta.sesion_caja_id == sesion.pk
    sesion.refresh_from_db()
    caja.cerrar_caja(admin_user, sesion.pk, str(uuid4()), datos_cierre(sesion, 10000))
    assert client.get(estado).json() == {"abierta": False}
    repetida = enviar()
    assert repetida.status_code == 200 and repetida.json()["id"] == venta.pk
    nueva = abrir(admin_user)
    assert enviar().status_code == 200
    assert not nueva.ventas.exists()
    assert (
        Venta.objects.count()
        == ItemVenta.objects.count()
        == RegistroVenta.objects.count()
        == 1
    )
    assert not MovimientoStock.objects.exists()


def test_vistas_de_caja_permisos_cuenta_y_escritura(admin_user, normal_user):
    cliente = Client(enforce_csrf_checks=True)
    gestion = reverse("caja_gestion")
    assert cliente.get(gestion).status_code == 302
    assert cliente.get(reverse("pos_estado_caja")).status_code == 302
    cliente.force_login(normal_user)
    assert cliente.get(gestion).status_code == 403
    assert cliente.get(reverse("pos_estado_caja")).status_code == 403
    normal_user.user_permissions.add(Permission.objects.get(codename="abrir_caja"))
    response = cliente.get(gestion)
    assert response.status_code == 200
    assert "no-store" in response.headers["Cache-Control"]
    assert "Caja cerrada" in response.content.decode()
    sesion = abrir(admin_user, inicial=94201)
    assert "94.201" not in cliente.get(gestion).content.decode()
    assert (
        cliente.get(reverse("caja_listado_movimientos", args=[sesion.pk])).status_code
        == 403
    )
    cliente.force_login(admin_user)
    assert cliente.post(gestion).status_code == 403
    token = cliente.get(gestion).cookies["csrftoken"].value
    assert cliente.post(gestion, headers={"X-CSRFToken": token}).status_code == 405
    respuesta = post(
        cliente,
        "caja_abrir",
        {"efectivo_inicial": 0},
        **{"X-CSRFToken": token, "X-Stockex-Account": str(normal_user.pk)},
    )
    assert respuesta.status_code == 403
    normal_user.user_permissions.add(Permission.objects.get(codename="cerrar_caja"))
    cliente.force_login(normal_user)
    respuesta = post(
        cliente,
        "caja_cerrar",
        datos_cierre(sesion, 94201),
        sesion.pk,
        **{"X-CSRFToken": token, "X-Stockex-Account": str(normal_user.pk)},
    )
    assert respuesta.status_code == 201
    assert "Caja cuadrada" in respuesta.json()["instantanea_html"]
    assert (
        cliente.get(reverse("caja_historial_detalle", args=[sesion.pk])).status_code
        == 403
    )
    cliente.logout()
    assert cliente.get(gestion + "?fragmento=resumen").status_code == 302


def test_lecturas_paginadas_con_snapshot_y_escapado(
    client, admin_user, normal_user, monkeypatch
):
    client.force_login(admin_user)
    monkeypatch.setattr(caja, "LIMITE_MOVIMIENTOS", 2)
    monkeypatch.setattr(caja, "LIMITE_CIERRES", 2)
    sesiones = []
    movimientos = []
    for i in range(3):
        sesion = abrir(admin_user, inicial=1000)
        sesiones.append(sesion)
        recibos = [
            movimiento(admin_user, sesion, importe=125, motivo=f"<b>Motivo {j}</b>")
            for j in range(3)
        ]
        movimientos.append(recibos)
        activa = client.get(reverse("caja_gestion") + "?fragmento=resumen")
        assert "1.375" in activa.content.decode()
        assert "no-store" in activa.headers["Cache-Control"]
        sesion.refresh_from_db()
        caja.cerrar_caja(
            admin_user,
            sesion.pk,
            str(uuid4()),
            {
                **datos_cierre(sesion, 1375 + i),
                "observaciones": "<em>Conteo verificado</em>",
            },
        )
    monkeypatch.setattr(
        caja, "resumir_caja", lambda *args: pytest.fail("Recalculó un cierre")
    )
    hoy = timezone.localdate(timezone=SANTIAGO)
    ruta = reverse("caja_historial")
    historial = client.get(ruta)
    assert [sesion.pk for sesion in historial.context["cierres"]] == [
        sesiones[2].pk,
        sesiones[1].pk,
    ]
    assert client.get(ruta + historial.context["siguiente"]).context["cierres"] == [
        sesiones[0]
    ]
    assert client.get(
        ruta, {"desde": hoy.isoformat(), "clasificacion": "cuadrada"}
    ).context["cierres"] == [sesiones[0]]
    assert not client.get(
        ruta, {"hasta": (hoy - timedelta(days=1)).isoformat()}
    ).context["cierres"]
    assert client.get(ruta, {"desde": "2026-02-29"}).status_code == 400
    assert client.get(ruta, {"antes_de": "x"}).status_code == 400

    detalle = client.get(reverse("caja_historial_detalle", args=[sesiones[0].pk]))
    sesiones[0].refresh_from_db()
    assert detalle.context["resumen"] == sesiones[0].resumen_cierre
    assert "&lt;em&gt;Conteo verificado&lt;/em&gt;" in detalle.content.decode()
    assert "no-store" in detalle.headers["Cache-Control"]
    ruta_mov = reverse("caja_listado_movimientos", args=[sesiones[0].pk])
    pagina = client.get(ruta_mov)
    assert isinstance(pagina.context["movimientos"][0], MovimientoCaja)
    assert [m.pk for m in pagina.context["movimientos"]] == [
        movimientos[0][2].pk,
        movimientos[0][1].pk,
    ]
    assert "&lt;b&gt;Motivo 2&lt;/b&gt;" in pagina.content.decode()
    assert "no-store" in pagina.headers["Cache-Control"]
    assert client.get(ruta_mov + pagina.context["siguiente"]).context[
        "movimientos"
    ] == [movimientos[0][0]]
    assert client.get(ruta_mov, {"antes_de": "0"}).status_code == 400
    cierre_json = client.get(reverse("caja_cierres")).json()["cierres"][0]
    assert cierre_json["efectivo_esperado"] == 1375 and cierre_json["diferencia"] == 2

    normal_user.user_permissions.add(Permission.objects.get(codename="consultar_caja"))
    client.force_login(normal_user)
    assert client.get(ruta_mov).status_code == 403
    activa = abrir(admin_user)
    assert (
        client.get(reverse("caja_listado_movimientos", args=[activa.pk])).status_code
        == 200
    )
    normal_user.user_permissions.set(
        [Permission.objects.get(codename="consultar_cierres_caja")]
    )
    assert client.get(ruta_mov).status_code == 200
    assert (
        client.get(reverse("caja_listado_movimientos", args=[activa.pk])).status_code
        == 403
    )

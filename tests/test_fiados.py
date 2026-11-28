from datetime import date, timedelta
from io import StringIO
from uuid import uuid4

import pytest
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from inventario import anulacion_ventas, caja, fiados, registro_ventas
from inventario.historial_ventas import SANTIAGO
from inventario.models import (
    AnulacionVenta,
    Cliente,
    CuentaPorCobrar,
    Devolucion,
    ItemVenta,
    MovimientoStock,
    PagoCliente,
    RegistroVenta,
    Venta,
)

from .test_caja import abrir, datos_cierre, post

pytestmark = pytest.mark.django_db


@pytest.fixture
def deudor():
    return Cliente.objects.create(nombre="Cliente sin RUT")


def solicitud(cliente, monto=1000, **campos):
    return {
        "modalidad": "rapida",
        "metodo_pago": "credito",
        "monto": monto,
        "cliente_id": cliente.pk,
        **campos,
    }


def fiar(usuario, cliente, monto=1000):
    resultado = registro_ventas.registrar_venta(
        usuario, str(uuid4()), solicitud(cliente, monto)
    )
    return resultado.venta, CuentaPorCobrar.objects.get(pk=resultado.cuenta_id)


def pagar(usuario, cuenta, importe, metodo="efectivo", *, clave=None):
    return fiados.registrar_abono(
        usuario,
        cuenta.pk,
        clave or str(uuid4()),
        {"importe": importe, "metodo_pago": metodo},
    )


def cerrar(usuario, sesion, contado):
    sesion.refresh_from_db()
    return caja.cerrar_caja(
        usuario, sesion.pk, str(uuid4()), datos_cierre(sesion, contado)
    ).registro


def test_venta_fiada_rapida_abono_total_e_idempotencia(
    client, admin_user, deudor, caja_abierta
):
    client.force_login(admin_user)
    clave_venta = str(uuid4())
    venta_datos = solicitud(
        deudor, fecha_vencimiento="2030-12-31", notas="  Fiado semanal  "
    )
    alta = post(client, "registrar_venta_pos", venta_datos, clave=clave_venta)
    assert alta.status_code == 201
    original = alta.json()
    cuenta = CuentaPorCobrar.objects.get(pk=original["cuenta_id"])
    venta = cuenta.venta
    assert original["cliente_id"] == deudor.pk and original["es_credito"] is True
    assert original["sesion_caja_id"] == caja_abierta.pk
    assert original["monto_recibido"] == original["cambio"] == 0
    assert venta.total == cuenta.monto_total == 1000
    assert venta.cliente_id == cuenta.cliente_id and deudor.rut is None
    assert (
        cuenta.fecha_vencimiento == date(2030, 12, 31)
        and cuenta.notas == "Fiado semanal"
    )
    assert cuenta.fecha_emision == timezone.localdate(venta.fecha, SANTIAGO)
    assert (
        cuenta.numero_documento.startswith("CC-") and len(cuenta.numero_documento) == 35
    )
    assert cuenta.fiado_seguro and cuenta.estado == "pendiente"
    assert deudor.saldo_pendiente == 1000
    assert (
        post(client, "registrar_venta_pos", venta_datos, clave=clave_venta).status_code
        == 200
    )

    clave_abono = str(uuid4())
    datos = {
        "importe": 350,
        "metodo_pago": "efectivo",
        "referencia": "  E-10 ",
        "observaciones": "Recibido",
    }
    primer_abono = post(client, "fiados_abonar", datos, cuenta.pk, clave=clave_abono)
    assert primer_abono.status_code == 201
    respuesta = primer_abono.json()
    assert (
        respuesta["referencia"] == "E-10" and respuesta["observaciones"] == "Recibido"
    )
    assert (
        respuesta["usuario_id"] == admin_user.pk
        and respuesta["sesion_caja_id"] == caja_abierta.pk
    )
    cuenta.refresh_from_db()
    assert (cuenta.monto_pagado, cuenta.saldo_pendiente, cuenta.estado) == (
        350,
        650,
        "parcial",
    )
    assert not pagar(admin_user, cuenta, 650, "tarjeta").repetida
    cuenta.refresh_from_db()
    assert (cuenta.monto_pagado, cuenta.saldo_pendiente, cuenta.estado) == (
        1000,
        0,
        "pagado",
    )
    assert deudor.saldo_pendiente == 0

    sesion = cerrar(admin_user, caja_abierta, 350)
    for abrir_otra in (False, True):
        if abrir_otra:
            abrir(admin_user)
        abono = post(client, "fiados_abonar", datos, cuenta.pk, clave=clave_abono)
        assert abono.status_code == 200 and abono.json() == {
            **respuesta,
            "repetida": True,
        }
        assert post(
            client, "registrar_venta_pos", venta_datos, clave=clave_venta
        ).json() == {**original, "repetida": True}
    assert (
        post(
            client,
            "fiados_abonar",
            {**datos, "importe": 351},
            cuenta.pk,
            clave=clave_abono,
        ).json()["error"]
        == "clave_en_conflicto"
    )
    otra = CuentaPorCobrar.objects.create(
        cliente=deudor, monto_total=400, fecha_emision=cuenta.fecha_emision
    )
    assert (
        post(client, "fiados_abonar", datos, otra.pk, clave=clave_abono).json()["error"]
        == "clave_en_conflicto"
    )
    assert (
        post(
            client,
            "registrar_venta_pos",
            {**venta_datos, "monto": 1001},
            clave=clave_venta,
        ).json()["error"]
        == "clave_en_conflicto"
    )
    assert PagoCliente.objects.filter(sesion_caja=sesion).count() == 2
    assert not PagoCliente.objects.exclude(sesion_caja=sesion).exists()
    assert RegistroVenta.objects.count() == Venta.objects.count() == 1
    assert not ItemVenta.objects.exists() and not MovimientoStock.objects.exists()
    assert CuentaPorCobrar.objects.filter(venta=venta).count() == 1


def test_fiado_detallado_precios_cliente_y_limite(
    client, admin_user, producto, caja_abierta
):
    deudor = Cliente.objects.create(nombre="Con límite", limite_credito=20000)
    client.force_login(admin_user)
    cuerpo = {
        "modalidad": "detallada",
        "metodo_pago": "credito",
        "cliente_id": deudor.pk,
        "items": [{"producto_id": producto.pk, "precio_visto": 9000, "cantidad": 2}],
    }
    assert (
        post(client, "registrar_venta_pos", cuerpo).json()["error"] == "precio_cambiado"
    )
    cuerpo["items"][0]["precio_visto"] = 10000
    assert (
        post(client, "registrar_venta_pos", {**cuerpo, "total": 1}).status_code == 400
    )
    venta = post(client, "registrar_venta_pos", cuerpo)
    assert venta.status_code == 201 and venta.json()["items"][0]["subtotal"] == 20000
    assert venta.json()["total"] == 20000
    assert (
        post(client, "registrar_venta_pos", solicitud(deudor, 1)).json()["error"]
        == "limite_credito_excedido"
    )
    assert (
        post(client, "registrar_venta_pos", {**cuerpo, "cliente_id": 123456}).json()[
            "error"
        ]
        == "cliente_no_elegible"
    )
    deudor.activo = False
    deudor.save(update_fields=["activo"])
    assert (
        post(client, "registrar_venta_pos", cuerpo).json()["error"]
        == "cliente_no_elegible"
    )
    cuenta = CuentaPorCobrar.objects.get()
    assert cuenta.fecha_vencimiento is None and not cuenta.esta_vencida
    assert not pagar(admin_user, cuenta, 4000, "transferencia").repetida
    assert venta.json()["items"][0]["precio_unitario"] == 10000
    assert (
        Venta.objects.count()
        == ItemVenta.objects.count()
        == RegistroVenta.objects.count()
        == 1
    )
    producto.refresh_from_db()
    assert producto.stock == 50 and not MovimientoStock.objects.exists()


def test_rechazos_y_rollback_no_dejan_escrituras(
    client, admin_user, deudor, monkeypatch
):
    client.force_login(admin_user)
    datos = solicitud(deudor)
    v = post(client, "registrar_venta_pos", datos)
    assert v.status_code == 409 and v.json()["error"] == "caja_no_abierta"
    assert not Venta.objects.exists() and not RegistroVenta.objects.exists()
    sesion = abrir(admin_user)
    for invalido in (
        {**datos, "monto_recibido": True},
        {**datos, "monto_recibido": 1},
        {**datos, "fecha_vencimiento": "2026-02-29"},
        {**datos, "vendedor_id": 10},
    ):
        assert post(client, "registrar_venta_pos", invalido).status_code == 400

    def fallar(_):
        raise RuntimeError("Fallo después de escribir")

    with monkeypatch.context() as parche:
        parche.setattr(registro_ventas, "invalidar_resumen", fallar)
        with pytest.raises(RuntimeError):
            post(client, "registrar_venta_pos", datos)
    assert not Venta.objects.exists() and not CuentaPorCobrar.objects.exists()
    assert not RegistroVenta.objects.exists()
    _, cuenta = fiar(admin_user, deudor)
    sesion.refresh_from_db()
    version = sesion.version_resumen
    with monkeypatch.context() as parche:
        parche.setattr(fiados, "invalidar_resumen", fallar)
        with pytest.raises(RuntimeError):
            pagar(admin_user, cuenta, 500)
    cuenta.refresh_from_db()
    sesion.refresh_from_db()
    assert (cuenta.monto_pagado, cuenta.estado, sesion.version_resumen) == (
        0,
        "pendiente",
        version,
    )
    assert not PagoCliente.objects.exists()

    for monto in (0, -3, True, 1.0, 0.5, "20", caja.MAX_IMPORTE + 1):
        assert (
            post(
                client,
                "fiados_abonar",
                {"importe": monto, "metodo_pago": "efectivo"},
                cuenta.pk,
            ).status_code
            == 400
        )
    assert (
        post(
            client, "fiados_abonar", {"importe": 10, "metodo_pago": "cheque"}, cuenta.pk
        ).status_code
        == 400
    )
    assert (
        post(
            client,
            "fiados_abonar",
            {"importe": 10, "metodo_pago": "efectivo", "fecha_pago": "2026-01-01"},
            cuenta.pk,
        ).status_code
        == 400
    )
    assert (
        post(
            client,
            "fiados_abonar",
            {"importe": 1001, "metodo_pago": "efectivo"},
            cuenta.pk,
        ).json()["error"]
        == "abono_supera_saldo"
    )
    cerrar(admin_user, sesion, 0)
    assert (
        post(
            client,
            "fiados_abonar",
            {"importe": 500, "metodo_pago": "efectivo"},
            cuenta.pk,
        ).json()["error"]
        == "caja_no_abierta"
    )
    assert not PagoCliente.objects.exists()


def test_anulacion_fiado_y_caja_con_abonos(client, admin_user, deudor, caja_abierta):
    client.force_login(admin_user)
    ed, deuda_anulada = fiar(admin_user, deudor, 250)
    resultado = anulacion_ventas.anular_venta(admin_user, ed.pk, "Duplicada")
    assert anulacion_ventas.anular_venta(admin_user, ed.pk, "Duplicada").repetida
    assert resultado.anulacion.venta_id == ed.pk and AnulacionVenta.objects.count() == 1
    deuda_anulada.refresh_from_db()
    assert (
        deuda_anulada.monto_total,
        deuda_anulada.saldo_pendiente,
        deuda_anulada.estado,
    ) == (250, 0, "cancelado")
    with pytest.raises(caja.ErrorCaja, match="pagada o cancelada"):
        pagar(admin_user, deuda_anulada, 1)

    venta, cuenta = fiar(admin_user, deudor, 900)
    primera = cerrar(admin_user, caja_abierta, 0)
    assert primera.resumen_cierre["fiados"] == {"cantidad": 1, "importe": 900}
    assert primera.resumen_cierre["abonos"]["importe"] == 0
    assert primera.resumen_cierre["efectivo_esperado"] == 0
    siguiente = abrir(admin_user, inicial=100)
    registro_ventas.registrar_venta(
        admin_user,
        str(uuid4()),
        {"modalidad": "rapida", "metodo_pago": "efectivo", "monto": 80},
    )
    previa, _ = caja.consultar_caja(admin_user)
    for importe, metodo in (
        (200, "efectivo"),
        (300, "tarjeta"),
        (400, "transferencia"),
    ):
        pago = pagar(admin_user, cuenta, importe, metodo).registro
        assert pago.sesion_caja_id == siguiente.pk
    with pytest.raises(caja.ErrorCaja) as cambiado:
        caja.cerrar_caja(
            admin_user, siguiente.pk, str(uuid4()), datos_cierre(previa, 380)
        )
    assert cambiado.value.datos["error"] == "resumen_cambiado"
    resumen = cerrar(admin_user, siguiente, 380).resumen_cierre
    assert (
        resumen["cantidad_vigente"],
        resumen["total_vigente"],
        resumen["efectivo_esperado"],
    ) == (1, 80, 380)
    assert resumen["abonos"]["importe"] == 900 and resumen["abonos"]["cantidad"] == 3
    assert resumen["recibido_por_metodo"]["efectivo"] == {
        "ventas_directas": 80,
        "abonos": 200,
        "total": 280,
    }
    assert resumen["recibido_por_metodo"]["tarjeta"]["total"] == 300
    assert resumen["recibido_por_metodo"]["transferencia"]["total"] == 400
    assert (
        not Venta.objects.filter(sesion_caja=caja_abierta, cancelada=False)
        .exclude(pk=venta.pk)
        .exists()
    )
    primera.refresh_from_db()
    assert (
        primera.resumen_cierre["total_vigente"] == 900
        and primera.resumen_cierre["abonos"]["importe"] == 0
    )

    abrir(admin_user)
    otra_venta, abierta = fiar(admin_user, deudor)
    pagar(admin_user, abierta, 10)
    with pytest.raises(anulacion_ventas.ErrorAnulacion, match="abonos confirmados"):
        anulacion_ventas.anular_venta(admin_user, otra_venta.pk, "Duplicada")
    with pytest.raises(anulacion_ventas.ErrorAnulacion, match="cerrada"):
        anulacion_ventas.anular_venta(admin_user, venta.pk, "Duplicada")


def test_vencimiento_y_conciliacion_historica(client, admin_user, deudor, caja_abierta):
    client.force_login(admin_user)
    hoy = timezone.localdate(timezone=SANTIAGO)
    historica = CuentaPorCobrar.objects.create(
        cliente=deudor,
        monto_total=100,
        monto_pagado=20,
        fecha_emision=hoy,
        fecha_vencimiento=hoy - timedelta(days=1),
        estado="vencido",
    )
    original = PagoCliente.objects.create(
        cuenta_por_cobrar=historica, monto=20, fecha_pago=hoy, metodo_pago="cheque"
    )
    assert historica.esta_vencida and deudor.saldo_pendiente == 80
    detalle = client.get(reverse("fiados_detalle", args=[historica.pk])).json()
    assert (detalle["estado"], detalle["estado_registrado"], detalle["vencida"]) == (
        "parcial",
        "vencido",
        True,
    )
    assert client.get(reverse("fiados_saldo", args=[deudor.pk])).json()["saldo"] == 80
    result = pagar(admin_user, historica, 80)
    historica.refresh_from_db()
    assert historica.estado == "pagado" and not historica.esta_vencida
    original.refresh_from_db()
    assert original.sesion_caja_id is None and original.metodo_pago == "cheque"
    assert result.registro.sesion_caja_id == caja_abierta.pk

    mala = CuentaPorCobrar.objects.create(
        cliente=deudor,
        monto_total=100,
        monto_pagado=110,
        fecha_emision=hoy,
        estado="parcial",
    )
    assert mala.saldo_pendiente == -10
    detalle = client.get(reverse("fiados_detalle", args=[mala.pk])).json()
    assert detalle["saldo"] is None and detalle["conciliacion_requerida"]
    r = client.get(reverse("fiados_saldo", args=[deudor.pk]))
    assert r.status_code == 409 and r.json()["error"] == "cuenta_inconsistente"
    assert (
        post(client, "registrar_venta_pos", solicitud(deudor)).json()["error"]
        == "cuenta_inconsistente"
    )
    with pytest.raises(caja.ErrorCaja, match="conciliación"):
        pagar(admin_user, mala, 1)
    assert PagoCliente.objects.count() == 2


def test_permisos_paginacion_y_csrf(
    admin_user, normal_user, caja_abierta, deudor, monkeypatch
):
    call_command("crear_grupos_permisos", stdout=StringIO())
    normal_user.groups.add(Group.objects.get(name="Vendedor"))
    cliente = Client(enforce_csrf_checks=True)
    urls = [
        "fiados_buscar_clientes",
        "fiados_saldo",
        "fiados_pendientes",
        "fiados_detalle",
        "fiados_abonos",
    ]
    _, cuenta = fiar(admin_user, deudor)
    cliente.force_login(normal_user)
    for nombre, args in zip(
        urls, [[], [deudor.pk], [deudor.pk], [cuenta.pk], [cuenta.pk]]
    ):
        assert cliente.get(reverse(nombre, args=args)).status_code == 403
    assert cliente.get(reverse("listar_cuentas_cobrar")).status_code == 403

    cliente.force_login(admin_user)
    token = cliente.get(reverse("punto_venta")).cookies["csrftoken"].value
    cuerpo = {"importe": 5, "metodo_pago": "transferencia"}
    ruta = reverse("fiados_abonar", args=[cuenta.pk])
    assert cliente.get(ruta).status_code == 405
    assert post(cliente, "fiados_abonar", cuerpo, cuenta.pk).status_code == 403
    respuesta = post(
        cliente,
        "fiados_abonar",
        cuerpo,
        cuenta.pk,
        **{"X-CSRFToken": token, "X-Stockex-Account": str(normal_user.pk)},
    )
    assert respuesta.status_code == 403
    cabecera = {"X-CSRFToken": token, "X-Stockex-Account": str(admin_user.pk)}
    assert (
        post(cliente, "fiados_abonar", cuerpo, cuenta.pk, **cabecera).status_code == 201
    )
    assert (
        post(cliente, "fiados_abonar", cuerpo, cuenta.pk, **cabecera).status_code == 201
    )
    assert (
        post(cliente, "fiados_abonar", cuerpo, cuenta.pk, **cabecera).status_code == 201
    )
    assert post(cliente, "registrar_venta_pos", solicitud(deudor)).status_code == 403
    assert (
        "no-store"
        in cliente.get(reverse("fiados_saldo", args=[deudor.pk]))["Cache-Control"]
    )
    busqueda = cliente.get(reverse("fiados_buscar_clientes"), {"q": "sin RUT"})
    assert busqueda.json() == {
        "clientes": [{"id": deudor.pk, "nombre": deudor.nombre, "rut": None}]
    }
    assert "no-store" in busqueda["Cache-Control"]
    monkeypatch.setattr("inventario.views_fiados.LIMITE_PAGINA", 2)
    abonos = reverse("fiados_abonos", args=[cuenta.pk])
    pagina = cliente.get(abonos).json()
    assert len(pagina["abonos"]) == 2
    assert (
        len(cliente.get(abonos, {"antes_de": pagina["antes_de"]}).json()["abonos"]) == 1
    )
    assert cliente.get(abonos, {"antes_de": "-2"}).status_code == 400
    assert (
        cliente.post(
            reverse("registrar_pago", args=[cuenta.pk]), HTTP_X_CSRFTOKEN=token
        ).status_code
        == 423
    )
    normal_user.user_permissions.add(Permission.objects.get(codename="registrar_abono"))
    cliente.force_login(normal_user)
    assert (
        post(
            cliente, "fiados_abonar", cuerpo, cuenta.pk, **{"X-CSRFToken": token}
        ).status_code
        == 201
    )
    assert cliente.get(reverse("fiados_saldo", args=[deudor.pk])).status_code == 403


def test_limites_legacy_html_y_admin(client, admin_user, deudor, caja_abierta):
    fiar(admin_user, deudor, 100)
    client.force_login(admin_user)
    editar = reverse("editar_cliente", args=[deudor.pk])
    crear = reverse("crear_cliente")
    for monto in ("-1", "0.5", "1000000000000", "Nan"):
        assert (
            client.post(
                crear, {"nombre": "Inválido", "limite_credito": monto}
            ).status_code
            == 200
        )
        assert not Cliente.objects.filter(nombre="Inválido").exists()
    for monto in ("-1", "50"):
        assert (
            client.post(
                editar,
                {"nombre": deudor.nombre, "limite_credito": monto, "activo": "on"},
            ).status_code
            == 200
        )
        deudor.refresh_from_db()
        assert deudor.limite_credito == 0
    assert (
        client.post(
            editar, {"nombre": deudor.nombre, "limite_credito": "100", "activo": "on"}
        ).status_code
        == 302
    )
    deudor.refresh_from_db()
    assert deudor.limite_credito == 100
    ruta = reverse("admin:inventario_cliente_change", args=[deudor.pk])
    admin_datos = {
        "nombre": deudor.nombre,
        "tipo_cliente": "natural",
        "activo": "on",
        "limite_credito": "99",
    }
    assert client.post(ruta, admin_datos).status_code == 200
    deudor.refresh_from_db()
    assert deudor.limite_credito == 100
    assert (
        client.post(ruta, {**admin_datos, "limite_credito": "125"}).status_code == 302
    )
    deudor.refresh_from_db()
    assert deudor.limite_credito == 125


def test_restricciones_persistentes(admin_user, deudor, caja_abierta):
    venta, cuenta = fiar(admin_user, deudor)
    with pytest.raises(IntegrityError), transaction.atomic():
        CuentaPorCobrar.objects.create(
            venta=venta,
            cliente=deudor,
            fiado_seguro=True,
            monto_total=1000,
            fecha_emision=cuenta.fecha_emision,
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        CuentaPorCobrar.objects.filter(pk=cuenta.pk).update(monto_pagado=1001)
    pago = pagar(admin_user, cuenta, 20).registro
    with pytest.raises(IntegrityError), transaction.atomic():
        PagoCliente.objects.create(
            usuario=admin_user,
            clave=pago.clave,
            sesion_caja=caja_abierta,
            cuenta_por_cobrar=cuenta,
            monto=20,
            fecha_pago=pago.fecha_pago,
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        PagoCliente.objects.filter(pk=pago.pk).update(sesion_caja=None)
    cuenta.refresh_from_db()
    assert cuenta.monto_pagado == 20 and PagoCliente.objects.count() == 1
    historico = Cliente.objects.create(nombre="Con devolución histórica")
    Devolucion.objects.create(
        cliente=historico,
        venta=Venta.objects.create(total=35),
        tipo_devolucion="completa",
        monto_devolver=35,
        metodo_reembolso="efectivo",
        estado="procesada",
    )
    with pytest.raises(ProtectedError):
        historico.delete()

from uuid import uuid4

import pytest
from django.db import OperationalError, connection
from django.test import Client
from django.urls import reverse

from inventario import anulacion_ventas, caja
from inventario.bloqueo_caja import sqlite_ocupado
from inventario.models import (
    AnulacionVenta,
    Cliente,
    CuentaPorCobrar,
    PagoCliente,
    RegistroVenta,
    Venta,
)

from .test_caja import abrir, datos_cierre
from .test_caja_concurrencia import competir
from .test_fiados import cerrar, fiar, pagar

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def turno(admin_user):
    return abrir(admin_user), Cliente.objects.create(
        nombre="Concurrencia", limite_credito=1000
    )


@pytest.mark.parametrize("reintento", [False, True])
def test_dos_abonos_bloquean_saldo_e_idempotencia(admin_user, turno, reintento):
    sesion, cliente = turno
    _, cuenta = fiar(admin_user, cliente)
    clave = str(uuid4())
    otra = clave if reintento else str(uuid4())
    ganador, segundo = competir(
        lambda: pagar(admin_user, cuenta, 600, clave=clave),
        lambda: pagar(admin_user, cuenta, 600, clave=otra),
    )
    if reintento:
        assert segundo.repetida and segundo.registro.pk == ganador.registro.pk
    else:
        assert segundo == "abono_supera_saldo"
    cuenta.refresh_from_db()
    assert cuenta.monto_pagado == 600 and PagoCliente.objects.count() == 1
    assert caja.consultar_caja(admin_user)[1]["efectivo_esperado"] == 600


def test_dos_fiados_respetan_limite(admin_user, turno):
    sesion, cliente = turno
    primero, segundo = competir(
        lambda: fiar(admin_user, cliente, 600),
        lambda: fiar(admin_user, cliente, 600),
    )
    assert segundo == "limite_credito_excedido"
    venta, deuda = primero
    assert venta.sesion_caja_id == sesion.pk and deuda.monto_total == 600
    assert (
        Venta.objects.count()
        == RegistroVenta.objects.count()
        == CuentaPorCobrar.objects.count()
        == 1
    )


@pytest.mark.parametrize("anula_primero", [True, False])
def test_anulacion_frente_a_abono(admin_user, turno, anula_primero):
    _, cliente = turno
    venta, deuda = fiar(admin_user, cliente)

    def anular():
        return anulacion_ventas.anular_venta(admin_user, venta.pk, "Duplicada")

    def abonar():
        return pagar(admin_user, deuda, 100)

    if anula_primero:
        _, segundo = competir(anular, abonar)
        assert segundo == "cuenta_no_pagable"
        assert AnulacionVenta.objects.count() == 1 and not PagoCliente.objects.exists()
    else:
        _, segundo = competir(abonar, anular)
        assert segundo == "no_anulable"
        assert PagoCliente.objects.count() == 1 and not AnulacionVenta.objects.exists()
    venta.refresh_from_db()
    deuda.refresh_from_db()
    assert venta.cancelada == anula_primero
    assert deuda.estado == ("cancelado" if anula_primero else "parcial")


@pytest.mark.parametrize("operacion", ["fiado", "abono"])
@pytest.mark.parametrize("cierra_primero", [True, False])
def test_cierre_frente_a_fiado_y_abono(admin_user, turno, operacion, cierra_primero):
    sesion, cliente = turno
    deuda = fiar(admin_user, cliente)[1] if operacion == "abono" else None
    sesion.refresh_from_db()
    solicitud = datos_cierre(sesion)

    def cierre():
        return caja.cerrar_caja(admin_user, sesion.pk, str(uuid4()), solicitud).registro

    def escribir():
        return (
            pagar(admin_user, deuda, 100) if deuda else fiar(admin_user, cliente, 100)
        )

    if cierra_primero:
        cerrada, rechazo = competir(cierre, escribir)
        assert rechazo == "caja_no_abierta"
        assert cerrada.resumen_cierre["abonos"]["cantidad"] == 0
        assert cerrada.resumen_cierre["fiados"]["cantidad"] == int(deuda is not None)
        assert not PagoCliente.objects.exists()
        assert RegistroVenta.objects.count() == int(deuda is not None)
    else:
        _, rechazo = competir(escribir, cierre)
        assert rechazo == "resumen_cambiado"
        conciliada = cerrar(admin_user, sesion, 100 if deuda else 0)
        assert conciliada.resumen_cierre["fiados"]["cantidad"] == 1
        assert conciliada.resumen_cierre["abonos"]["importe"] == (100 if deuda else 0)


@pytest.mark.parametrize("limite_primero", [False, True])
def test_limite_legacy_y_fiado_comparten_bloqueo(admin_user, turno, limite_primero):
    sesion, cliente = turno
    navegador = Client()
    navegador.force_login(admin_user)

    def cambiar():
        bloqueo_ocupado = False

        def observar_bloqueo(execute, sql, params, many, context):
            nonlocal bloqueo_ocupado
            try:
                return execute(sql, params, many, context)
            except OperationalError as error:
                if '"inventario_bloqueocaja"' in sql and sqlite_ocupado(error):
                    bloqueo_ocupado = True
                raise

        with connection.execute_wrapper(observar_bloqueo):
            respuesta = navegador.post(
                reverse("editar_cliente", args=[cliente.pk]),
                {"nombre": cliente.nombre, "activo": "on", "limite_credito": "500"},
            )
        assert bloqueo_ocupado == (respuesta.status_code == 503)
        if bloqueo_ocupado:
            assert respuesta["Retry-After"] == "1"
            assert (
                respuesta.content.decode() == "La base está ocupada. Vuelve a intentar."
            )
            assert Cliente.objects.get(pk=cliente.pk).limite_credito == 1000
            return "base_ocupada"
        if respuesta.status_code == 200:
            assert (
                "El límite es menor que el saldo pendiente."
                in respuesta.content.decode()
            )
        return respuesta.status_code

    def vender():
        return fiar(admin_user, cliente, 600)

    if limite_primero:
        estado, rechazo = competir(cambiar, vender)
        assert estado == 302 and rechazo == "limite_credito_excedido"
        assert not Venta.objects.exists()
        assert (
            not RegistroVenta.objects.exists() and not CuentaPorCobrar.objects.exists()
        )
    else:
        (venta, deuda), estado = competir(vender, cambiar)
        assert estado == 200
        assert Venta.objects.get().pk == venta.pk
        assert venta.sesion_caja_id == sesion.pk and venta.total == 600
        assert RegistroVenta.objects.get().venta_id == venta.pk
        assert CuentaPorCobrar.objects.get().pk == deuda.pk
        assert deuda.venta_id == venta.pk and deuda.cliente_id == cliente.pk
        assert deuda.monto_total == deuda.saldo_pendiente == 600
        assert deuda.estado == "pendiente" and deuda.fiado_seguro
    cliente.refresh_from_db()
    assert cliente.limite_credito == (500 if limite_primero else 1000)

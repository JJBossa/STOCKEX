from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from django.db import OperationalError, connection, connections, transaction
from django.test import Client
from django.urls import reverse

from inventario import anulacion_ventas, caja
from inventario.bloqueo_caja import bloquear_caja, sqlite_ocupado
from inventario.models import BloqueoCaja, MovimientoCaja, SesionCaja, Venta

from .test_caja import abrir, datos_cierre, movimiento, rapida

pytestmark = pytest.mark.django_db(transaction=True)


def comprobar_espera_postgres(pid_primero, pid_segundo):
    limite = monotonic() + 5
    while monotonic() < limite:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_blocking_pids(%s)", [pid_segundo])
            if pid_primero in cursor.fetchone()[0]:
                return
        sleep(0.01)
    pytest.fail("La segunda conexión no esperó el bloqueo financiero.")


def competir(primera, segunda):
    pg = connection.vendor == "postgresql"
    sqlite_compartida = "mode=memory" in str(connection.settings_dict["NAME"])
    BloqueoCaja.objects.get_or_create(pk=1)
    guardada = Event()
    liberar = Event()
    intento = Event()
    pids = Queue()

    def ejecutar(operacion, ganadora=False):
        def vigilar_bloqueo(execute, sql, params, many, context):
            if '"inventario_bloqueocaja"' in sql:
                intento.set()
            return execute(sql, params, many, context)

        try:
            if pg:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pids.put(cursor.fetchone()[0])
            if ganadora:
                with transaction.atomic():
                    resultado = operacion()
                    guardada.set()
                    assert liberar.wait(10)
                    return resultado
            with connection.execute_wrapper(vigilar_bloqueo):
                return operacion()
        except (caja.ErrorCaja, anulacion_ventas.ErrorAnulacion) as error:
            if isinstance(error, caja.ErrorCaja):
                return error.datos["error"]
            return error.codigo
        except OperationalError as error:
            if sqlite_ocupado(error):
                return "base_ocupada"
            raise
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        pendiente = pool.submit(ejecutar, primera, True)
        try:
            assert guardada.wait(5)
            competidora = pool.submit(ejecutar, segunda)
            assert intento.wait(5)
            if pg:
                comprobar_espera_postgres(pids.get(timeout=5), pids.get(timeout=5))
            elif sqlite_compartida:
                assert competidora.result(timeout=5) == "base_ocupada"
            else:
                assert not competidora.done()
        finally:
            liberar.set()
        ganador = pendiente.result(timeout=5)
        resultado = competidora.result(timeout=5)
    if sqlite_compartida:
        resultado = ejecutar(segunda)
    return ganador, resultado


def test_aperturas_simultaneas(admin_user):
    ganadora, segunda = competir(lambda: abrir(admin_user), lambda: abrir(admin_user))
    assert segunda == "caja_abierta"
    assert SesionCaja.objects.get().pk == ganadora.pk


@pytest.mark.parametrize("abre_primero", [True, False])
def test_apertura_y_venta_simultaneas(admin_user, abre_primero):
    def apertura():
        return abrir(admin_user)

    def venta():
        return rapida(admin_user)

    if abre_primero:
        sesion, registrada = competir(apertura, venta)
    else:
        registrada, sesion = competir(venta, apertura)
    assert registrada.sesion_caja_id == (sesion.pk if abre_primero else None)


@pytest.mark.parametrize("misma_clave", [True, False])
def test_cierres_simultaneos(admin_user, misma_clave):
    sesion = abrir(admin_user)
    datos = datos_cierre(sesion)
    clave = str(uuid4())
    otra = clave if misma_clave else str(uuid4())
    primero, segundo = competir(
        lambda: caja.cerrar_caja(admin_user, sesion.pk, clave, datos),
        lambda: caja.cerrar_caja(admin_user, sesion.pk, otra, datos),
    )
    assert not primero.repetida
    if misma_clave:
        assert segundo.repetida and segundo.registro.pk == primero.registro.pk
    else:
        assert segundo == "caja_cerrada"
    assert SesionCaja.objects.filter(cerrada_en__isnull=False).count() == 1


def test_movimientos_simultaneos_misma_clave(admin_user):
    sesion = abrir(admin_user)
    clave = str(uuid4())
    datos = {"tipo": "ingreso", "importe": 20, "motivo": "Fondo de sencillo"}

    def registrar():
        return caja.registrar_movimiento(admin_user, sesion.pk, clave, datos)

    primero, segundo = competir(registrar, registrar)
    assert not primero.repetida and segundo.repetida
    assert MovimientoCaja.objects.get().pk == primero.registro.pk == segundo.registro.pk


@pytest.mark.parametrize("operacion", ["venta", "anulacion", "movimiento"])
@pytest.mark.parametrize("cierra_primero", [True, False])
def test_cierre_simultaneo_con_operacion(admin_user, operacion, cierra_primero):
    sesion = abrir(admin_user)
    previa = rapida(admin_user) if operacion == "anulacion" else None
    sesion.refresh_from_db()
    cerrar_con = datos_cierre(sesion, contado=900 if previa else 0)
    clave = str(uuid4())

    def cierre():
        return caja.cerrar_caja(admin_user, sesion.pk, clave, cerrar_con)

    def escribir():
        if operacion == "venta":
            return rapida(admin_user)
        if operacion == "movimiento":
            return movimiento(admin_user, sesion)
        return anulacion_ventas.anular_venta(admin_user, previa.pk, "Duplicada")

    if cierra_primero:
        cerrada, resultado = competir(cierre, escribir)
        assert cerrada.registro.resumen_cierre["efectivo_esperado"] == (
            900 if previa else 0
        )
        if operacion == "venta":
            # STK-06A permite una venta nueva sin sesión si el cierre confirma primero.
            assert resultado.sesion_caja_id is None
        elif operacion == "anulacion":
            assert resultado == "no_anulable"
            assert not Venta.objects.get(pk=previa.pk).cancelada
        else:
            assert resultado == "caja_cerrada"
            assert not MovimientoCaja.objects.exists()
        return

    _, rechazo = competir(escribir, cierre)
    assert rechazo == "resumen_cambiado"
    sesion, resumen = caja.consultar_caja(admin_user)
    cerrar_con.update(datos_cierre(sesion, resumen["efectivo_esperado"]))
    r = cierre().registro.resumen_cierre
    assert (r["cantidad_vigente"], r["cantidad_anulada"], r["ingresos"]) == {
        "venta": (1, 0, 0),
        "anulacion": (0, 1, 0),
        "movimiento": (0, 0, 100),
    }[operacion]


def test_sqlite_ocupado_responde_503_y_permite_reintentar(admin_user):
    if connection.vendor != "sqlite":
        pytest.skip("Verifica el manejo de bloqueo temporal de SQLite.")
    cliente = Client()
    cliente.force_login(admin_user)
    url = reverse("caja_abrir")
    clave = str(uuid4())

    def solicitud():
        return cliente.post(
            url,
            {"efectivo_inicial": 0},
            content_type="application/json",
            headers={"Idempotency-Key": clave},
        )

    def intentar():
        try:
            with connection.cursor() as cursor:
                cursor.execute("PRAGMA busy_timeout = 50")
            return solicitud()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            bloquear_caja()
            ocupada = pool.submit(intentar).result(timeout=5)
            assert ocupada.status_code == 503 and ocupada["Retry-After"] == "1"
        assert solicitud().status_code == 201

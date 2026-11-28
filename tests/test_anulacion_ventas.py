from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from io import StringIO
from queue import Queue
from statistics import median
from threading import Event
from time import monotonic, perf_counter, sleep

import pytest
from django.contrib import admin
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.db import IntegrityError, connection, connections
from django.db.models.deletion import ProtectedError
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from inventario.anulacion_ventas import anular_venta
from inventario.models import (
    AnulacionVenta,
    Cliente,
    Cotizacion,
    CuentaPorCobrar,
    Devolucion,
    ItemVenta,
    Lote,
    MovimientoLote,
    MovimientoStock,
    Venta,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def roles():
    call_command("crear_grupos_permisos", stdout=StringIO())
    return tuple(
        Group.objects.get(name=nombre) for nombre in ("Administrador", "Vendedor")
    )


@pytest.fixture
def actores(django_user_model, roles):
    administrador = django_user_model.objects.create_user("responsable-stk05b")
    administrador.groups.add(roles[0])
    vendedor = django_user_model.objects.create_user("vendedor-stk05b")
    vendedor.groups.add(roles[1])
    return administrador, vendedor


@pytest.fixture
def venta(actores):
    return Venta.objects.create(
        usuario=actores[1], modalidad=Venta.Modalidad.RAPIDA, subtotal=4000, total=4000
    )


def enviar(client, venta, motivo, **datos):
    return client.post(
        reverse("cancelar_venta", args=[venta.pk]),
        {"motivo": motivo, **datos},
        HTTP_ACCEPT="application/json",
    )


@pytest.mark.parametrize("metodo", ["efectivo", "tarjeta", "transferencia"])
@pytest.mark.parametrize("modalidad", Venta.Modalidad.values)
def test_conserva_venta_e_inventario(client, actores, producto, modalidad, metodo):
    administrador, vendedor = actores
    venta = Venta.objects.create(
        usuario=vendedor,
        modalidad=modalidad,
        subtotal=4200,
        descuento=200,
        total=4000,
        monto_recibido=5000,
        cambio=1000,
        metodo_pago=metodo,
        notas="Original",
    )
    if modalidad == Venta.Modalidad.DETALLADA:
        ItemVenta.objects.create(
            venta=venta,
            producto=producto,
            nombre_producto=producto.nombre,
            cantidad=2,
            precio_unitario=2100,
        )
    original = Venta.objects.values().get(pk=venta.pk)
    lineas = list(venta.items.values())
    catalogo = list(type(producto).objects.values())
    movimientos = [
        modelo.objects.count() for modelo in (MovimientoLote, MovimientoStock)
    ]
    client.force_login(administrador)
    antes = timezone.now()
    respuesta = enviar(
        client,
        venta,
        "  Venta ingresada dos veces  ",
        total=1,
        metodo_pago="mixto",
        fecha="2020-01-01T00:00:00Z",
        usuario=vendedor.pk,
        cancelada=False,
    )
    assert respuesta.status_code == 201
    assert respuesta.json() == {"id": venta.pk, "cancelada": True, "repetida": False}
    anulacion = AnulacionVenta.objects.get(venta=venta)
    assert anulacion.usuario == administrador
    assert antes <= anulacion.fecha <= timezone.now()
    assert anulacion.motivo == "Venta ingresada dos veces"
    assert Venta.objects.values().get(pk=venta.pk) == {**original, "cancelada": True}
    assert list(venta.items.values()) == lineas
    assert list(type(producto).objects.values()) == catalogo
    assert [
        modelo.objects.count() for modelo in (MovimientoLote, MovimientoStock)
    ] == movimientos


@pytest.mark.parametrize("motivo", ["", " \n\t ", "á" * 251, "motivo\x00"])
def test_motivo_invalido(client, actores, venta, motivo):
    client.force_login(actores[0])
    respuesta = enviar(client, venta, motivo)
    assert respuesta.status_code == 400
    assert respuesta.json()["error"] == "motivo_invalido"
    assert not Venta.objects.get(pk=venta.pk).cancelada
    assert not AnulacionVenta.objects.exists()


def test_motivo_textual_250_caracteres_y_redireccion_nativa(client, actores, venta):
    client.force_login(actores[0])
    detalle = reverse("detalle_venta", args=[venta.pk])
    filtros = "?periodo=todas&metodo_pago=efectivo&page=2"
    motivo = '<b onclick="alert(1)">Corrección & revisión · ñ</b>'.ljust(250, "é")
    respuesta = client.post(
        reverse("cancelar_venta", args=[venta.pk]) + filtros, {"motivo": f" {motivo} "}
    )
    assert respuesta.status_code == 302
    assert respuesta["Location"] == detalle + filtros
    vista = client.get(respuesta["Location"])
    assert vista.context["regreso"] == reverse("listar_ventas") + filtros
    assert vista.context["anulacion"].motivo == motivo
    assert escape(motivo).encode() in vista.content
    assert motivo.encode() not in vista.content
    assert b"responsable-stk05b" in vista.content
    assert b"data-form-anulacion" not in vista.content


def test_autenticacion_roles_metodos_y_alcance(
    client, actores, venta, django_user_model
):
    administrador, vendedor = actores
    ruta = reverse("cancelar_venta", args=[venta.pk])
    assert enviar(client, venta, "Duplicada").status_code == 302
    assert client.get(ruta).status_code == 302
    assert administrador.has_perm("inventario.anular_venta")
    assert not vendedor.has_perm("inventario.anular_venta")
    client.force_login(vendedor)
    assert enviar(client, venta, "Duplicada").status_code == 403
    assert (
        b"data-form-anulacion"
        not in client.get(reverse("detalle_venta", args=[venta.pk])).content
    )
    client.force_login(administrador)
    assert client.get(ruta).status_code == 405
    assert client.put(ruta).status_code == 405
    assert client.delete(ruta).status_code == 405
    assert (
        client.post(
            reverse("cancelar_venta", args=[venta.pk + 999]), {"motivo": "No existe"}
        ).status_code
        == 404
    )
    tercero = django_user_model.objects.create_user("vendedor-delegado")
    tercero.groups.add(vendedor.groups.get())
    tercero.user_permissions.add(Permission.objects.get(codename="anular_venta"))
    client.force_login(tercero)
    assert enviar(client, venta, "Fuera de alcance").status_code == 404
    propia = Venta.objects.create(usuario=tercero, total=200)
    assert enviar(client, propia, "Dentro de su alcance").status_code == 201
    assert not Venta.objects.get(pk=venta.pk).cancelada


def test_csrf(actores, venta):
    client = Client(enforce_csrf_checks=True)
    client.force_login(actores[0])
    ruta = reverse("cancelar_venta", args=[venta.pk])
    client.get(reverse("detalle_venta", args=[venta.pk]))
    assert client.post(ruta, {"motivo": "Duplicada"}).status_code == 403
    assert not AnulacionVenta.objects.exists()
    assert (
        client.post(
            ruta,
            {"motivo": "Duplicada"},
            HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
            HTTP_ACCEPT="application/json",
        ).status_code
        == 201
    )


def test_reintentos_y_rutas_de_escritura(client, actores, venta, admin_user):
    client.force_login(actores[0])
    ticket = reverse("imprimir_ticket_venta", args=[venta.pk])
    tipos = ("termica", "a4")
    assert [client.get(f"{ticket}?tipo={tipo}").status_code for tipo in tipos] == [
        200,
        200,
    ]
    assert enviar(client, venta, "Duplicada").status_code == 201
    assert [client.get(f"{ticket}?tipo={tipo}").status_code for tipo in tipos] == [
        404,
        404,
    ]
    auditoria = AnulacionVenta.objects.values().get(venta=venta)
    respuesta = enviar(client, venta, "  Duplicada  ")
    assert respuesta.status_code == 200
    assert respuesta.json() == {"id": venta.pk, "cancelada": True, "repetida": True}
    assert enviar(client, venta, "Cambiar motivo").status_code == 409
    client.force_login(admin_user)
    assert enviar(client, venta, "Duplicada").status_code == 409
    url_api = reverse("api:venta-detail", args=[venta.pk])
    assert (
        client.patch(
            url_api, {"cancelada": False}, content_type="application/json"
        ).status_code
        == 405
    )
    assert client.delete(url_api).status_code == 405
    for accion in ("change", "delete"):
        assert (
            client.post(
                reverse(f"admin:inventario_venta_{accion}", args=[venta.pk]),
                {"cancelada": False},
            ).status_code
            == 403
        )
    assert not admin.site.is_registered(AnulacionVenta)
    with pytest.raises(ProtectedError):
        venta.delete()
    with pytest.raises(ProtectedError):
        actores[0].delete()
    assert Venta.objects.get(pk=venta.pk).cancelada
    assert AnulacionVenta.objects.values().get(venta=venta) == auditoria


def test_historica_sin_metadatos(client, actores, venta):
    Venta.objects.filter(pk=venta.pk).update(cancelada=True)
    client.force_login(actores[0])
    assert enviar(client, venta, "Dato inventado").status_code == 409
    contenido = client.get(reverse("detalle_venta", args=[venta.pk])).content
    assert "Anulación histórica sin información".encode() in contenido
    assert b"data-form-anulacion" not in contenido
    assert not AnulacionVenta.objects.exists()


@pytest.mark.parametrize(
    "dependencia",
    [
        "credito",
        "mixto",
        "es_credito",
        "otro",
        "cuenta",
        "devolucion",
        "cotizacion",
        "lote",
        "stock_distinto",
        "stock_incompleto",
    ],
)
def test_bloquea_dependencias(client, actores, venta, producto, dependencia):
    if dependencia in ("credito", "mixto", "otro"):
        Venta.objects.filter(pk=venta.pk).update(metodo_pago=dependencia)
    elif dependencia == "es_credito":
        Venta.objects.filter(pk=venta.pk).update(es_credito=True)
    elif dependencia == "cuenta":
        hoy = timezone.localdate()
        CuentaPorCobrar.objects.create(
            venta=venta,
            cliente=Cliente.objects.create(nombre="Cliente sintético"),
            fecha_emision=hoy,
            fecha_vencimiento=hoy,
            monto_total=venta.total,
        )
    elif dependencia == "devolucion":
        Devolucion.objects.create(
            venta=venta,
            tipo_devolucion="total",
            metodo_reembolso="efectivo",
            monto_devolver=venta.total,
            motivo="Registro histórico",
        )
    elif dependencia == "cotizacion":
        Cotizacion.objects.create(
            convertida_en_venta=venta, fecha_vencimiento=timezone.localdate()
        )
    elif dependencia == "lote":
        lote = Lote.objects.create(producto=producto, numero_lote="STK05B")
        MovimientoLote.objects.create(venta=venta, lote=lote, tipo="salida", cantidad=1)
    else:
        ItemVenta.objects.create(
            venta=venta,
            producto=producto,
            nombre_producto=producto.nombre,
            cantidad=1,
            precio_unitario=venta.total,
            stock_anterior=20,
            stock_despues=19 if dependencia == "stock_distinto" else None,
        )
    client.force_login(actores[0])
    detalle = client.get(reverse("detalle_venta", args=[venta.pk]))
    assert b"data-form-anulacion" not in detalle.content
    assert b"Anulaci" in detalle.content and b"no disponible" in detalle.content
    respuesta = enviar(client, venta, "Duplicada")
    assert respuesta.status_code == 409
    assert respuesta.json()["error"] == "no_anulable"
    assert not Venta.objects.get(pk=venta.pk).cancelada
    assert not AnulacionVenta.objects.exists()


def test_rollback_de_estado_y_auditoria(monkeypatch, actores, venta):
    crear = AnulacionVenta.objects.create

    def crear_y_fallar(**datos):
        crear(**datos)
        raise IntegrityError("Fallo simulado al registrar la anulación")

    monkeypatch.setattr(AnulacionVenta.objects, "create", crear_y_fallar)
    with pytest.raises(IntegrityError, match="Fallo simulado"):
        anular_venta(actores[0], venta.pk, "Duplicada")
    assert not Venta.objects.get(pk=venta.pk).cancelada
    assert not AnulacionVenta.objects.exists()


def test_resumen_historial_y_clientes(client, actores, venta):
    primero = Cliente.objects.create(nombre="Alfa")
    segundo = Cliente.objects.create(nombre="Beta")
    Venta.objects.filter(pk=venta.pk).update(cliente=primero)
    Venta.objects.create(total=2000, metodo_pago="tarjeta", cliente=segundo)
    Venta.objects.create(total=1000, metodo_pago="transferencia", cliente=primero)
    Venta.objects.create(total=700, metodo_pago="efectivo", cancelada=True)
    client.force_login(actores[0])
    ruta = reverse("listar_ventas") + "?periodo=todas"
    clientes = reverse("listar_clientes") + "?orden=total_compras"

    def comprobar(
        resumen, total, vigentes, promedio, monto_anulado, anuladas, efectivo
    ):
        assert (
            resumen.total_vigente,
            resumen.cantidad_vigente,
            resumen.promedio,
            resumen.monto_anulado,
            resumen.cantidad_anulada,
        ) == (total, vigentes, Decimal(promedio), monto_anulado, anuladas)
        totales_pago = {
            linea.metodo: (linea.total, linea.cantidad) for linea in resumen.pagos
        }
        assert totales_pago == {
            "efectivo": efectivo,
            "tarjeta": (2000, 1),
            "transferencia": (1000, 1),
            "credito": (0, 0),
            "mixto": (0, 0),
        }

    comprobar(
        client.get(ruta).context["resumen"], 7000, 3, "2333.33", 700, 1, (4000, 1)
    )
    assert [c.pk for c in client.get(clientes).context["clientes"]] == [
        primero.pk,
        segundo.pk,
    ]
    assert enviar(client, venta, "Duplicada").status_code == 201
    historial = client.get(ruta)
    comprobar(historial.context["resumen"], 3000, 2, "1500.00", 4700, 2, (0, 0))
    fila = next(
        registro for registro in historial.context["ventas"] if registro.pk == venta.pk
    )
    assert fila.cancelada and fila.total == 4000
    ordenados = list(client.get(clientes).context["clientes"])
    assert [c.pk for c in ordenados] == [segundo.pk, primero.pk]
    assert [c.total_compras for c in ordenados] == [2000, 1000]


@pytest.mark.django_db(transaction=True)
def test_concurrencia_real_postgresql(monkeypatch, django_user_model):
    if connection.vendor != "postgresql":
        pytest.skip("Verifica el bloqueo SELECT FOR UPDATE en PostgreSQL")
    primero = django_user_model.objects.create_superuser("responsable-primero")
    segundo = django_user_model.objects.create_superuser("responsable-segundo")
    venta = Venta.objects.create(total=4000)
    guardada = Event()
    liberar = Event()
    pids = Queue()
    crear = AnulacionVenta.objects.create

    def crear_bajo_bloqueo(**datos):
        auditoria = crear(**datos)
        if datos["usuario"].pk == primero.pk:
            guardada.set()
            assert liberar.wait(10)
        return auditoria

    def intentar(pk, motivo):
        try:
            usuario = django_user_model.objects.get(pk=pk)
            cliente = Client()
            cliente.force_login(usuario)
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                pids.put(cursor.fetchone()[0])
            return enviar(cliente, venta, motivo)
        finally:
            connections.close_all()

    monkeypatch.setattr(AnulacionVenta.objects, "create", crear_bajo_bloqueo)
    with ThreadPoolExecutor(max_workers=2) as pool:
        ganadora = pool.submit(intentar, primero.pk, "Primer motivo")
        try:
            assert guardada.wait(5)
            pid_primero = pids.get(timeout=5)
            competidora = pool.submit(intentar, segundo.pk, "Segundo motivo")
            pid_segundo = pids.get(timeout=5)
            bloqueadores = []
            limite = monotonic() + 5
            while monotonic() < limite:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_blocking_pids(%s)", [pid_segundo])
                    bloqueadores = cursor.fetchone()[0]
                if pid_primero in bloqueadores:
                    break
                sleep(0.01)
            assert pid_primero in bloqueadores
        finally:
            liberar.set()
        exito = ganadora.result(timeout=5)
        assert exito.status_code == 201 and not exito.json()["repetida"]
        conflicto = competidora.result(timeout=5)
        assert (
            conflicto.status_code == 409 and conflicto.json()["error"] == "ya_anulada"
        )
    auditoria = AnulacionVenta.objects.get(venta=venta)
    assert (auditoria.usuario, auditoria.motivo) == (primero, "Primer motivo")
    assert Venta.objects.get(pk=venta.pk).cancelada


@pytest.mark.django_db(transaction=True)
def test_medicion_solicitudes_anulacion(client, actores, producto):
    client.force_login(actores[0])
    for modalidad in Venta.Modalidad.values:
        muestras = {operacion: [] for operacion in ("post", "reintento", "estado")}
        for _ in range(20):
            venta = Venta.objects.create(modalidad=modalidad, total=4000)
            if modalidad == Venta.Modalidad.DETALLADA:
                ItemVenta.objects.bulk_create(
                    [
                        ItemVenta(
                            venta=venta,
                            producto=producto,
                            nombre_producto=producto.nombre,
                            cantidad=1,
                            precio_unitario=400,
                            subtotal=400,
                        )
                        for _ in range(10)
                    ]
                )
            ruta = reverse("detalle_venta", args=[venta.pk])
            for operacion in muestras:
                with CaptureQueriesContext(connection) as consultas:
                    inicio = perf_counter()
                    respuesta = (
                        client.get(ruta)
                        if operacion == "estado"
                        else enviar(client, venta, "Medición sintética")
                    )
                    duracion = (perf_counter() - inicio) * 1000
                assert respuesta.status_code == (201 if operacion == "post" else 200)
                muestras[operacion].append((duracion, len(consultas)))
        for operacion, resultados in muestras.items():
            tiempos, consultas = zip(*resultados)
            print(
                f"STK05B {connection.vendor} {modalidad} {operacion}: "
                f"mediana {median(tiempos):.2f} ms; SQL {min(consultas)}–{max(consultas)}"
            )

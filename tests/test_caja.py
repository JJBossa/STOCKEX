from datetime import datetime
from io import StringIO
from uuid import uuid4

import pytest
from django.contrib import admin
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models import ProtectedError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from inventario import anulacion_ventas, caja, registro_ventas
from inventario.models import (
    AnulacionVenta,
    BloqueoCaja,
    MovimientoCaja,
    MovimientoStock,
    RegistroVenta,
    SesionCaja,
    Venta,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def cajero(admin_user, client):
    client.force_login(admin_user)
    return client


def post(client, ruta, datos, *args, clave=None, **headers):
    return client.post(
        reverse(ruta, args=args),
        datos,
        content_type="application/json",
        headers={"Idempotency-Key": clave or str(uuid4()), **headers},
    )


def abrir(usuario, inicial=0):
    return caja.abrir_caja(
        usuario, str(uuid4()), {"efectivo_inicial": inicial}
    ).registro


def rapida(usuario, **campos):
    return registro_ventas.registrar_venta(
        usuario,
        str(uuid4()),
        {"modalidad": "rapida", "metodo_pago": "efectivo", "monto": 900, **campos},
    ).venta


def movimiento(usuario, sesion, **campos):
    return caja.registrar_movimiento(
        usuario,
        sesion.pk,
        str(uuid4()),
        {"tipo": "ingreso", "importe": 100, "motivo": "Fondo adicional", **campos},
    ).registro


def datos_cierre(sesion, contado=0, **campos):
    return {
        "efectivo_contado": contado,
        "huella": str(sesion.version_resumen),
        **campos,
    }


def test_apertura_idempotente_y_restriccion_persistente(cajero, admin_user):
    activa = reverse("caja_activa")
    assert cajero.get(activa).json() == {"sesion": None}
    clave = str(uuid4())
    datos = {"efectivo_inicial": 0, "observaciones": " Inventario previo "}
    respuesta = post(cajero, "caja_abrir", datos, clave=clave)
    assert respuesta.status_code == 201 and "no-store" in respuesta["Cache-Control"]
    apertura = respuesta.json()
    assert apertura["abierta_por_id"] == admin_user.pk
    assert apertura["observaciones_apertura"] == "Inventario previo"
    assert apertura["efectivo_inicial"] == 0
    assert not apertura["repetida"]
    sesion = SesionCaja.objects.get(pk=apertura["id"])
    repetida = post(cajero, "caja_abrir", datos, clave=clave)
    assert repetida.status_code == 200
    assert repetida.json() == {**apertura, "repetida": True}
    distinta = post(cajero, "caja_abrir", {**datos, "efectivo_inicial": 1}, clave=clave)
    assert (
        distinta.status_code == 409 and distinta.json()["error"] == "clave_en_conflicto"
    )
    segunda = post(cajero, "caja_abrir", datos)
    assert segunda.status_code == 409 and segunda.json()["error"] == "caja_abierta"
    with pytest.raises(IntegrityError), transaction.atomic():
        SesionCaja.objects.create(
            abierta_por=admin_user, efectivo_inicial=1, clave_apertura=uuid4()
        )
    with pytest.raises(ProtectedError):
        admin_user.delete()
    assert SesionCaja.objects.count() == 1
    assert cajero.get(activa).json()["huella"] == str(sesion.version_resumen)

    caja.cerrar_caja(admin_user, sesion.pk, str(uuid4()), datos_cierre(sesion))
    tardia = post(cajero, "caja_abrir", datos, clave=clave)
    assert tardia.status_code == 200 and tardia.json() == repetida.json()
    assert cajero.get(activa).json() == {"sesion": None}
    assert abrir(admin_user).pk != sesion.pk


@pytest.mark.parametrize(
    "valor", [-1, 1.5, 1.0, "1", True, None, [], caja.MAX_CONTADO + 1]
)
def test_importes_invalidos_en_las_tres_operaciones(admin_user, cajero, valor):
    assert post(cajero, "caja_abrir", {"efectivo_inicial": valor}).status_code == 400
    sesion = abrir(admin_user)
    assert (
        post(
            cajero,
            "caja_movimiento",
            {"tipo": "retiro", "importe": valor, "motivo": "Depósito"},
            sesion.pk,
        ).status_code
        == 400
    )
    assert (
        post(cajero, "caja_cerrar", datos_cierre(sesion, valor), sesion.pk).status_code
        == 400
    )
    assert not MovimientoCaja.objects.exists()
    sesion.refresh_from_db()
    assert sesion.cerrada_en is None


@pytest.mark.parametrize(
    "datos",
    [
        {"tipo": "retiro", "importe": 0, "motivo": "Depósito"},
        {"tipo": "gasto", "importe": 1, "motivo": "Depósito"},
        {"tipo": "retiro", "importe": 1, "motivo": " "},
        {"tipo": "retiro", "importe": 1, "motivo": "\x00"},
        {"tipo": "retiro", "importe": 1, "motivo": "\ud800"},
        {"tipo": "retiro", "importe": 1},
        {"tipo": "retiro", "importe": 1, "motivo": "a" * 251},
        {"tipo": "retiro", "importe": 1, "motivo": "OK", "usuario_id": 1},
    ],
)
def test_movimientos_rechazan_datos_invalidos(cajero, admin_user, datos):
    sesion = abrir(admin_user)
    respuesta = post(cajero, "caja_movimiento", datos, sesion.pk)
    assert respuesta.status_code == 400
    assert not MovimientoCaja.objects.exists()


def test_asociacion_de_dos_vendedores_totales_e_inventario(
    admin_user, cajero, django_user_model, producto
):
    previa = Venta.objects.create(
        usuario=admin_user, modalidad=Venta.Modalidad.RAPIDA, total=5000
    )
    historica = Venta.objects.create(total=6000, cancelada=True)
    call_command("crear_grupos_permisos", stdout=StringIO())
    vendedores = [
        django_user_model.objects.create_user(nombre) for nombre in ("a", "b")
    ]
    for vendedor in vendedores:
        vendedor.groups.add(Group.objects.get(name="Vendedor"))

    sesion = abrir(admin_user, inicial=500)
    efectivo = rapida(vendedores[0], monto_recibido=1000)
    detallada = registro_ventas.registrar_venta(
        vendedores[1],
        str(uuid4()),
        {
            "modalidad": "detallada",
            "metodo_pago": "tarjeta",
            "items": [
                {"producto_id": producto.pk, "cantidad": 1, "precio_visto": 10_000}
            ],
        },
    ).venta
    transferencia = rapida(vendedores[0], monto=800, metodo_pago="transferencia")
    anulada = rapida(vendedores[1], monto=700)
    anulacion_ventas.anular_venta(admin_user, anulada.pk, "Venta duplicada")
    movimiento(admin_user, sesion, importe=250)
    movimiento(admin_user, sesion, tipo="retiro", importe=200)

    assert (efectivo.total, efectivo.monto_recibido, efectivo.cambio) == (
        900,
        1000,
        100,
    )
    assert set(sesion.ventas.values_list("pk", "usuario_id")) == {
        (efectivo.pk, vendedores[0].pk),
        (detallada.pk, vendedores[1].pk),
        (transferencia.pk, vendedores[0].pk),
        (anulada.pk, vendedores[1].pk),
    }
    assert set(
        Venta.objects.filter(sesion_caja__isnull=True).values_list("pk", flat=True)
    ) == {previa.pk, historica.pk}
    previa.refresh_from_db()
    assert previa.sesion_caja_id is None
    invalida = Client()
    invalida.force_login(vendedores[0])
    respuesta_venta = post(
        invalida,
        "registrar_venta_pos",
        {
            "modalidad": "rapida",
            "metodo_pago": "efectivo",
            "monto": 5,
            "sesion_caja_id": sesion.pk,
        },
    )
    assert respuesta_venta.status_code == 400
    assert (
        anulada.sesion_caja_id
        == efectivo.sesion_caja_id
        == detallada.sesion_caja_id
        == sesion.pk
    )
    assert sesion.ventas.count() == 4
    assert (
        invalida.get(reverse("detalle_venta", args=[detallada.pk])).status_code == 404
    )
    resumen = cajero.get(reverse("caja_activa")).json()["resumen"]
    assert resumen == {
        "efectivo_inicial": 500,
        "cantidad_vigente": 3,
        "total_vigente": 11700,
        "por_metodo": {
            "efectivo": {"cantidad": 1, "importe": 900},
            "tarjeta": {"cantidad": 1, "importe": 10000},
            "transferencia": {"cantidad": 1, "importe": 800},
            "credito": {"cantidad": 0, "importe": 0},
            "mixto": {"cantidad": 0, "importe": 0},
        },
        "cantidad_anulada": 1,
        "monto_anulado": 700,
        "fiados": {"cantidad": 0, "importe": 0},
        "ventas_directas": {"cantidad": 3, "importe": 11700},
        "abonos": {
            "cantidad": 0,
            "importe": 0,
            "por_metodo": {
                metodo: {"cantidad": 0, "importe": 0}
                for metodo in ("efectivo", "tarjeta", "transferencia")
            },
        },
        "recibido_por_metodo": {
            "efectivo": {"ventas_directas": 900, "abonos": 0, "total": 900},
            "tarjeta": {"ventas_directas": 10000, "abonos": 0, "total": 10000},
            "transferencia": {"ventas_directas": 800, "abonos": 0, "total": 800},
        },
        "ingresos": 250,
        "retiros": 200,
        "cantidad_ingresos": 1,
        "cantidad_retiros": 1,
        "efectivo_esperado": 1450,
    }
    producto.refresh_from_db()
    assert producto.stock == 50
    assert not MovimientoStock.objects.exists()


def test_movimiento_idempotente_incluso_despues_del_cierre(admin_user, cajero):
    sesion = abrir(admin_user)
    clave = str(uuid4())
    datos = {"tipo": "retiro", "importe": 40, "motivo": " Depósito "}
    nueva = post(cajero, "caja_movimiento", datos, sesion.pk, clave=clave)
    assert nueva.status_code == 201
    registrada = nueva.json()
    assert (
        registrada["motivo"] == "Depósito" and registrada["usuario_id"] == admin_user.pk
    )
    sesion.refresh_from_db()
    huella = sesion.version_resumen
    repetida = post(cajero, "caja_movimiento", datos, sesion.pk, clave=clave)
    assert repetida.status_code == 200
    assert repetida.json() == {**registrada, "repetida": True}
    conflicto = post(
        cajero, "caja_movimiento", {**datos, "importe": 41}, sesion.pk, clave=clave
    )
    assert (
        conflicto.status_code == 409
        and conflicto.json()["error"] == "clave_en_conflicto"
    )
    assert MovimientoCaja.objects.count() == 1
    sesion.refresh_from_db()
    assert sesion.version_resumen == huella

    caja.cerrar_caja(
        admin_user,
        sesion.pk,
        str(uuid4()),
        datos_cierre(sesion, observaciones="El retiro supera al efectivo inicial"),
    )
    assert (
        post(cajero, "caja_movimiento", datos, sesion.pk, clave=clave).json()
        == repetida.json()
    )
    rechazo = post(cajero, "caja_movimiento", datos, sesion.pk)
    assert rechazo.status_code == 409 and rechazo.json()["error"] == "caja_cerrada"
    with pytest.raises(ProtectedError):
        sesion.delete()


@pytest.mark.parametrize(
    "contado,diferencia,clasificacion",
    [(100, 0, "cuadrada"), (70, -30, "faltante"), (130, 30, "sobrante")],
)
def test_cierre_sin_ventas_y_reintentos(
    admin_user, cajero, contado, diferencia, clasificacion
):
    sesion = abrir(admin_user, inicial=100)
    datos = datos_cierre(sesion, contado)
    if diferencia:
        respuesta = post(cajero, "caja_cerrar", datos, sesion.pk)
        assert (
            respuesta.status_code == 400
            and respuesta.json()["error"] == "observaciones_requeridas"
        )
        sesion.refresh_from_db()
        assert sesion.cerrada_en is None
        datos["observaciones"] = " Diferencia confirmada "
    clave = str(uuid4())
    nueva = post(cajero, "caja_cerrar", datos, sesion.pk, clave=clave)
    assert nueva.status_code == 201
    cierre = nueva.json()
    assert cierre["efectivo_contado"] == contado
    assert cierre["observaciones_cierre"] == datos.get("observaciones", "").strip()
    assert cierre["cerrada_por_id"] == admin_user.pk
    assert cierre["resumen"]["cantidad_vigente"] == 0
    assert cierre["resumen"]["efectivo_esperado"] == 100
    assert cierre["resumen"]["diferencia"] == diferencia
    assert cierre["resumen"]["clasificacion"] == clasificacion
    repetida = post(cajero, "caja_cerrar", datos, sesion.pk, clave=clave)
    assert repetida.status_code == 200 and repetida.json() == {
        **cierre,
        "repetida": True,
    }
    for campos in (
        {"efectivo_contado": contado + 1},
        {"observaciones": "Otra nota"},
        {"huella": str(uuid4())},
    ):
        distinta = post(
            cajero, "caja_cerrar", {**datos, **campos}, sesion.pk, clave=clave
        )
        assert (
            distinta.status_code == 409
            and distinta.json()["error"] == "clave_en_conflicto"
        )
    doble = post(cajero, "caja_cerrar", datos, sesion.pk)
    assert doble.status_code == 409 and doble.json()["error"] == "caja_cerrada"
    assert cajero.get(reverse("caja_activa")).json() == {"sesion": None}


def test_reconfirmacion_aunque_el_efectivo_no_cambie(cajero, admin_user):
    sesion = abrir(admin_user)
    url_activa = reverse("caja_activa")
    datos = datos_cierre(sesion)
    venta = rapida(admin_user, metodo_pago="tarjeta")
    clave = str(uuid4())
    for escribir in (
        lambda: anulacion_ventas.anular_venta(admin_user, venta.pk, "Corregir tarjeta"),
        lambda: movimiento(admin_user, sesion),
    ):
        conflicto = post(cajero, "caja_cerrar", datos, sesion.pk, clave=clave)
        assert (
            conflicto.status_code == 409
            and conflicto.json()["error"] == "resumen_cambiado"
        )
        datos["huella"] = cajero.get(url_activa).json()["huella"]
        escribir()
    conflicto = post(cajero, "caja_cerrar", datos, sesion.pk, clave=clave)
    assert (
        conflicto.status_code == 409 and conflicto.json()["error"] == "resumen_cambiado"
    )
    activa = cajero.get(url_activa).json()
    datos.update(
        huella=activa["huella"], efectivo_contado=activa["resumen"]["efectivo_esperado"]
    )
    assert post(cajero, "caja_cerrar", datos, sesion.pk, clave=clave).status_code == 201


def test_cierre_historico_venta_idempotente_y_anulacion_bloqueada(
    cajero, admin_user, monkeypatch
):
    sesion = abrir(admin_user)
    clave = str(uuid4())
    datos = {"modalidad": "rapida", "metodo_pago": "efectivo", "monto": 90}
    venta = registro_ventas.registrar_venta(admin_user, clave, datos).venta
    anulada = rapida(admin_user)
    anulacion = anulacion_ventas.anular_venta(
        admin_user, anulada.pk, "Corrección"
    ).anulacion
    sesion.refresh_from_db()
    cierre = post(cajero, "caja_cerrar", datos_cierre(sesion, 90), sesion.pk).json()
    assert cierre["resumen"]["cantidad_anulada"] == 1
    detalle = reverse("detalle_venta", args=[venta.pk])
    assert "está cerrada" in cajero.get(detalle).content.decode()
    with pytest.raises(anulacion_ventas.ErrorAnulacion, match="está cerrada"):
        anulacion_ventas.anular_venta(admin_user, venta.pk, "Intento tardío")
    assert not Venta.objects.get(pk=venta.pk).cancelada
    repetida = anulacion_ventas.anular_venta(admin_user, anulada.pk, "Corrección")
    assert repetida.repetida and repetida.anulacion == anulacion

    siguiente = abrir(admin_user)
    reintento = registro_ventas.registrar_venta(admin_user, clave, datos)
    assert reintento.repetida and reintento.venta.pk == venta.pk
    assert reintento.venta.sesion_caja_id == sesion.pk
    assert not siguiente.ventas.exists()
    assert (
        caja.consultar_caja(admin_user)[0].version_resumen == siguiente.version_resumen
    )

    def no_recalcular(*args):
        pytest.fail("La lectura histórica debe usar la instantánea persistida.")

    monkeypatch.setattr(caja, "resumir_ventas", no_recalcular)
    url_cierre = reverse("caja_detalle_cierre", args=[sesion.pk])
    respuesta = cajero.get(url_cierre)
    assert respuesta.json() == {k: v for k, v in cierre.items() if k != "repetida"}
    assert "no-store" in respuesta["Cache-Control"]
    listado = cajero.get(reverse("caja_cierres")).json()
    assert [fila["id"] for fila in listado["cierres"]] == [sesion.pk]
    assert (
        cajero.get(reverse("caja_detalle_cierre", args=[siguiente.pk])).status_code
        == 404
    )
    with pytest.raises(ProtectedError):
        sesion.delete()


def test_historial_paginas_estables(admin_user, cajero, monkeypatch):
    monkeypatch.setattr(caja, "LIMITE_CIERRES", 2)
    cerradas = []
    for inicial in (10, 20, 30):
        sesion = abrir(admin_user, inicial)
        caja.cerrar_caja(
            admin_user, sesion.pk, str(uuid4()), datos_cierre(sesion, inicial)
        )
        cerradas.append(sesion.pk)
    abrir(admin_user)

    url = reverse("caja_cierres")
    primera = cajero.get(url).json()
    assert [cierre["id"] for cierre in primera["cierres"]] == cerradas[:0:-1]
    assert primera["antes_de"] == cerradas[1]
    segunda = cajero.get(url, {"antes_de": primera["antes_de"]}).json()
    assert [cierre["id"] for cierre in segunda["cierres"]] == cerradas[:1]
    assert segunda["antes_de"] is None
    for cursor in ("", "-1", "1.1", "9" * 20):
        assert cajero.get(url, {"antes_de": cursor}).status_code == 400


@pytest.mark.parametrize(
    "inicio,fin,local_inicio,local_fin",
    [
        (
            "2026-02-01T02:30:00+00:00",
            "2026-02-01T05:30:00+00:00",
            "2026-01-31T23:30:00-03:00",
            "2026-02-01T02:30:00-03:00",
        ),
        (
            "2026-04-05T02:30:00+00:00",
            "2026-04-05T04:15:00+00:00",
            "2026-04-04T23:30:00-03:00",
            "2026-04-05T00:15:00-04:00",
        ),
        (
            "2026-09-06T03:45:00+00:00",
            "2026-09-06T04:15:00+00:00",
            "2026-09-05T23:45:00-04:00",
            "2026-09-06T01:15:00-03:00",
        ),
    ],
)
def test_sesion_cruza_medianoche_y_cambios_de_hora(
    admin_user, cajero, monkeypatch, inicio, fin, local_inicio, local_fin
):
    monkeypatch.setattr(timezone, "now", lambda: datetime.fromisoformat(inicio))
    sesion = abrir(admin_user)
    monkeypatch.setattr(timezone, "now", lambda: datetime.fromisoformat(fin))
    venta = rapida(admin_user)
    assert venta.sesion_caja_id == sesion.pk
    sesion.refresh_from_db()
    cierre = post(cajero, "caja_cerrar", datos_cierre(sesion, 900), sesion.pk).json()
    assert cierre["abierta_en"] == local_inicio
    assert cierre["cerrada_en"] == local_fin


def test_permisos_csrf_metodos_y_superficies_de_escritura(
    cajero, admin_user, django_user_model
):
    call_command("crear_grupos_permisos", stdout=StringIO())
    administrador = django_user_model.objects.create_user("admin-caja")
    administrador.groups.add(Group.objects.get(name="Administrador"))
    vendedor = django_user_model.objects.create_user("vendedor-caja")
    vendedor.groups.add(Group.objects.get(name="Vendedor"))
    permisos = {
        caja.CONSULTAR_CAJA,
        caja.ABRIR_CAJA,
        caja.REGISTRAR_MOVIMIENTO,
        caja.CERRAR_CAJA,
        caja.CONSULTAR_CIERRES,
    }
    assert administrador.has_perms(permisos)
    assert permisos.isdisjoint(vendedor.get_all_permissions())
    segura = Client(enforce_csrf_checks=True)
    assert segura.get(reverse("caja_activa")).status_code == 302
    segura.force_login(administrador)
    url = reverse("caja_abrir")
    datos = {"efectivo_inicial": 0}
    assert segura.get(url).status_code == 405
    assert post(segura, "caja_abrir", datos).status_code == 403
    cabecera = {
        "X-CSRFToken": segura.get(reverse("caja_activa")).cookies["csrftoken"].value
    }
    respuesta = post(segura, "caja_abrir", datos, **cabecera)
    assert respuesta.status_code == 201
    pk = respuesta.json()["id"]
    sesion = SesionCaja.objects.get(pk=pk)
    datos_movimiento = {"tipo": "retiro", "importe": 1, "motivo": "Traslado"}
    assert post(segura, "caja_movimiento", datos_movimiento, pk).status_code == 403
    assert post(segura, "caja_cerrar", datos_cierre(sesion), pk).status_code == 403
    assert segura.get(reverse("caja_movimiento", args=[pk])).status_code == 405
    assert segura.get(reverse("caja_cerrar", args=[pk])).status_code == 405

    sin_permiso = Client()
    sin_permiso.force_login(vendedor)
    assert sin_permiso.get(reverse("caja_activa")).status_code == 403
    assert sin_permiso.get(reverse("caja_cierres")).status_code == 403
    assert sin_permiso.get(reverse("caja_detalle_cierre", args=[pk])).status_code == 403
    assert post(sin_permiso, "caja_abrir", datos).status_code == 403
    assert post(sin_permiso, "caja_movimiento", datos_movimiento, pk).status_code == 403
    assert post(sin_permiso, "caja_cerrar", datos_cierre(sesion), pk).status_code == 403
    with pytest.raises(PermissionDenied):
        caja.consultar_caja(vendedor)
    # Una delegación de consulta histórica no concede otras operaciones.
    vendedor.user_permissions.add(
        Permission.objects.get(codename="consultar_cierres_caja")
    )
    assert sin_permiso.get(reverse("caja_cierres")).status_code == 200
    assert sin_permiso.get(reverse("caja_activa")).status_code == 403

    for modelo in (SesionCaja, MovimientoCaja, BloqueoCaja):
        assert not admin.site.is_registered(modelo)
    assert cajero.get("/api/sesiones-caja/").status_code == 404
    assert not MovimientoCaja.objects.exists()


def test_json_estricto_y_totales_del_cliente(cajero, admin_user):
    for datos, estado in (
        ('{"efectivo_inicial":0,"efectivo_inicial":1}', 400),
        ('{"efectivo_inicial":NaN}', 400),
        ('{"efectivo_inicial":0,"abierta_por":1}', 400),
        ("x" * (16 * 1024 + 1), 413),
    ):
        assert post(cajero, "caja_abrir", datos).status_code == estado
    assert (
        cajero.post(reverse("caja_abrir"), {"efectivo_inicial": 0}).status_code == 415
    )
    assert (
        post(
            cajero, "caja_abrir", {"efectivo_inicial": 0}, clave="inválida"
        ).status_code
        == 400
    )
    sesion = abrir(admin_user)
    assert (
        post(
            cajero, "caja_cerrar", datos_cierre(sesion, efectivo_esperado=0), sesion.pk
        ).status_code
        == 400
    )


@pytest.mark.parametrize("operacion", ["venta", "anulacion", "movimiento", "cierre"])
def test_rollback_financiero(admin_user, monkeypatch, operacion):
    sesion = abrir(admin_user)
    venta = rapida(admin_user)
    sesion.refresh_from_db()
    version = sesion.version_resumen

    def abortar(*args, **kwargs):
        raise RuntimeError("Fallo después de escribir")

    if operacion == "cierre":
        guardar = SesionCaja.save

        def guardar_y_fallar(*args, **kwargs):
            guardar(*args, **kwargs)
            abortar()

        monkeypatch.setattr(SesionCaja, "save", guardar_y_fallar)

        def ejecutar():
            return caja.cerrar_caja(
                admin_user, sesion.pk, str(uuid4()), datos_cierre(sesion, 900)
            )

    else:
        modulo, ejecutar = {
            "venta": (registro_ventas, lambda: rapida(admin_user)),
            "anulacion": (
                anulacion_ventas,
                lambda: anulacion_ventas.anular_venta(
                    admin_user, venta.pk, "Duplicada"
                ),
            ),
            "movimiento": (caja, lambda: movimiento(admin_user, sesion)),
        }[operacion]
        invalidar = modulo.invalidar_resumen

        def invalidar_y_fallar(*args, **kwargs):
            invalidar(*args, **kwargs)
            abortar()

        monkeypatch.setattr(modulo, "invalidar_resumen", invalidar_y_fallar)

    with pytest.raises(RuntimeError, match="Fallo después de escribir"):
        ejecutar()
    sesion.refresh_from_db()
    assert sesion.version_resumen == version
    assert sesion.cerrada_en is None and sesion.resumen_cierre is None
    assert Venta.objects.count() == RegistroVenta.objects.count() == 1
    assert not Venta.objects.get(pk=venta.pk).cancelada
    assert not AnulacionVenta.objects.exists()
    assert not MovimientoCaja.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_migracion_0021_avance_reversion_y_reaplicacion(admin_user):
    anterior = [("inventario", "0020_anulacion_segura_ventas")]
    actual = [("inventario", "0021_nucleo_cierres_caja")]
    ejecutor = MigrationExecutor(connection)
    esquema_final = ejecutor.loader.graph.leaf_nodes()
    apps_anteriores = ejecutor.loader.project_state(anterior).apps
    Venta0020 = apps_anteriores.get_model("inventario", "Venta")
    Anulacion0020 = apps_anteriores.get_model("inventario", "AnulacionVenta")

    try:
        ejecutor.migrate(anterior)
        historica = Venta0020.objects.create(
            usuario_id=admin_user.pk,
            numero_venta="STK06-ANTERIOR",
            total=200,
            cancelada=True,
        )
        auditoria = Anulacion0020.objects.create(
            venta=historica, usuario_id=admin_user.pk, motivo="Conservar auditoría"
        )
        venta_guardada = Venta0020.objects.values().get(pk=historica.pk)
        anulacion_guardada = Anulacion0020.objects.values().get(pk=auditoria.pk)
        MigrationExecutor(connection).migrate(actual)
        assert Venta.objects.values().get(pk=historica.pk) == {
            **venta_guardada,
            "sesion_caja_id": None,
        }
        assert (
            AnulacionVenta.objects.values().get(pk=auditoria.pk) == anulacion_guardada
        )
        assert BloqueoCaja.objects.filter(pk=1).exists()
        permisos = Group.objects.get(name="Administrador").permissions
        assert permisos.filter(content_type__model="sesioncaja").count() == 5

        MigrationExecutor(connection).migrate(esquema_final)
        sesion = abrir(admin_user)
        nueva = rapida(admin_user)
        movimiento(admin_user, sesion)
        sesion.refresh_from_db()
        caja.cerrar_caja(
            admin_user, sesion.pk, str(uuid4()), datos_cierre(sesion, 1000)
        )
        MigrationExecutor(connection).migrate(anterior)
        assert Venta0020.objects.values().get(pk=historica.pk) == venta_guardada
        assert Venta0020.objects.get(pk=nueva.pk).total == 900
        assert Anulacion0020.objects.values().get(pk=auditoria.pk) == anulacion_guardada
        assert not permisos.filter(content_type__model="sesioncaja").exists()
        assert SesionCaja._meta.db_table not in connection.introspection.table_names()
        MigrationExecutor(connection).migrate(actual)
        assert not SesionCaja.objects.exists()
        assert not MovimientoCaja.objects.exists()
        assert not Venta.objects.filter(sesion_caja__isnull=False).exists()
        assert (
            AnulacionVenta.objects.values().get(pk=auditoria.pk) == anulacion_guardada
        )
    finally:
        MigrationExecutor(connection).migrate(esquema_final)

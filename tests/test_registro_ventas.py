from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from threading import Barrier, Event
from uuid import uuid4

import pytest
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.db import IntegrityError, connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.middleware.csrf import get_token
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from inventario.models import (
    Cliente,
    CuentaPorCobrar,
    ItemVenta,
    MovimientoStock,
    Producto,
    RegistroVenta,
    Venta,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def vendedor(django_user_model):
    call_command("crear_grupos_permisos", stdout=StringIO())
    usuario = django_user_model.objects.create_user("vendedor-pos")
    usuario.groups.add(Group.objects.get(name="Vendedor"))
    return usuario


@pytest.fixture
def pos(client, vendedor):
    client.force_login(vendedor)
    return client


def rapida(**campos):
    return {"modalidad": "rapida", "metodo_pago": "efectivo", "monto": 900, **campos}


def linea(producto, **campos):
    return {
        "producto_id": producto.pk,
        "cantidad": 1,
        "precio_visto": int(producto.precio),
        **campos,
    }


def detallada(*items, **campos):
    return {
        "modalidad": "detallada",
        "metodo_pago": "transferencia",
        "items": list(items),
        **campos,
    }


def enviar(client, datos, *, clave=None, **headers):
    headers.setdefault("Idempotency-Key", str(uuid4()) if clave is None else clave)
    return client.post(
        reverse("registrar_venta_pos"),
        datos,
        content_type="application/json",
        headers=headers,
    )


def test_venta_rapida_sin_cliente_productos_ni_movimientos(pos, vendedor):
    antes = timezone.now()
    respuesta = enviar(pos, rapida())
    assert respuesta.status_code == 201
    resultado = respuesta.json()
    venta = Venta.objects.get()
    assert resultado == {
        "id": venta.pk,
        "numero_venta": venta.numero_venta,
        "modalidad": "rapida",
        "usuario_id": vendedor.pk,
        "fecha": resultado["fecha"],
        "subtotal": 900,
        "total": 900,
        "metodo_pago": "efectivo",
        "monto_recibido": 900,
        "cambio": 0,
        "items": [],
        "repetida": False,
    }
    assert antes <= venta.fecha <= timezone.now()
    assert (
        abs((venta.fecha - parse_datetime(resultado["fecha"])).total_seconds()) < 0.001
    )
    assert venta.cliente is None and not venta.es_credito
    assert not ItemVenta.objects.exists()
    assert not Producto.objects.exists()
    assert not MovimientoStock.objects.exists()
    assert not CuentaPorCobrar.objects.exists()


@pytest.mark.parametrize("varios", [False, True])
def test_detallada_conserva_precio_base_nombre_y_stock(pos, producto, varios):
    Producto.objects.filter(pk=producto.pk).update(stock=0, precio=1, precio_promo=99)
    producto.refresh_from_db()
    items = [linea(producto, cantidad=3)]
    otro = Producto.objects.create(nombre="Otro", precio=900, precio_promo=200, stock=4)
    if varios:
        items.insert(0, linea(otro, cantidad=2))
    respuesta = enviar(pos, detallada(*items))
    assert respuesta.status_code == 201
    resultado = respuesta.json()
    assert resultado["modalidad"] == "detallada"
    assert resultado["total"] == (1803 if varios else 3)
    assert resultado["monto_recibido"] == resultado["total"]
    assert resultado["cambio"] == 0
    assert len(resultado["items"]) == (2 if varios else 1)
    assert resultado["items"][0] == {
        "producto_id": producto.pk,
        "nombre_producto": producto.nombre,
        "cantidad": 3,
        "precio_unitario": 1,
        "subtotal": 3,
    }
    assert set(ItemVenta.objects.values_list("stock_anterior", "stock_despues")) == {
        (None, None)
    }
    assert Venta.objects.get().descuento == 0
    assert set(Producto.objects.values_list("pk", "stock")) == {
        (producto.pk, 0),
        (otro.pk, 4),
    }
    assert not MovimientoStock.objects.exists()


def test_precios_manipulados_y_cambios_exigen_confirmacion(pos, producto):
    precio_visto = linea(producto)
    alterada = enviar(pos, detallada(linea(producto, precio_visto=1)))
    assert alterada.status_code == 409
    assert alterada.json()["productos"] == [
        {"producto_id": producto.pk, "precio_vigente": 10000}
    ]
    Producto.objects.filter(pk=producto.pk).update(precio=17000)
    clave = str(uuid4())
    cambio = enviar(pos, detallada(precio_visto), clave=clave)
    assert cambio.status_code == 409
    assert cambio.json()["error"] == "precio_cambiado"
    assert cambio.json()["productos"] == [
        {"producto_id": producto.pk, "precio_vigente": 17000}
    ]
    assert not Venta.objects.exists()
    assert not RegistroVenta.objects.exists()
    confirmada = enviar(
        pos, detallada(linea(producto, precio_visto=17000)), clave=clave
    )
    assert confirmada.status_code == 201
    assert confirmada.json()["total"] == 17000


def test_productos_duplicados_inactivos_e_inexistentes(pos, producto):
    duplicada = enviar(pos, detallada(linea(producto), linea(producto, cantidad=2)))
    assert duplicada.status_code == 400
    assert duplicada.json()["error"] == "producto_duplicado"
    Producto.objects.filter(pk=producto.pk).update(activo=False)
    inexistente = producto.pk + 10
    indisponible = enviar(
        pos, detallada(linea(producto), linea(producto, producto_id=inexistente))
    )
    assert indisponible.status_code == 409
    assert indisponible.json()["producto_ids"] == [producto.pk, inexistente]
    assert not Venta.objects.exists()


@pytest.mark.parametrize(
    "cantidad", [True, False, 0, -1, "2", 1.5, 2.0, None, [], 1_000_001]
)
def test_cantidades_invalidas(pos, producto, cantidad):
    respuesta = enviar(pos, detallada(linea(producto, cantidad=cantidad)))
    assert respuesta.status_code == 400
    assert respuesta.json()["campo"] == "cantidad"
    assert not Venta.objects.exists()


@pytest.mark.parametrize(
    "monto", [True, False, 0, -1, "200", 2.0, 0.5, None, {}, 10**12, 10**25]
)
def test_importes_invalidos(pos, monto):
    for datos in (rapida(monto=monto), rapida(monto_recibido=monto)):
        respuesta = enviar(pos, datos)
        assert respuesta.status_code == 400
        assert respuesta.json()["error"] == "entero_invalido"
    assert not RegistroVenta.objects.exists()
    assert not Venta.objects.exists()


def test_limites_de_clp_productos_items_y_payload(pos, producto):
    assert enviar(pos, rapida(monto=999_999_999_999)).status_code == 201
    assert (
        enviar(pos, detallada(linea(producto, producto_id=2**63))).json()["campo"]
        == "producto_id"
    )
    assert (
        enviar(pos, detallada(linea(producto, precio_visto="1"))).json()["campo"]
        == "precio_visto"
    )
    assert (
        enviar(pos, detallada(*[linea(producto)] * 101)).json()["error"]
        == "items_invalidos"
    )
    Producto.objects.filter(pk=producto.pk).update(precio=9_999_999_999)
    producto.refresh_from_db()
    respuesta = enviar(pos, detallada(linea(producto, cantidad=2)))
    assert respuesta.status_code == 400 and respuesta.json()["campo"] == "subtotal_item"
    assert enviar(pos, b" " * 16385).status_code == 413
    assert Venta.objects.count() == 1


@pytest.mark.parametrize(
    "payload", [b'{"monto":1,"monto":2}', b"{", b"NaN", b"\xff", b"[" * 2000]
)
def test_json_invalido(pos, payload):
    respuesta = enviar(pos, payload)
    assert respuesta.status_code == 400 and respuesta.json()["error"] == "json_invalido"
    assert not Venta.objects.exists()


@pytest.mark.parametrize("metodo", ["credito", "mixto", "cheque", "", None, {}])
def test_metodos_de_pago_excluidos(pos, metodo):
    respuesta = enviar(pos, rapida(metodo_pago=metodo))
    assert respuesta.status_code == 400
    assert respuesta.json()["error"] == "metodo_pago_invalido"
    assert not Venta.objects.exists()


def test_pago_en_efectivo_calcula_vuelto_y_rechaza_importe_insuficiente(pos):
    assert (
        enviar(pos, rapida(monto_recibido=899)).json()["error"]
        == "efectivo_insuficiente"
    )
    resultado = enviar(pos, rapida(monto_recibido=1000)).json()
    assert (resultado["monto_recibido"], resultado["cambio"]) == (1000, 100)
    assert Venta.objects.get().cambio == 100


@pytest.mark.parametrize("metodo", ["tarjeta", "transferencia"])
def test_tarjeta_transferencia_importe_exacto_y_sin_vuelto(pos, metodo):
    for monto in (899, 901):
        respuesta = enviar(pos, rapida(metodo_pago=metodo, monto_recibido=monto))
        assert (
            respuesta.status_code == 400
            and respuesta.json()["error"] == "monto_pago_inexacto"
        )
    for campos in ({}, {"monto_recibido": 900}):
        respuesta = enviar(pos, rapida(metodo_pago=metodo, **campos))
        assert respuesta.status_code == 201
        assert (respuesta.json()["monto_recibido"], respuesta.json()["cambio"]) == (
            900,
            0,
        )


def test_idempotencia_recupera_snapshot_y_acepta_claves_distintas(pos, producto):
    otro = Producto.objects.create(nombre="Otro", precio=100)
    items = (linea(producto), linea(otro))
    clave = str(uuid4())
    original = enviar(pos, detallada(*items), clave=clave)
    assert original.status_code == 201
    Producto.objects.filter(pk=producto.pk).update(
        precio=99, nombre="Editado", activo=False
    )
    repetida = enviar(pos, detallada(*reversed(items)), clave=clave.upper())
    assert repetida.status_code == 200
    assert repetida.json() == {**original.json(), "repetida": True}
    conflicto = enviar(
        pos, detallada(linea(producto, precio_visto=99), items[1]), clave=clave
    )
    assert (
        conflicto.status_code == 409
        and conflicto.json()["error"] == "clave_en_conflicto"
    )
    assert enviar(pos, rapida()).status_code == 201
    assert enviar(pos, rapida()).status_code == 201
    assert Venta.objects.count() == RegistroVenta.objects.count() == 3
    assert ItemVenta.objects.count() == 2


def test_idempotencia_separa_vendedores(pos, admin_user):
    clave = str(uuid4())
    primera = enviar(pos, rapida(), clave=clave)
    pos.force_login(admin_user)
    segunda = enviar(pos, rapida(monto=1000), clave=clave)
    assert primera.status_code == segunda.status_code == 201
    assert primera.json()["usuario_id"] != segunda.json()["usuario_id"]
    assert primera.json()["numero_venta"] != segunda.json()["numero_venta"]


def test_rollback_despues_de_insertar_un_item(pos, producto, monkeypatch):
    otro = Producto.objects.create(nombre="Otro", precio=100)
    crear_items = ItemVenta.objects.bulk_create
    clave = str(uuid4())
    datos = detallada(linea(producto), linea(otro))

    def fallo(items):
        crear_items(items[:1])
        raise IntegrityError("Fallo inducido después del primer ítem")

    with monkeypatch.context() as m:
        m.setattr(ItemVenta.objects, "bulk_create", fallo)
        with pytest.raises(IntegrityError, match="Fallo inducido"):
            enviar(pos, datos, clave=clave)
    for modelo in (Venta, ItemVenta, RegistroVenta, MovimientoStock):
        assert not modelo.objects.exists()
    assert enviar(pos, datos, clave=clave).status_code == 201
    assert ItemVenta.objects.count() == 2


def test_endpoint_permisos_post_csrf_y_tipo_de_contenido(vendedor, normal_user):
    client = Client(enforce_csrf_checks=True)
    ruta = reverse("registrar_venta_pos")
    solicitud = RequestFactory().get(ruta)
    token = get_token(solicitud)
    client.cookies["csrftoken"] = solicitud.META["CSRF_COOKIE"]
    headers = {"X-CSRFToken": token}
    assert enviar(client, rapida(), **headers).status_code == 302
    normal_user.user_permissions.add(Permission.objects.get(codename="add_venta"))
    client.force_login(normal_user)
    assert enviar(client, rapida(), **headers).status_code == 403
    client.force_login(vendedor)
    assert client.get(ruta).status_code == 405
    assert enviar(client, rapida()).status_code == 403
    assert client.post(ruta, {"monto": 900}, headers=headers).status_code == 415
    assert enviar(client, rapida(), clave="", **headers).status_code == 400
    assert not Venta.objects.exists()
    assert enviar(client, rapida(), **headers).status_code == 201


@pytest.mark.parametrize(
    "campo", ["usuario_id", "usuario", "fecha", "total", "descuento", "cambio"]
)
def test_campos_de_servidor_no_se_pueden_imponer(pos, campo):
    respuesta = enviar(pos, rapida(**{campo: 123}))
    assert (
        respuesta.status_code == 400 and respuesta.json()["error"] == "campos_invalidos"
    )
    assert not Venta.objects.exists()


def test_ventas_historicas_y_relaciones_se_conservan(
    client, admin_user, vendedor, producto
):
    cliente = Cliente.objects.create(nombre="Cliente histórico")
    historica = Venta.objects.create(
        numero_venta="V-20240101000000",
        usuario=vendedor,
        cliente=cliente,
        total=91,
        subtotal=100,
        descuento=9,
        metodo_pago="credito",
        es_credito=True,
    )
    item = ItemVenta.objects.create(
        venta=historica,
        producto=producto,
        nombre_producto="Nombre histórico",
        precio_unitario=50,
        cantidad=2,
        stock_anterior=8,
        stock_despues=6,
    )
    client.force_login(admin_user)
    assert enviar(client, rapida()).status_code == 201
    assert (
        client.delete(reverse("api:producto-detail", args=[producto.pk])).status_code
        == 409
    )
    client.post(reverse("eliminar_producto", args=[producto.pk]))
    client.post(
        reverse("admin:inventario_producto_delete", args=[producto.pk]), {"post": "yes"}
    )
    client.post(
        reverse("admin:inventario_cliente_delete", args=[cliente.pk]), {"post": "yes"}
    )
    historica.refresh_from_db()
    item.refresh_from_db()
    assert historica.modalidad is None
    assert (historica.total, historica.descuento, historica.metodo_pago) == (
        91,
        9,
        "credito",
    )
    assert (historica.usuario_id, historica.cliente_id) == (vendedor.pk, cliente.pk)
    assert (item.producto_id, item.nombre_producto, item.precio_unitario) == (
        producto.pk,
        "Nombre histórico",
        50,
    )
    assert (item.stock_anterior, item.stock_despues) == (8, 6)
    assert (
        client.get(reverse("api:venta-detail", args=[historica.pk])).json()["total"]
        == "91"
    )
    assert client.get(reverse("detalle_venta", args=[historica.pk])).status_code == 200


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("escenario", ["distintas", "misma", "conflicto"])
def test_concurrencia_de_registro_real_en_postgresql(vendedor, producto, escenario):
    if connection.vendor != "postgresql":
        pytest.skip("Requiere PostgreSQL y dos conexiones independientes.")
    simultaneas = Barrier(2, timeout=10)
    primera = str(uuid4())
    segunda = str(uuid4()) if escenario == "distintas" else primera

    def esperar_escrituras(execute, sql, params, many, context):
        if sql.startswith('INSERT INTO "inventario_registroventa"'):
            simultaneas.wait()
        return execute(sql, params, many, context)

    def solicitud(clave, cantidad):
        try:
            client = Client()
            client.force_login(vendedor)
            with connection.execute_wrapper(esperar_escrituras):
                return enviar(
                    client, detallada(linea(producto, cantidad=cantidad)), clave=clave
                )
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        tareas = [
            pool.submit(solicitud, primera, 1),
            pool.submit(solicitud, segunda, 2 if escenario == "conflicto" else 1),
        ]
        respuestas = [tarea.result(timeout=20) for tarea in tareas]

    estados = sorted(respuesta.status_code for respuesta in respuestas)
    if escenario == "distintas":
        assert estados == [201, 201]
        assert len({respuesta.json()["numero_venta"] for respuesta in respuestas}) == 2
        assert (
            Venta.objects.count()
            == RegistroVenta.objects.count()
            == ItemVenta.objects.count()
            == 2
        )
    else:
        assert (
            Venta.objects.count()
            == RegistroVenta.objects.count()
            == ItemVenta.objects.count()
            == 1
        )
        if escenario == "misma":
            assert estados == [200, 201]
            assert len({respuesta.json()["id"] for respuesta in respuestas}) == 1
        else:
            assert estados == [201, 409]
            assert (
                next(r for r in respuestas if r.status_code == 409).json()["error"]
                == "clave_en_conflicto"
            )
    producto.refresh_from_db()
    assert producto.stock == 50
    assert not MovimientoStock.objects.exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "cambio,error",
    [
        ({"precio": 12000}, "precio_cambiado"),
        ({"activo": False}, "productos_no_disponibles"),
    ],
)
def test_registro_observa_cambio_concurrente_de_catalogo_en_postgresql(
    vendedor, producto, cambio, error
):
    if connection.vendor != "postgresql":
        pytest.skip("Requiere bloqueos de fila de PostgreSQL.")
    lee_producto = Event()

    def vigilar_bloqueo(execute, sql, params, many, context):
        if 'FROM "inventario_producto"' in sql and "FOR UPDATE" in sql:
            lee_producto.set()
        return execute(sql, params, many, context)

    def solicitud():
        try:
            client = Client()
            client.force_login(vendedor)
            with connection.execute_wrapper(vigilar_bloqueo):
                return enviar(client, detallada(linea(producto)))
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            Producto.objects.filter(pk=producto.pk).update(**cambio)
            tarea = pool.submit(solicitud)
            assert lee_producto.wait(timeout=10)
            assert not tarea.done()
        respuesta = tarea.result(timeout=10)
    assert respuesta.status_code == 409 and respuesta.json()["error"] == error
    assert not Venta.objects.exists()
    assert not RegistroVenta.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_migracion_avance_y_reversion_con_ventas(client, admin_user, producto):
    anterior = [("inventario", "0017_proteger_cuentas_por_cobrar")]
    nueva = [("inventario", "0018_nucleo_seguro_ventas")]
    migracion = MigrationExecutor(connection)
    esquema_inicial = migracion.loader.graph.leaf_nodes()
    apps_anteriores = migracion.loader.project_state(anterior).apps
    VentaAnterior = apps_anteriores.get_model("inventario", "Venta")
    ItemAnterior = apps_anteriores.get_model("inventario", "ItemVenta")

    try:
        migracion.migrate(anterior)
        historica = VentaAnterior.objects.create(
            usuario_id=admin_user.pk,
            numero_venta="HISTORICA",
            subtotal=100,
            total=91,
            descuento=9,
        )
        ItemAnterior.objects.create(
            venta=historica,
            producto_id=producto.pk,
            nombre_producto="Histórico",
            precio_unitario=100,
            subtotal=100,
            stock_anterior=4,
            stock_despues=3,
        )
        venta_guardada = VentaAnterior.objects.values().get(pk=historica.pk)
        item_guardado = ItemAnterior.objects.values().get(venta=historica)

        MigrationExecutor(connection).migrate(nueva)
        assert Venta.objects.values().get(pk=historica.pk) == {
            **venta_guardada,
            "modalidad": None,
        }
        assert ItemVenta.objects.values().get(venta_id=historica.pk) == item_guardado
        client.force_login(admin_user)
        respuesta = enviar(client, detallada(linea(producto)))
        assert respuesta.status_code == 201
        nueva_id = respuesta.json()["id"]

        MigrationExecutor(connection).migrate(anterior)
        assert VentaAnterior.objects.values().get(pk=historica.pk) == venta_guardada
        assert ItemAnterior.objects.values().get(venta=historica) == item_guardado
        assert VentaAnterior.objects.get(pk=nueva_id).total == producto.precio
        assert ItemAnterior.objects.values_list("stock_anterior", "stock_despues").get(
            venta_id=nueva_id
        ) == (0, 0)
    finally:
        MigrationExecutor(connection).migrate(esquema_inicial)

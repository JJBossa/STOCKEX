import json
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO, StringIO
from threading import Barrier
from time import perf_counter
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection, connections
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from openpyxl import Workbook

from inventario import lectura_productos_excel as lector
from inventario.importacion_productos import ConflictoImportacion, importar, planificar
from inventario.models import Categoria, HistorialPrecio, MovimientoStock, Producto


def archivo_excel(filas, *, hoja="Productos", columnas=lector.COLUMNAS, mascara=False):
    libro = Workbook()
    productos = libro.active
    productos.title = hoja
    productos.append(columnas)
    for fila in filas:
        productos.append(fila)
    if mascara:
        productos["A2"].number_format = "000000"
    libro.create_sheet("Ignorada").append(["No es parte del catálogo"])
    destino = BytesIO()
    libro.save(destino)
    return destino.getvalue()


def cambiar_parte(data, nombre, transformar):
    destino = BytesIO()
    with (
        ZipFile(BytesIO(data)) as original,
        ZipFile(destino, "w", ZIP_DEFLATED) as nuevo,
    ):
        for ruta in original.namelist():
            contenido = original.read(ruta)
            nuevo.writestr(
                ruta, transformar(contenido) if ruta == nombre else contenido
            )
    return destino.getvalue()


def leer(data, nombre="sintetico.xlsx"):
    return lector.leer_excel(BytesIO(data), nombre)


def enviar(client, data, *, token=None, csrf=None, accion="previsualizar"):
    campos = {
        "archivo": SimpleUploadedFile("sintetico.xlsx", data),
        "accion": accion,
    }
    if token is not None:
        campos["vista_previa"] = token
    if csrf is not None:
        campos["csrfmiddlewaretoken"] = csrf
    return client.post(reverse("importar_productos_excel"), campos)


@pytest.mark.django_db
@pytest.mark.parametrize("extension", ["xlsx", "xlsm"])
def test_importa_formatos_y_conserva_datos(extension):
    columnas = (*lector.COLUMNAS, "Precio Compra", "Stock", "Valor Inventario")
    data = archivo_excel(
        [
            ("000015", " Bebida limón ", "Bebidas", 1, 99, 80, 700),
            ("A-02", "Agua", "bebidas", 550, 80, 4, 400),
            ("A-03", "Jugo", None, 560, 80, 0, 0),
        ],
        columnas=columnas,
    )
    if extension == "xlsm":
        data = cambiar_parte(
            data,
            "[Content_Types].xml",
            lambda xml: xml.replace(
                b"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
                b"application/vnd.ms-excel.sheet.macroEnabled.main+xml",
            ),
        )
    catalogo = leer(data, f"sintetico.{extension}")
    plan = planificar(catalogo)
    assert (plan.resumen.validas, plan.resumen.nuevos, plan.resumen.sin_categoria) == (
        3,
        3,
        1,
    )
    assert [fila.sku for fila in plan.resumen.precio_un_peso] == ["000015"]
    assert not Producto.objects.exists()
    assert not Categoria.objects.exists()

    assert importar(catalogo, version=plan.version).nuevos == 3
    valores = Producto.objects.order_by("sku").values_list(
        "sku",
        "nombre",
        "categoria__nombre",
        "precio",
        "precio_compra",
        "stock",
        "activo",
    )
    assert list(valores) == [
        ("000015", " Bebida limón ", "Bebidas", 1, 0, 0, True),
        ("A-02", "Agua", "bebidas", 550, 0, 0, True),
        ("A-03", "Jugo", None, 560, 0, 0, True),
    ]
    assert Categoria.objects.count() == 2
    assert importar(catalogo, version=plan.version).sin_cambios == 3
    assert HistorialPrecio.objects.count() == 3
    assert not MovimientoStock.objects.exists()


def test_sku_numerico_con_mascara_y_formula_con_cache():
    data = archivo_excel([(7, "Bebida", "Bebidas", "=500+1")], mascara=True)

    def guardar_cache(xml):
        arbol = ElementTree.fromstring(xml)
        arbol.find(".//{*}c[@r='D2']/{*}v").text = "501"
        return ElementTree.tostring(arbol)

    data = cambiar_parte(data, "xl/worksheets/sheet1.xml", guardar_cache)
    catalogo = leer(data)
    assert not catalogo.errores
    assert (catalogo.filas[0].sku, catalogo.filas[0].precio) == ("000007", 501)


def test_precision_decimal_del_xml():
    data = archivo_excel([("001", "Producto", None, 1)])
    data = cambiar_parte(
        data,
        "xl/worksheets/sheet1.xml",
        lambda xml: xml.replace(b"<v>1</v>", b"<v>1.00000000000000001</v>"),
    )
    assert leer(data).errores == (
        lector.ErrorFila(
            2, "Precio: se requiere un entero positivo de hasta 10 dígitos, en CLP."
        ),
    )


@pytest.mark.parametrize("precio", [None, 0, -1, 1.25, "NaN", "$100", True, 10**10])
def test_rechaza_precio_invalido(precio):
    catalogo = leer(archivo_excel([("SKU-1", "Producto", None, precio)]))
    assert not catalogo.filas
    assert catalogo.errores[0].fila == 2
    assert "Precio" in catalogo.errores[0].motivo


@pytest.mark.parametrize(
    ("fila", "campo"),
    [
        ((" ", "Producto", None, 1), "SKU"),
        (("A", " ", None, 1), "Nombre"),
        (("S" * 51, "Producto", None, 1), "SKU"),
        (("A", "N" * 201, None, 1), "Nombre"),
        (("A", "Producto", "C" * 101, 1), "Categoría"),
        (("A", "Producto", None, "=1+1"), "fórmula sin valor"),
        (("A", "Producto", '=""', 1), "fórmula sin valor"),
    ],
)
def test_rechaza_campos_invalidos(fila, campo):
    catalogo = leer(archivo_excel([fila]))
    assert not catalogo.filas
    assert catalogo.errores[0].fila == 2
    assert campo in catalogo.errores[0].motivo


def test_sku_duplicado_se_marca_en_ambas_filas():
    catalogo = leer(archivo_excel([("001", "P1", None, 1), ("001", "P2", None, 2)]))
    assert not catalogo.filas
    assert [error.fila for error in catalogo.errores] == [2, 3]
    assert all("duplicado" in error.motivo for error in catalogo.errores)


def test_archivo_malformado_y_estructura_requerida():
    with pytest.raises(lector.ExcelInvalido, match="corrupto"):
        leer(b"archivo corrupto")
    with pytest.raises(lector.ExcelInvalido, match="hoja Productos"):
        leer(archivo_excel([], hoja="Otra"))
    with pytest.raises(lector.ExcelInvalido, match="faltan columnas.*Precio"):
        leer(archivo_excel([], columnas=lector.COLUMNAS[:-1]))
    with pytest.raises(lector.ExcelInvalido, match="xlsx o .xlsm"):
        leer(b"x", "archivo.xls")


def test_limites_de_archivo_y_xml(monkeypatch):
    data = archivo_excel([("A", "A", None, 1), ("B", "B", None, 2)])
    dtd = cambiar_parte(
        data, "xl/worksheets/sheet1.xml", lambda xml: b"<!DOCTYPE worksheet>" + xml
    )
    with pytest.raises(lector.ExcelInvalido, match="declaraciones XML"):
        leer(dtd)
    with monkeypatch.context() as cambios:
        cambios.setattr(lector, "MAX_ARCHIVO", len(data) - 1)
        with pytest.raises(lector.ExcelInvalido, match="5 MiB"):
            leer(data)
    with monkeypatch.context() as cambios:
        cambios.setattr(lector, "MAX_DESCOMPRIMIDO", 100)
        with pytest.raises(lector.ExcelInvalido, match="descompresión"):
            leer(data)
    monkeypatch.setattr(lector, "MAX_FILAS", 1)
    with pytest.raises(lector.ExcelInvalido, match="filas"):
        leer(data)


@pytest.mark.django_db
def test_actualiza_por_sku_y_preserva_campos(monkeypatch, producto):
    Producto.objects.filter(pk=producto.pk).update(
        stock=12, precio_compra=200, activo=False, imagen="productos/prueba.jpg"
    )
    ausente = Producto.objects.create(sku="NO-INCLUIDO", nombre="Otro", precio=10)

    def no_optimizar(_):
        pytest.fail("El importador no debe modificar archivos de imagen")

    monkeypatch.setattr(Producto, "optimizar_imagen", no_optimizar)
    catalogo = leer(archivo_excel([(producto.sku, "Nuevo nombre", None, 170)]))
    resultado = importar(catalogo)
    producto.refresh_from_db()
    assert resultado.actualizados == 1
    assert (producto.nombre, producto.precio, producto.categoria_id) == (
        "Nuevo nombre",
        170,
        None,
    )
    assert (producto.stock, producto.precio_compra, producto.activo) == (12, 200, False)
    assert producto.imagen.name == "productos/prueba.jpg"
    assert Producto.objects.filter(pk=ausente.pk, precio=10).exists()
    assert (
        HistorialPrecio.objects.filter(producto=producto, precio_nuevo=170).count() == 1
    )


@pytest.mark.django_db
def test_rollback_en_error_de_persistencia(monkeypatch, producto):
    catalogo = leer(
        archivo_excel(
            [
                (producto.sku, "Actualizado", "Nueva", 900),
                ("nuevo", "Producto nuevo", "Nueva", 200),
            ]
        )
    )
    guardar = Producto.save

    def guardar_con_error(self, *args, **kwargs):
        guardar(self, *args, **kwargs)
        if self.sku == "nuevo":
            raise IntegrityError("fallo sintético")

    monkeypatch.setattr(Producto, "save", guardar_con_error)
    historial = HistorialPrecio.objects.count()
    with pytest.raises(ConflictoImportacion, match="integridad"):
        importar(catalogo)
    assert not Categoria.objects.filter(nombre="Nueva").exists()
    assert Producto.objects.count() == 1
    assert Producto.objects.get(pk=producto.pk).nombre == producto.nombre
    assert HistorialPrecio.objects.count() == historial


@pytest.mark.django_db(transaction=True)
def test_catalogo_531_productos_y_consultas():
    filas = [
        (f"{i:06}", f"Producto {i}", f"Categoría {i % 25}", i + 1) for i in range(531)
    ]
    data = archivo_excel(filas)
    inicio = perf_counter()
    with CaptureQueriesContext(connection) as consultas:
        catalogo = leer(data)
        previo = planificar(catalogo)
        assert previo.resumen.nuevos == 531
        assert importar(catalogo, version=previo.version).nuevos == 531
    print(
        f"{connection.vendor} 531 nuevos: {perf_counter() - inicio:.3f} s, {len(consultas)} SQL"
    )
    assert len(consultas) <= 2 * 531 + 12
    assert Producto.objects.count() == HistorialPrecio.objects.count() == 531
    assert Categoria.objects.count() == 25

    inicio = perf_counter()
    with CaptureQueriesContext(connection) as consultas:
        assert importar(leer(data)).sin_cambios == 531
    print(
        f"{connection.vendor} 531 sin cambios: {perf_counter() - inicio:.3f} s, {len(consultas)} SQL"
    )
    assert len(consultas) <= 7
    assert HistorialPrecio.objects.count() == 531
    assert not MovimientoStock.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_importaciones_concurrentes_repetidas():
    catalogo = leer(archivo_excel([("SKU", "Producto", "Categoría", 500)]))
    version = planificar(catalogo).version
    barrera = Barrier(2)

    def ejecutar():
        try:
            barrera.wait(timeout=10)
            return importar(catalogo, version=version).nuevos
        except ConflictoImportacion as error:
            return str(error)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as grupo:
        resultados = list(grupo.map(lambda _: ejecutar(), range(2)))
    assert resultados.count(1) == 1
    segundo = next(resultado for resultado in resultados if resultado != 1)
    assert segundo == 0 or (connection.vendor == "sqlite" and "ocupado" in segundo)
    assert importar(catalogo, version=version).sin_cambios == 1
    assert (
        Producto.objects.count()
        == Categoria.objects.count()
        == HistorialPrecio.objects.count()
        == 1
    )


@pytest.mark.django_db
def test_web_permiso_csrf_y_archivo_temporal(
    settings, tmp_path, admin_user, normal_user
):
    settings.FILE_UPLOAD_MAX_MEMORY_SIZE = 1
    settings.FILE_UPLOAD_TEMP_DIR = str(tmp_path)
    data = archivo_excel([("0001", "P", None, 1)])
    client = Client(enforce_csrf_checks=True)
    url = reverse("importar_productos_excel")
    assert client.get(url).status_code == 302
    client.force_login(normal_user)
    assert enviar(client, data).status_code == 403
    client.force_login(admin_user)
    assert client.get(url).status_code == 200
    csrf = client.cookies["csrftoken"].value
    assert enviar(client, data).status_code == 403
    previo = enviar(client, data, csrf=csrf)
    assert previo.status_code == 200
    assert previo.context["resumen"].nuevos == 1
    assert not Producto.objects.exists()
    assert not Categoria.objects.exists()
    assert not HistorialPrecio.objects.exists()
    token = previo.context["vista_previa"]

    assert enviar(client, data, token=token, accion="confirmar").status_code == 403
    final = enviar(client, data, token=token, csrf=csrf, accion="confirmar")
    assert final.status_code == 200 and final.context["importado"]
    repetida = enviar(client, data, token=token, csrf=csrf, accion="confirmar")
    assert repetida.status_code == 200
    assert repetida.context["resumen"].sin_cambios == 1
    assert Producto.objects.count() == HistorialPrecio.objects.count() == 1
    assert list(tmp_path.iterdir()) == []


@pytest.mark.django_db
def test_administrador_de_grupo_necesita_permisos(client, normal_user):
    call_command("crear_grupos_permisos", stdout=StringIO())
    grupo = Group.objects.get(name="Administrador")
    normal_user.groups.add(grupo)
    client.force_login(normal_user)
    assert client.get(reverse("importar_productos_excel")).status_code == 200
    grupo.permissions.remove(grupo.permissions.get(codename="change_producto"))
    assert client.get(reverse("importar_productos_excel")).status_code == 403


@pytest.mark.django_db
def test_web_validacion_y_conflicto_despues_de_previsualizar(
    client, admin_user, producto
):
    client.force_login(admin_user)
    data = archivo_excel([(producto.sku, producto.nombre, None, 91)])
    token = enviar(client, data).context["vista_previa"]
    assert enviar(client, data, accion="confirmar").status_code == 409
    distinto = archivo_excel([(producto.sku, producto.nombre, None, 92)])
    assert enviar(client, distinto, token=token, accion="confirmar").status_code == 409
    Producto.objects.filter(pk=producto.pk).update(precio=300)
    conflicto = enviar(client, data, token=token, accion="confirmar")
    assert conflicto.status_code == 409
    assert "catálogo cambió" in conflicto.context["error"]
    assert Producto.objects.get(pk=producto.pk).precio == 300


@pytest.mark.django_db
def test_web_no_confirma_filas_invalidas_y_limita_carga(
    client, admin_user, monkeypatch
):
    client.force_login(admin_user)
    data = archivo_excel([("sku", "Nombre", None, 0)])
    previo = enviar(client, data)
    assert previo.status_code == 200
    assert previo.context["resumen"].errores[0].fila == 2
    assert "vista_previa" not in previo.context
    assert not Producto.objects.exists()
    monkeypatch.setattr(
        "inventario.views_importacion_productos.MAX_ARCHIVO", len(data) - 1
    )
    assert enviar(client, data).status_code == 400
    assert not Producto.objects.exists()


@pytest.mark.django_db
def test_comandos_y_proteccion_del_catalogo(tmp_path):
    ruta = tmp_path / "sintetico.xlsx"
    ruta.write_bytes(archivo_excel([("001", "Prueba", None, 1)]))
    salida = StringIO()
    comando = "importar_productos_excel"
    with pytest.raises(CommandError):
        call_command(comando, str(ruta), stdout=salida)
    call_command(comando, str(ruta), "--dry-run", stdout=salida)
    assert "Nuevos: 1" in salida.getvalue()
    assert not Producto.objects.exists()
    call_command(comando, str(ruta), "--confirm", stdout=salida)
    producto = Producto.objects.get(sku="001")
    assert producto.precio == 1
    with pytest.raises(CommandError, match="deshabilitado"):
        call_command("importar_productos", stdout=salida)
    respaldo = tmp_path / "respaldo.json"
    respaldo.write_text(json.dumps({"productos": "[]"}), encoding="utf-8")
    with pytest.raises(CommandError, match="base sin productos"):
        call_command("importar_datos", str(respaldo))
    with pytest.raises(CommandError, match="--clear"):
        call_command("importar_datos", str(respaldo), "--clear")
    assert Producto.objects.get(sku="001").precio == 1

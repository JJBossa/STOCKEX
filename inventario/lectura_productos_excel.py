import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from xml.etree.ElementTree import ParseError
from xml.parsers import expat
from zipfile import BadZipFile, ZipFile
from zlib import error as ZlibError

from openpyxl import load_workbook
from openpyxl.cell.read_only import ReadOnlyCell
from openpyxl.utils.exceptions import InvalidFileException
from openpyxl.worksheet._reader import FORMULA_TAG, WorkSheetParser

from .models import Categoria, Producto

MAX_ARCHIVO = 5 * 1024 * 1024
MAX_DESCOMPRIMIDO = 32 * 1024 * 1024
MAX_FILAS = 5000
MAX_COLUMNAS = 64
MAX_ENTRADAS = 256
COLUMNAS = ("SKU", "Nombre", "Categoría", "Precio")
NUMERO = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


class ExcelInvalido(Exception):
    pass


@dataclass(frozen=True)
class ErrorFila:
    fila: int
    motivo: str


@dataclass(frozen=True)
class FilaProducto:
    fila: int
    sku: str
    nombre: str
    categoria: str | None
    precio: int


@dataclass(frozen=True)
class CatalogoExcel:
    huella: str
    filas: tuple[FilaProducto, ...]
    errores: tuple[ErrorFila, ...]


class LectorExacto(WorkSheetParser):
    """Mantiene el valor XML numérico como texto para convertirlo con Decimal."""

    def parse_cell(self, element):
        numerica = element.get("t", "n") == "n"
        if numerica:
            element.set("t", "str")
        celda = super().parse_cell(element)
        if numerica:
            celda["data_type"] = "d" if celda["style_id"] in self.date_formats else "n"
        celda["formula"] = element.find(FORMULA_TAG) is not None
        return celda


def rechazar_dtd(*_):
    raise ExcelInvalido("El archivo contiene declaraciones XML no permitidas.")


def validar_contenedor(data):
    with ZipFile(BytesIO(data)) as archivo:
        entradas = archivo.infolist()
        if len(entradas) > MAX_ENTRADAS or len(archivo.namelist()) != len(
            set(archivo.namelist())
        ):
            raise ExcelInvalido(
                "El archivo supera el límite de partes o contiene partes duplicadas."
            )
        if sum(parte.file_size for parte in entradas) > MAX_DESCOMPRIMIDO:
            raise ExcelInvalido(
                "El archivo supera el límite de descompresión de 32 MiB."
            )
        for parte in entradas:
            if parte.flag_bits & 1:
                raise ExcelInvalido("Los archivos cifrados no están admitidos.")
            if not parte.is_dir():
                revisar_xml(archivo, parte)


def revisar_xml(archivo, parte):
    parser = expat.ParserCreate()
    parser.StartDoctypeDeclHandler = rechazar_dtd
    try:
        with archivo.open(parte) as origen:
            for bloque in iter(lambda: origen.read(65536), b""):
                parser.Parse(bloque, False)
            parser.Parse(b"", True)
    except expat.ExpatError:
        # Una parte binaria no es XML. El rechazo de DTD se aplica a cualquier sufijo.
        if parte.filename.lower().endswith((".xml", ".rels")):
            raise


def leer_excel(origen, nombre):
    if Path(nombre).suffix.lower() not in (".xlsx", ".xlsm"):
        raise ExcelInvalido("Selecciona un archivo .xlsx o .xlsm.")
    data = origen.read(MAX_ARCHIVO + 1)
    if not data or len(data) > MAX_ARCHIVO:
        raise ExcelInvalido("El archivo debe contener datos y pesar como máximo 5 MiB.")
    try:
        validar_contenedor(data)
        libro = load_workbook(
            BytesIO(data),
            read_only=True,
            data_only=True,
            keep_links=False,
            keep_vba=False,
        )
        try:
            if "Productos" not in libro.sheetnames:
                raise ExcelInvalido("Falta la hoja Productos.")
            filas, errores = leer_hoja(libro["Productos"])
        finally:
            libro.close()
    except (
        AttributeError,
        BadZipFile,
        EOFError,
        IndexError,
        InvalidFileException,
        KeyError,
        NotImplementedError,
        OSError,
        OverflowError,
        ParseError,
        RuntimeError,
        TypeError,
        ValueError,
        ZlibError,
        expat.ExpatError,
    ) as error:
        raise ExcelInvalido(
            "El archivo Excel está corrupto o tiene un formato inválido."
        ) from error
    return CatalogoExcel(hashlib.sha256(data).hexdigest(), tuple(filas), tuple(errores))


def leer_hoja(hoja):
    with hoja._get_source() as origen:
        parser = LectorExacto(
            origen,
            hoja._shared_strings,
            data_only=True,
            date_formats=hoja.parent._date_formats,
        )
        filas = parser.parse()
        encabezado, celdas = next(filas, (0, []))
        if encabezado != 1:
            raise ExcelInvalido("La fila 1 debe contener las columnas requeridas.")
        columnas = posiciones_columnas(celdas)
        return validar_filas(hoja, filas, columnas)


def posiciones_columnas(celdas):
    nombres = {}
    posiciones = set()
    for celda in celdas:
        columna = celda["column"]
        if (
            celda["row"] != 1
            or not 1 <= columna <= MAX_COLUMNAS
            or columna in posiciones
        ):
            raise ExcelInvalido(
                "La fila 1 contiene posiciones inválidas o más de 64 columnas."
            )
        posiciones.add(columna)
        nombre = celda["value"]
        if nombre in COLUMNAS:
            if nombre in nombres:
                raise ExcelInvalido(f"La fila 1 repite la columna {nombre}.")
            nombres[nombre] = columna
    faltantes = ", ".join(columna for columna in COLUMNAS if columna not in nombres)
    if faltantes:
        raise ExcelInvalido(f"En la fila 1 faltan columnas obligatorias: {faltantes}.")
    return nombres


def validar_filas(hoja, filas, columnas):
    candidatas = []
    errores = []
    anterior = 1
    for fila, celdas in filas:
        if fila > MAX_FILAS + 1:
            raise ExcelInvalido("La hoja Productos admite hasta 5000 filas de datos.")
        mapa = {celda["column"]: celda for celda in celdas}
        if (
            fila <= anterior
            or len(mapa) != len(celdas)
            or any(
                celda["row"] != fila or not 1 <= celda["column"] <= MAX_COLUMNAS
                for celda in celdas
            )
        ):
            raise ExcelInvalido(
                f"La fila {fila} contiene posiciones inválidas o más de 64 columnas."
            )
        anterior = fila
        campos = {nombre: mapa.get(columna, {}) for nombre, columna in columnas.items()}
        if not any(
            celda.get("value") is not None or celda.get("formula")
            for celda in campos.values()
        ):
            continue
        try:
            for nombre, celda in campos.items():
                if celda.get("formula") and (
                    celda["value"] is None or celda["data_type"] == "e"
                ):
                    raise ExcelInvalido(f"{nombre}: fórmula sin valor válido guardado.")
            candidatas.append(
                FilaProducto(
                    fila,
                    leer_sku(hoja, campos["SKU"]),
                    texto(
                        campos["Nombre"],
                        "Nombre",
                        Producto._meta.get_field("nombre").max_length,
                    ),
                    texto(
                        campos["Categoría"],
                        "Categoría",
                        Categoria._meta.get_field("nombre").max_length,
                        opcional=True,
                    ),
                    leer_precio(campos["Precio"]),
                )
            )
        except ExcelInvalido as error:
            errores.append(ErrorFila(fila, str(error)))
    repeticiones = Counter(fila.sku for fila in candidatas)
    validas = []
    for fila in candidatas:
        if repeticiones[fila.sku] > 1:
            errores.append(ErrorFila(fila.fila, "SKU duplicado dentro del archivo."))
        else:
            validas.append(fila)
    if not validas and not errores:
        raise ExcelInvalido("La hoja Productos no contiene filas de datos.")
    return validas, sorted(errores, key=lambda error: error.fila)


def texto(celda, nombre, largo, *, opcional=False):
    valor = celda.get("value")
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        if opcional and celda.get("data_type") != "e":
            return None
        raise ExcelInvalido(f"{nombre}: el campo es obligatorio.")
    if (
        celda.get("data_type") not in ("s", "str")
        or "\x00" in valor
        or len(valor) > largo
    ):
        raise ExcelInvalido(
            f"{nombre}: se requiere texto válido de hasta {largo} caracteres."
        )
    return valor


def entero(valor, minimo, maximo):
    if (
        not isinstance(valor, str)
        or len(valor) > 64
        or not NUMERO.fullmatch(valor.strip())
    ):
        return None
    try:
        numero = Decimal(valor.strip())
    except InvalidOperation:
        return None
    if minimo <= numero <= maximo and numero == numero.to_integral_value():
        return int(numero)
    return None


def leer_sku(hoja, celda):
    largo = Producto._meta.get_field("sku").max_length
    if celda.get("data_type") == "n" and celda.get("value") is not None:
        valor = entero(celda["value"], 0, 999_999_999_999_999)
        if valor is None:
            raise ExcelInvalido("SKU numérico inválido. Guárdalo como texto.")
        formato = ReadOnlyCell(
            hoja,
            celda["row"],
            celda["column"],
            celda["value"],
            style_id=celda["style_id"],
        ).number_format
        if formato == "General":
            return str(valor)
        if re.fullmatch(r"0{1,50}", formato):
            return str(valor).zfill(len(formato))
        raise ExcelInvalido("Formato de SKU numérico ambiguo. Guárdalo como texto.")
    return texto(celda, "SKU", largo)


def leer_precio(celda):
    if celda.get("data_type") in ("n", "s", "str"):
        maximo = 10 ** Producto._meta.get_field("precio").max_digits - 1
        precio = entero(celda.get("value"), 1, maximo)
        if precio is not None:
            return precio
    raise ExcelInvalido(
        "Precio: se requiere un entero positivo de hasta 10 dígitos, en CLP."
    )

import hashlib
import json
from dataclasses import dataclass

from django.core.cache import cache
from django.db import IntegrityError, OperationalError, connection, transaction
from django.db.models import F

from .lectura_productos_excel import CatalogoExcel, ErrorFila, FilaProducto
from .models import Categoria, Producto


class ConflictoImportacion(Exception):
    pass


@dataclass(frozen=True)
class Resumen:
    validas: int
    nuevos: int
    actualizados: int
    sin_cambios: int
    precio_un_peso: tuple[FilaProducto, ...]
    sin_categoria: int
    errores: tuple[ErrorFila, ...]


@dataclass
class Plan:
    resumen: Resumen
    version: str
    productos: dict[str, Producto]
    categorias: dict[str, Categoria]
    pendientes: list[FilaProducto]


def requiere_cambio(fila, producto, categorias):
    categoria = categorias.get(fila.categoria)
    if fila.categoria and categoria is None:
        return True
    return (
        producto.nombre != fila.nombre
        or producto.precio != fila.precio
        or producto.categoria_id != (categoria.pk if categoria else None)
    )


def planificar(catalogo: CatalogoExcel, *, bloquear=False):
    productos = Producto.objects.order_by("pk")
    categorias = Categoria.objects.order_by("pk")
    if bloquear:
        productos = productos.select_for_update()
        categorias = categorias.select_for_update()
    productos = productos.in_bulk(
        sorted(fila.sku for fila in catalogo.filas), field_name="sku"
    )
    nombres = sorted({fila.categoria for fila in catalogo.filas if fila.categoria})
    categorias = categorias.in_bulk(nombres, field_name="nombre")
    estado = [
        [
            (sku, prod.pk, prod.nombre, str(prod.precio), prod.categoria_id)
            for sku, prod in sorted(productos.items())
        ],
        [(nombre, categoria.pk) for nombre, categoria in sorted(categorias.items())],
    ]
    version = hashlib.sha256(json.dumps(estado, sort_keys=True).encode()).hexdigest()
    nuevos, actualizados, pendientes = 0, 0, []
    for fila in catalogo.filas:
        producto = productos.get(fila.sku)
        if producto is None:
            nuevos += 1
            pendientes.append(fila)
        elif requiere_cambio(fila, producto, categorias):
            actualizados += 1
            pendientes.append(fila)
    resumen = Resumen(
        validas=len(catalogo.filas),
        nuevos=nuevos,
        actualizados=actualizados,
        sin_cambios=len(catalogo.filas) - len(pendientes),
        precio_un_peso=tuple(fila for fila in catalogo.filas if fila.precio == 1),
        sin_categoria=sum(fila.categoria is None for fila in catalogo.filas),
        errores=catalogo.errores,
    )
    return Plan(resumen, version, productos, categorias, pendientes)


def bloquear_catalogo():
    """Serializa importadores antes de leer el estado dentro de la transacción."""
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [0x53544B5F3032])
    elif connection.vendor == "sqlite":
        # Inicia la transacción de escritura sin cambiar filas ni ejecutar señales.
        Producto.objects.filter(pk__isnull=True).update(stock=F("stock"))
    else:
        raise ConflictoImportacion("Este motor no está admitido para la importación.")


def importar(catalogo: CatalogoExcel, *, version=None, usuario=None):
    if catalogo.errores:
        raise ConflictoImportacion("Corrige las filas con errores antes de confirmar.")
    try:
        with transaction.atomic():
            bloquear_catalogo()
            plan = planificar(catalogo, bloquear=True)
            if version is not None and version != plan.version and plan.pendientes:
                raise ConflictoImportacion(
                    "El catálogo cambió. Genera una vista previa nueva."
                )
            if plan.pendientes:
                guardar_productos(plan, usuario)
                transaction.on_commit(
                    lambda: cache.delete_many(
                        ["categorias_list", "stats_inicio_global"]
                    ),
                    robust=True,
                )
            return plan.resumen
    except IntegrityError as error:
        raise ConflictoImportacion(
            "Un conflicto de integridad impidió importar. Revisa el catálogo y vuelve a previsualizar."
        ) from error
    except OperationalError as error:
        causa = error.__cause__
        if getattr(causa, "sqlite_errorname", "").startswith(
            ("SQLITE_BUSY", "SQLITE_LOCKED")
        ) or (getattr(causa, "pgcode", None) in {"40001", "40P01", "55P03"}):
            raise ConflictoImportacion(
                "El catálogo está ocupado. Vuelve a generar la vista previa o inténtalo de nuevo."
            ) from error
        raise


def guardar_productos(plan, usuario):
    faltantes = sorted(
        {
            fila.categoria
            for fila in plan.pendientes
            if fila.categoria and fila.categoria not in plan.categorias
        }
    )
    categorias = Categoria.objects.bulk_create(
        [Categoria(nombre=nombre) for nombre in faltantes]
    )
    plan.categorias.update((categoria.nombre, categoria) for categoria in categorias)
    for fila in plan.pendientes:
        categoria = plan.categorias.get(fila.categoria)
        producto = plan.productos.get(fila.sku)
        if producto is None:
            Producto.objects.create(
                sku=fila.sku,
                nombre=fila.nombre,
                categoria=categoria,
                precio=fila.precio,
                stock=0,
                precio_compra=0,
            )
            continue
        producto.nombre = fila.nombre
        producto.categoria = categoria
        producto.precio = fila.precio
        producto._request_user = usuario
        producto.save(
            update_fields=["nombre", "categoria", "precio", "fecha_actualizacion"]
        )

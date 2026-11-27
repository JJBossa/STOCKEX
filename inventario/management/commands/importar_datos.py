import json
from pathlib import Path

from django.core import serializers
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from inventario.importacion_productos import bloquear_catalogo
from inventario.models import Categoria, Factura, ItemFactura, Producto, Proveedor

SECCIONES = (
    ("categorias", Categoria),
    ("proveedores", Proveedor),
    ("productos", Producto),
    ("facturas", Factura),
    ("items_factura", ItemFactura),
)


class Command(BaseCommand):
    help = "Restaura un respaldo JSON explícito. Solo carga catálogo en una base sin catálogo."

    def add_arguments(self, parser):
        parser.add_argument("archivo", type=Path)
        parser.add_argument("--clear", action="store_true", help="Opción retirada.")
        parser.add_argument(
            "--skip-if-exists", action="store_true", help="Compatibilidad histórica."
        )

    def handle(self, *args, **options):
        if options["clear"]:
            raise CommandError("--clear ya no está admitido.")
        try:
            datos = json.loads(options["archivo"].read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise CommandError("No se pudo leer el respaldo JSON.") from error
        if not isinstance(datos, dict):
            raise CommandError(
                "El respaldo JSON debe contener sus secciones por nombre."
            )
        with transaction.atomic():
            if {"productos", "categorias"} & datos.keys():
                bloquear_catalogo()
                if Producto.objects.exists() or Categoria.objects.exists():
                    raise CommandError(
                        "La restauración de catálogo exige una base sin productos ni categorías."
                    )
            for seccion, modelo in SECCIONES:
                if seccion in datos:
                    for registro in serializers.deserialize("json", datos[seccion]):
                        if not isinstance(registro.object, modelo):
                            raise CommandError(
                                f"Modelo incorrecto en la sección {seccion}."
                            )
                        registro.save()
        self.stdout.write(self.style.SUCCESS("Restauración completada."))

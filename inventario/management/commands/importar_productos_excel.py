from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from inventario.importacion_productos import ConflictoImportacion, importar, planificar
from inventario.lectura_productos_excel import ExcelInvalido, leer_excel


class Command(BaseCommand):
    help = "Previsualiza o importa el catálogo desde la hoja Productos de un Excel."

    def add_arguments(self, parser):
        parser.add_argument("archivo", type=Path)
        modo = parser.add_mutually_exclusive_group(required=True)
        modo.add_argument(
            "--dry-run", action="store_true", help="Validar sin escribir."
        )
        modo.add_argument(
            "--confirm", action="store_true", help="Confirmar la importación atómica."
        )

    def handle(self, *args, **opciones):
        ruta = opciones["archivo"]
        try:
            with ruta.open("rb") as archivo:
                catalogo = leer_excel(archivo, ruta.name)
        except OSError as error:
            raise CommandError("No se pudo abrir el archivo Excel.") from error
        except ExcelInvalido as error:
            raise CommandError(str(error)) from error
        plan = planificar(catalogo)
        resumen = plan.resumen
        if opciones["confirm"] and not resumen.errores:
            try:
                resumen = importar(catalogo, version=plan.version)
            except ConflictoImportacion as error:
                raise CommandError(str(error)) from error
            self.stdout.write("Importación confirmada.")
        else:
            self.stdout.write("Vista previa. Sin escrituras.")
        self.stdout.write(
            f"Válidas: {resumen.validas} | Nuevos: {resumen.nuevos} | "
            f"Actualizados: {resumen.actualizados} | Sin cambios: {resumen.sin_cambios} | "
            f"Precio $1: {len(resumen.precio_un_peso)} | Sin categoría: {resumen.sin_categoria}"
        )
        for fila in resumen.precio_un_peso:
            self.stdout.write(f"Fila {fila.fila}: revisar precio $1.")
        for error in resumen.errores:
            self.stderr.write(f"Fila {error.fila}: {error.motivo}")
        if resumen.errores:
            raise CommandError("Hay filas con errores. No se importó ningún producto.")

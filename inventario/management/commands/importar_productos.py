from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Importador de catálogo anterior retirado."

    def handle(self, *args, **options):
        raise CommandError(
            "El catálogo anterior está deshabilitado. Usa importar_productos_excel RUTA --dry-run."
        )

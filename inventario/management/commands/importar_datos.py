"""
Comando para importar datos desde un archivo JSON exportado
Útil para migrar datos de SQLite (desarrollo local) a PostgreSQL (producción en Render)

Uso:
    python manage.py importar_datos datos_exportados.json
"""

from django.core.management.base import BaseCommand
from django.core import serializers
from django.db import transaction
from pathlib import Path
import json
from inventario.models import Producto

class Command(BaseCommand):
    help = 'Importa datos desde un archivo JSON exportado anteriormente'

    def add_arguments(self, parser):
        parser.add_argument(
            'archivo',
            type=str,
            help='Ruta al archivo JSON con los datos exportados',
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Elimina los datos existentes antes de importar',
        )
        parser.add_argument(
            '--skip-if-exists',
            action='store_true',
            default=True,
            help='No importar si ya existen datos (por defecto: True)',
        )

    def handle(self, *args, **options):
        archivo = options['archivo']
        clear = options.get('clear', False)
        skip_if_exists = options.get('skip-if-exists', True)
        
        BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
        archivo_path = BASE_DIR / archivo
        
        if not archivo_path.exists():
            self.stdout.write(
                self.style.ERROR(f'✗ El archivo {archivo_path} no existe')
            )
            return
        
        # Si skip-if-exists está activado y ya hay productos, no importar
        if skip_if_exists and Producto.objects.exists():
            self.stdout.write(
                self.style.WARNING(
                    f'⚠️  Ya existen productos en la base de datos. '
                    f'No se importarán datos para evitar duplicados.\n'
                    f'   Si deseas forzar la importación, ejecuta con --clear o elimina los datos existentes.'
                )
            )
            return
        
        self.stdout.write(f'Importando datos desde: {archivo_path}')
        
        # Cargar datos
        with open(archivo_path, 'r', encoding='utf-8') as f:
            datos = json.load(f)
        
        try:
            with transaction.atomic():
                # Importar en el orden correcto (respetando dependencias)
                
                # 1. Categorías (sin dependencias)
                if 'categorias' in datos:
                    self.stdout.write('  Importando categorías...')
                    for obj in serializers.deserialize('json', datos['categorias']):
                        obj.save()
                    self.stdout.write(self.style.SUCCESS('    ✓ Categorías importadas'))
                
                # 2. Proveedores (sin dependencias)
                if 'proveedores' in datos:
                    self.stdout.write('  Importando proveedores...')
                    for obj in serializers.deserialize('json', datos['proveedores']):
                        obj.save()
                    self.stdout.write(self.style.SUCCESS('    ✓ Proveedores importados'))
                
                # 3. Productos (depende de categorías)
                if 'productos' in datos:
                    self.stdout.write('  Importando productos...')
                    for obj in serializers.deserialize('json', datos['productos']):
                        obj.save()
                    self.stdout.write(self.style.SUCCESS('    ✓ Productos importados'))
                
                # 4. Facturas (depende de proveedores)
                if 'facturas' in datos:
                    self.stdout.write('  Importando facturas...')
                    for obj in serializers.deserialize('json', datos['facturas']):
                        obj.save()
                    self.stdout.write(self.style.SUCCESS('    ✓ Facturas importadas'))
                
                # 5. Items de Factura (depende de facturas y productos)
                if 'items_factura' in datos:
                    self.stdout.write('  Importando items de factura...')
                    for obj in serializers.deserialize('json', datos['items_factura']):
                        obj.save()
                    self.stdout.write(self.style.SUCCESS('    ✓ Items de factura importados'))
                
                self.stdout.write(
                    self.style.SUCCESS(
                        '\n✓ Importación completada exitosamente!'
                    )
                )
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'\n✗ Error durante la importación: {str(e)}')
            )
            raise


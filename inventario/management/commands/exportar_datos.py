"""
Comando para exportar datos desde SQLite (desarrollo local) a formato JSON
Este JSON puede luego importarse en PostgreSQL (producción en Render)

Uso:
    python manage.py exportar_datos

Esto creará un archivo 'datos_exportados.json' con todos los datos del modelo.
"""

from django.core.management.base import BaseCommand
from django.core import serializers
from inventario.models import Producto, Categoria, Proveedor, Factura, ItemFactura
import json
from pathlib import Path

class Command(BaseCommand):
    help = 'Exporta todos los datos de la base de datos a un archivo JSON para importar en producción'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output',
            type=str,
            default='datos_exportados.json',
            help='Nombre del archivo de salida (default: datos_exportados.json)',
        )

    def handle(self, *args, **options):
        output_file = options['output']
        BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
        
        self.stdout.write('Iniciando exportación de datos...')
        
        # Exportar todos los modelos
        datos = {}
        
        # Exportar Categorías
        categorias = Categoria.objects.all()
        datos['categorias'] = serializers.serialize('json', categorias)
        self.stdout.write(f'  ✓ Exportadas {categorias.count()} categorías')
        
        # Exportar Productos
        productos = Producto.objects.all()
        datos['productos'] = serializers.serialize('json', productos)
        self.stdout.write(f'  ✓ Exportados {productos.count()} productos')
        
        # Exportar Proveedores
        proveedores = Proveedor.objects.all()
        datos['proveedores'] = serializers.serialize('json', proveedores)
        self.stdout.write(f'  ✓ Exportados {proveedores.count()} proveedores')
        
        # Exportar Facturas
        facturas = Factura.objects.all()
        datos['facturas'] = serializers.serialize('json', facturas)
        self.stdout.write(f'  ✓ Exportadas {facturas.count()} facturas')
        
        # Exportar Items de Factura
        items = ItemFactura.objects.all()
        datos['items_factura'] = serializers.serialize('json', items)
        self.stdout.write(f'  ✓ Exportados {items.count()} items de factura')
        
        # Guardar en archivo JSON
        output_path = BASE_DIR / output_file
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(datos, f, indent=2, ensure_ascii=False)
        
        self.stdout.write(
            self.style.SUCCESS(
                f'\n✓ Exportación completada!\n'
                f'  Archivo guardado en: {output_path}\n'
                f'\n  Para importar en producción, ejecuta:\n'
                f'    python manage.py importar_datos {output_file}'
            )
        )


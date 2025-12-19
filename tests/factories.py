"""
Factories para crear datos de prueba con factory_boy
"""
import factory
from factory.django import DjangoModelFactory
from django.contrib.auth.models import User
from inventario.models import Categoria, Producto, Venta, ItemVenta, Cotizacion, ItemCotizacion


class UserFactory(DjangoModelFactory):
    """Factory para crear usuarios de prueba"""
    class Meta:
        model = User
        django_get_or_create = ('username',)
    
    username = factory.Sequence(lambda n: f'user{n}')
    email = factory.LazyAttribute(lambda obj: f'{obj.username}@test.com')
    password = factory.PostGenerationMethodCall('set_password', 'testpass123')


class CategoriaFactory(DjangoModelFactory):
    """Factory para crear categorías de prueba"""
    class Meta:
        model = Categoria
        django_get_or_create = ('nombre',)
    
    nombre = factory.Sequence(lambda n: f'Categoría {n}')
    descripcion = factory.Faker('text', max_nb_chars=100)
    color = '#667eea'


class ProductoFactory(DjangoModelFactory):
    """Factory para crear productos de prueba"""
    class Meta:
        model = Producto
    
    nombre = factory.Sequence(lambda n: f'Producto {n}')
    sku = factory.Sequence(lambda n: f'SKU-{n:04d}')
    descripcion = factory.Faker('text', max_nb_chars=200)
    categoria = factory.SubFactory(CategoriaFactory)
    precio = factory.Faker('pyint', min_value=1000, max_value=100000)
    precio_compra = factory.LazyAttribute(lambda obj: obj.precio * 0.5)
    stock = factory.Faker('pyint', min_value=0, max_value=100)
    stock_minimo = 10
    activo = True


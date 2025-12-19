"""
Tests para los modelos de la aplicación inventario
"""
import pytest
from django.core.exceptions import ValidationError
from inventario.models import Producto, Categoria, Venta, ItemVenta, Cotizacion


@pytest.mark.django_db
class TestCategoria:
    """Tests para el modelo Categoria"""
    
    def test_crear_categoria(self):
        """Test que se puede crear una categoría"""
        categoria = Categoria.objects.create(
            nombre='Test Categoría',
            descripcion='Descripción test',
            color='#ff0000'
        )
        assert categoria.nombre == 'Test Categoría'
        assert str(categoria) == 'Test Categoría'
    
    def test_categoria_unique_name(self):
        """Test que el nombre de categoría debe ser único"""
        Categoria.objects.create(nombre='Única')
        with pytest.raises(Exception):  # IntegrityError
            Categoria.objects.create(nombre='Única')


@pytest.mark.django_db
class TestProducto:
    """Tests para el modelo Producto"""
    
    def test_crear_producto(self, categoria):
        """Test que se puede crear un producto"""
        producto = Producto.objects.create(
            nombre='Producto Test',
            categoria=categoria,
            precio=10000,
            stock=50
        )
        assert producto.nombre == 'Producto Test'
        assert producto.precio == 10000
        assert producto.stock == 50
        assert producto.activo is True
    
    def test_producto_genera_sku_automatico(self, categoria):
        """Test que se genera SKU automático si no se proporciona"""
        producto = Producto.objects.create(
            nombre='Producto Sin SKU',
            categoria=categoria,
            precio=10000
        )
        assert producto.sku is not None
        assert len(producto.sku) > 0
    
    def test_producto_stock_bajo(self, categoria):
        """Test la propiedad stock_bajo"""
        producto = Producto.objects.create(
            nombre='Producto',
            categoria=categoria,
            precio=10000,
            stock=5,
            stock_minimo=10
        )
        assert producto.stock_bajo is True
        
        producto.stock = 15
        producto.save()
        assert producto.stock_bajo is False
    
    def test_producto_margen_ganancia(self, categoria):
        """Test el cálculo de margen de ganancia"""
        producto = Producto.objects.create(
            nombre='Producto',
            categoria=categoria,
            precio=10000,
            precio_compra=5000,
            stock=10
        )
        assert producto.margen_ganancia == 100.0  # (10000-5000)/5000 * 100
    
    def test_producto_valor_inventario(self, categoria):
        """Test el cálculo de valor de inventario"""
        producto = Producto.objects.create(
            nombre='Producto',
            categoria=categoria,
            precio=10000,
            stock=5
        )
        assert producto.valor_inventario == 50000  # 10000 * 5


@pytest.mark.django_db
class TestVenta:
    """Tests para el modelo Venta"""
    
    def test_crear_venta(self, admin_user):
        """Test que se puede crear una venta"""
        venta = Venta.objects.create(
            usuario=admin_user,
            subtotal=10000,
            total=10000,
            metodo_pago='efectivo',
            monto_recibido=10000,
            cambio=0
        )
        assert venta.numero_venta is not None
        assert venta.total == 10000
        assert venta.cancelada is False
    
    def test_venta_genera_numero_automatico(self, admin_user):
        """Test que se genera número de venta automático"""
        venta = Venta.objects.create(
            usuario=admin_user,
            subtotal=10000,
            total=10000,
            metodo_pago='efectivo',
            monto_recibido=10000
        )
        assert venta.numero_venta.startswith('V-')


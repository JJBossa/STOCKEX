"""
Serializers para Django REST Framework
Estos serializers permiten exponer los modelos como API REST
"""
from rest_framework import serializers
from django.contrib.auth.models import User
from .models import (
    Producto, Categoria, Venta, ItemVenta, 
    Cotizacion, ItemCotizacion, Proveedor, 
    MovimientoStock, NotificacionStock
)


class CategoriaSerializer(serializers.ModelSerializer):
    """Serializer para el modelo Categoria"""
    producto_count = serializers.IntegerField(source='producto_set.count', read_only=True)
    
    class Meta:
        model = Categoria
        fields = ['id', 'nombre', 'descripcion', 'color', 'fecha_creacion', 'producto_count']
        read_only_fields = ['fecha_creacion']


class ProductoSerializer(serializers.ModelSerializer):
    """Serializer para el modelo Producto"""
    categoria_nombre = serializers.CharField(source='categoria.nombre', read_only=True)
    categoria_color = serializers.CharField(source='categoria.color', read_only=True)
    stock_bajo = serializers.BooleanField(read_only=True)
    margen_ganancia = serializers.FloatField(read_only=True, allow_null=True)
    valor_inventario = serializers.DecimalField(max_digits=12, decimal_places=0, read_only=True)
    
    class Meta:
        model = Producto
        fields = [
            'id', 'nombre', 'sku', 'descripcion', 'categoria', 'categoria_nombre', 
            'categoria_color', 'precio_compra', 'precio', 'precio_promo', 
            'stock', 'stock_minimo', 'stock_bajo', 'imagen', 'activo',
            'margen_ganancia', 'valor_inventario', 'fecha_creacion', 'fecha_actualizacion'
        ]
        read_only_fields = ['fecha_creacion', 'fecha_actualizacion', 'sku']


class ProductoListSerializer(serializers.ModelSerializer):
    """Serializer simplificado para listar productos (más rápido)"""
    categoria_nombre = serializers.CharField(source='categoria.nombre', read_only=True)
    
    class Meta:
        model = Producto
        fields = ['id', 'nombre', 'sku', 'precio', 'precio_promo', 'stock', 'categoria_nombre', 'imagen', 'activo']


class ItemVentaSerializer(serializers.ModelSerializer):
    """Serializer para items de venta"""
    producto_nombre = serializers.CharField(source='producto.nombre', read_only=True)
    producto_sku = serializers.CharField(source='producto.sku', read_only=True)
    
    class Meta:
        model = ItemVenta
        fields = [
            'id', 'producto', 'producto_nombre', 'producto_sku', 
            'nombre_producto', 'cantidad', 'precio_unitario', 
            'subtotal', 'stock_anterior', 'stock_despues'
        ]
        read_only_fields = ['subtotal', 'stock_anterior', 'stock_despues']


class VentaSerializer(serializers.ModelSerializer):
    """Serializer para el modelo Venta"""
    items = ItemVentaSerializer(many=True, read_only=True)
    usuario_nombre = serializers.CharField(source='usuario.username', read_only=True)
    items_count = serializers.IntegerField(source='items.count', read_only=True)
    
    class Meta:
        model = Venta
        fields = [
            'id', 'numero_venta', 'usuario', 'usuario_nombre', 'fecha',
            'subtotal', 'descuento', 'total', 'metodo_pago',
            'monto_recibido', 'cambio', 'notas', 'cancelada',
            'items', 'items_count'
        ]
        read_only_fields = ['numero_venta', 'fecha', 'subtotal', 'total', 'cambio']


class ItemCotizacionSerializer(serializers.ModelSerializer):
    """Serializer para items de cotización"""
    producto_nombre = serializers.CharField(source='producto.nombre', read_only=True)
    
    class Meta:
        model = ItemCotizacion
        fields = [
            'id', 'producto', 'producto_nombre', 'nombre_producto',
            'cantidad', 'precio_unitario', 'subtotal'
        ]
        read_only_fields = ['subtotal']


class CotizacionSerializer(serializers.ModelSerializer):
    """Serializer para el modelo Cotizacion"""
    items = ItemCotizacionSerializer(many=True, read_only=True)
    usuario_nombre = serializers.CharField(source='usuario.username', read_only=True)
    esta_vencida = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = Cotizacion
        fields = [
            'id', 'numero_cotizacion', 'usuario', 'usuario_nombre',
            'cliente_nombre', 'cliente_contacto', 'cliente_telefono', 'cliente_email',
            'fecha_creacion', 'fecha_vencimiento', 'subtotal', 'descuento', 'total',
            'estado', 'notas', 'convertida_en_venta', 'items', 'esta_vencida'
        ]
        read_only_fields = ['numero_cotizacion', 'fecha_creacion', 'subtotal', 'total']


class ProveedorSerializer(serializers.ModelSerializer):
    """Serializer para el modelo Proveedor"""
    class Meta:
        model = Proveedor
        fields = ['id', 'nombre', 'rut', 'contacto', 'telefono', 'email', 'direccion', 'fecha_creacion']
        read_only_fields = ['fecha_creacion']


class MovimientoStockSerializer(serializers.ModelSerializer):
    """Serializer para movimientos de stock"""
    producto_nombre = serializers.CharField(source='producto.nombre', read_only=True)
    usuario_nombre = serializers.CharField(source='usuario.username', read_only=True)
    
    class Meta:
        model = MovimientoStock
        fields = [
            'id', 'producto', 'producto_nombre', 'tipo', 'cantidad', 'motivo',
            'stock_anterior', 'stock_nuevo', 'usuario', 'usuario_nombre',
            'fecha', 'notas', 'factura'
        ]
        read_only_fields = ['fecha']


class NotificacionStockSerializer(serializers.ModelSerializer):
    """Serializer para notificaciones de stock bajo"""
    producto_nombre = serializers.CharField(source='producto.nombre', read_only=True)
    producto_sku = serializers.CharField(source='producto.sku', read_only=True)
    
    class Meta:
        model = NotificacionStock
        fields = [
            'id', 'producto', 'producto_nombre', 'producto_sku',
            'fecha', 'vista', 'notificada', 'stock_anterior', 'stock_actual'
        ]
        read_only_fields = ['fecha']


"""
Vistas API usando Django REST Framework
Estos endpoints están en paralelo con los existentes, NO los reemplazan
"""
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import F, Prefetch
from django.db.models.deletion import ProtectedError
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django_filters.rest_framework import DjangoFilterBackend, FilterSet, NumberFilter
from typing import Optional

from .models import (
    Producto,
    Categoria,
    Venta,
    ItemVenta,
    Cotizacion,
    MovimientoStock,
    NotificacionStock,
    Proveedor,
)
from .serializers import (
    ProductoSerializer, ProductoListSerializer, CategoriaSerializer,
    VentaSerializer, CotizacionSerializer, MovimientoStockSerializer,
    NotificacionStockSerializer, ProveedorSerializer
)
from .access import ventas_visibles
from .permissions import PermisosCatalogo, PermisosModelo, PermisoAccionAdministrativa
from .utils import es_administrador


class ProductoViewSet(viewsets.ModelViewSet):
    permiso_accion = 'inventario.change_producto'

    """
    ViewSet para gestionar productos
    
    Permite:
    - list: Listar productos (GET /api/v1/productos/)
    - retrieve: Obtener un producto (GET /api/v1/productos/{id}/)
    - create: Crear producto (POST /api/v1/productos/)
    - update: Actualizar producto (PUT /api/v1/productos/{id}/)
    - destroy: Eliminar producto (DELETE /api/v1/productos/{id}/)
    
    Filtros:
    - ?search=nombre - Búsqueda en nombre y SKU
    - ?categoria=id - Filtrar por categoría
    - ?stock_bajo=true - Solo productos con stock bajo
    - ?activo=true - Solo productos activos
    """
    queryset = Producto.objects.all().select_related('categoria')
    permission_classes = [PermisosCatalogo]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['categoria', 'activo']
    search_fields = ['nombre', 'sku', 'descripcion']
    ordering_fields = ['nombre', 'precio', 'stock', 'fecha_creacion']
    ordering = ['nombre']
    
    def get_serializer_class(self):
        """Usar serializer simplificado para list, completo para detail"""
        if self.action == 'list':
            return ProductoListSerializer
        return ProductoSerializer
    
    def get_queryset(self):
        """Filtrar productos según parámetros"""
        queryset = super().get_queryset()
        
        # Filtrar por stock bajo
        stock_bajo = self.request.query_params.get('stock_bajo', None)
        if stock_bajo == 'true':
            queryset = queryset.filter(stock__lte=F('stock_minimo'))
        
        # Filtrar solo activos por defecto (si no se especifica)
        activo = self.request.query_params.get('activo', 'true')
        if activo == 'true':
            queryset = queryset.filter(activo=True)
        
        return queryset

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {"error": "El producto tiene ventas asociadas."},
                status=status.HTTP_409_CONFLICT,
            )

    @action(
        detail=True, methods=["post"], permission_classes=[PermisoAccionAdministrativa]
    )
    def actualizar_stock(self, request, pk: Optional[int] = None) -> Response:
        """
        Endpoint para actualizar stock de un producto.
        Solo administradores pueden usar este endpoint.
        """
        producto = self.get_object()
        cantidad = request.data.get('cantidad')
        tipo = request.data.get('tipo', 'ajuste')  # entrada, salida, ajuste
        
        if cantidad is None:
            return Response(
                {"error": "Cantidad requerida"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            cantidad = int(cantidad)
            stock_anterior = producto.stock
            
            if tipo == 'entrada':
                producto.stock += cantidad
            elif tipo == 'salida':
                producto.stock = max(0, producto.stock - cantidad)
            else:  # ajuste
                producto.stock = cantidad
            
            producto.save()
            
            return Response({
                'success': True,
                'stock_anterior': stock_anterior,
                'stock_nuevo': producto.stock,
                'producto': ProductoSerializer(producto).data
            })
        except ValueError:
            return Response(
                {'error': 'Cantidad debe ser un número'}, 
                status=status.HTTP_400_BAD_REQUEST
            )


class CategoriaViewSet(viewsets.ModelViewSet):
    """ViewSet para gestionar categorías"""
    queryset = Categoria.objects.all()
    serializer_class = CategoriaSerializer
    permission_classes = [PermisosCatalogo]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nombre', 'descripcion']
    ordering_fields = ['nombre', 'fecha_creacion']
    ordering = ['nombre']


class FiltroVentasAPI(FilterSet):
    usuario = NumberFilter(
        method="filtrar_usuario",
        min_value=1,
        max_value=2**63 - 1,
        max_digits=19,
        decimal_places=0,
    )

    class Meta:
        model = Venta
        fields = ["metodo_pago", "cancelada", "usuario"]

    def filtrar_usuario(self, ventas, nombre, usuario):
        if es_administrador(self.request.user):
            return ventas.filter(usuario_id=usuario)
        return ventas


@method_decorator(never_cache, name="dispatch")
class VentaViewSet(viewsets.ReadOnlyModelViewSet):
    """Consulta de ventas. Conserva el contrato y el alcance de la API."""

    queryset = Venta.objects.all()
    serializer_class = VentaSerializer
    permission_classes = [PermisosModelo]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = FiltroVentasAPI
    ordering_fields = ["fecha", "total"]
    ordering = ["-fecha", "-pk"]

    def get_queryset(self):
        return (
            ventas_visibles(self.request.user)
            .select_related("usuario")
            .prefetch_related(
                Prefetch("items", queryset=ItemVenta.objects.select_related("producto"))
            )
        )


class CotizacionViewSet(viewsets.ModelViewSet):
    """ViewSet para gestionar cotizaciones"""
    queryset = Cotizacion.objects.all().select_related('usuario').prefetch_related('items')
    serializer_class = CotizacionSerializer
    permission_classes = [PermisosModelo]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['estado', 'usuario']
    ordering_fields = ['fecha_creacion', 'total']
    ordering = ['-fecha_creacion']
    
    def get_queryset(self):
        """Filtrar cotizaciones según usuario"""
        queryset = super().get_queryset()
        
        # Si no es admin, solo ver sus propias cotizaciones
        if not es_administrador(self.request.user):
            queryset = queryset.filter(usuario=self.request.user)
        
        return queryset
    
    def perform_create(self, serializer):
        """Asignar usuario actual al crear cotización"""
        serializer.save(usuario=self.request.user)


class MovimientoStockViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet para consultar movimientos de stock (solo lectura)"""
    queryset = MovimientoStock.objects.all().select_related('producto', 'usuario')
    serializer_class = MovimientoStockSerializer
    permission_classes = [PermisosModelo]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['tipo', 'motivo', 'producto']
    ordering_fields = ['fecha']
    ordering = ['-fecha']


class NotificacionStockViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet para consultar notificaciones de stock bajo"""
    queryset = NotificacionStock.objects.all().select_related('producto')
    serializer_class = NotificacionStockSerializer
    permission_classes = [PermisosModelo]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['vista', 'notificada']
    ordering_fields = ['fecha']
    ordering = ['-fecha']
    
    permiso_accion = 'inventario.change_notificacionstock'

    @action(detail=True, methods=['post'], permission_classes=[PermisoAccionAdministrativa])
    def marcar_vista(self, request, pk: Optional[int] = None) -> Response:
        """Marcar notificación como vista"""
        notificacion = self.get_object()
        notificacion.vista = True
        notificacion.save()
        return Response({'success': True})


class ProveedorViewSet(viewsets.ModelViewSet):
    """ViewSet para gestionar proveedores"""
    queryset = Proveedor.objects.all()
    serializer_class = ProveedorSerializer
    permission_classes = [PermisosCatalogo]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nombre', 'rut', 'email']
    ordering_fields = ['nombre', 'fecha_creacion']
    ordering = ['nombre']

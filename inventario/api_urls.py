"""
URLs para la API REST
Estos endpoints están en paralelo con los existentes, NO los reemplazan
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .api_views import (
    ProductoViewSet, CategoriaViewSet, VentaViewSet,
    CotizacionViewSet, MovimientoStockViewSet,
    NotificacionStockViewSet, ProveedorViewSet
)

# Crear router y registrar viewsets
router = DefaultRouter()
router.register(r'productos', ProductoViewSet, basename='producto')
router.register(r'categorias', CategoriaViewSet, basename='categoria')
router.register(r'ventas', VentaViewSet, basename='venta')
router.register(r'cotizaciones', CotizacionViewSet, basename='cotizacion')
router.register(r'movimientos-stock', MovimientoStockViewSet, basename='movimiento-stock')
router.register(r'notificaciones-stock', NotificacionStockViewSet, basename='notificacion-stock')
router.register(r'proveedores', ProveedorViewSet, basename='proveedor')

app_name = 'api'

urlpatterns = [
    # Rutas del router (genera automáticamente: list, create, retrieve, update, destroy)
    path('', include(router.urls)),
    
    # Autenticación JWT
    path('auth/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
]


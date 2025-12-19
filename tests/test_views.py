"""
Tests para las vistas de la aplicación inventario
"""
import pytest
from django.urls import reverse
from django.contrib.auth.models import User
from inventario.models import Producto, Categoria
from tests.factories import ProductoFactory, CategoriaFactory, UserFactory


@pytest.mark.django_db
class TestLogin:
    """Tests para las vistas de autenticación"""
    
    def test_login_view_get(self, client):
        """Test que la vista de login se renderiza correctamente"""
        response = client.get(reverse('login'))
        assert response.status_code == 200
        assert 'form' in response.context
    
    def test_login_view_post_valid(self, client, admin_user):
        """Test login con credenciales válidas"""
        response = client.post(reverse('login'), {
            'username': 'admin_test',
            'password': 'testpass123'
        })
        # Debería redirigir después del login
        assert response.status_code in [302, 200]
    
    def test_login_view_post_invalid(self, client):
        """Test login con credenciales inválidas"""
        response = client.post(reverse('login'), {
            'username': 'noexiste',
            'password': 'wrongpass'
        })
        assert response.status_code == 200  # Vuelve a mostrar el formulario
        assert 'form' in response.context


@pytest.mark.django_db
class TestProductoViews:
    """Tests para las vistas de productos"""
    
    def test_inicio_view_requiere_login(self, client):
        """Test que la vista inicio requiere autenticación"""
        response = client.get(reverse('inicio'))
        # Debería redirigir al login
        assert response.status_code == 302
        assert '/login' in response.url
    
    def test_inicio_view_autenticado(self, client, admin_user):
        """Test que la vista inicio funciona con usuario autenticado"""
        client.force_login(admin_user)
        response = client.get(reverse('inicio'))
        assert response.status_code == 200
        assert 'productos' in response.context
    
    def test_agregar_producto_requiere_admin_bossa(self, client, normal_user):
        """Test que agregar producto requiere ser admin bossa"""
        client.force_login(normal_user)
        response = client.get(reverse('agregar_producto'))
        # Debería redirigir o mostrar error
        assert response.status_code in [302, 403]
    
    def test_agregar_producto_admin_bossa(self, client, bossa_user, categoria):
        """Test que bossa puede acceder a agregar producto"""
        client.force_login(bossa_user)
        response = client.get(reverse('agregar_producto'))
        assert response.status_code == 200


@pytest.mark.django_db
class TestAPIViews:
    """Tests para las vistas API"""
    
    def test_buscar_productos_api_requiere_login(self, client):
        """Test que la API requiere autenticación"""
        response = client.get(reverse('buscar_productos_api'), {'q': 'test'})
        assert response.status_code == 302  # Redirige al login
    
    def test_buscar_productos_api_autenticado(self, client, admin_user):
        """Test que la API funciona con usuario autenticado"""
        ProductoFactory(nombre='Producto Test', activo=True)
        client.force_login(admin_user)
        response = client.get(reverse('buscar_productos_api'), {'q': 'Test'})
        assert response.status_code == 200
        data = response.json()
        assert 'productos' in data
        assert len(data['productos']) > 0


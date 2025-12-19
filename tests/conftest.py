"""
Configuración global de pytest para el proyecto
"""
import pytest
from django.contrib.auth.models import User
from inventario.models import Categoria, Producto
import factory
from factory.django import DjangoModelFactory


@pytest.fixture
def admin_user(db):
    """Crea un usuario administrador para tests"""
    return User.objects.create_user(
        username='admin_test',
        email='admin@test.com',
        password='testpass123',
        is_staff=True,
        is_superuser=True
    )


@pytest.fixture
def normal_user(db):
    """Crea un usuario normal para tests"""
    return User.objects.create_user(
        username='user_test',
        email='user@test.com',
        password='testpass123'
    )


@pytest.fixture
def bossa_user(db):
    """Crea el usuario bossa (admin especial) para tests"""
    return User.objects.create_user(
        username='bossa',
        email='bossa@test.com',
        password='testpass123'
    )


@pytest.fixture
def categoria(db):
    """Crea una categoría de prueba"""
    return Categoria.objects.create(
        nombre='Categoría Test',
        descripcion='Descripción de prueba',
        color='#667eea'
    )


@pytest.fixture
def producto(db, categoria):
    """Crea un producto de prueba"""
    return Producto.objects.create(
        nombre='Producto Test',
        sku='TEST-001',
        descripcion='Producto de prueba',
        categoria=categoria,
        precio=10000,
        precio_compra=5000,
        stock=50,
        stock_minimo=10,
        activo=True
    )


@pytest.fixture
def api_client():
    """Cliente API para tests de REST Framework"""
    from rest_framework.test import APIClient
    return APIClient()


@pytest.fixture
def authenticated_api_client(api_client, admin_user):
    """Cliente API autenticado"""
    api_client.force_authenticate(user=admin_user)
    return api_client


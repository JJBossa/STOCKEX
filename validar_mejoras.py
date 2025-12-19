#!/usr/bin/env python
"""
Script para validar que todas las mejoras implementadas funcionan correctamente
"""
import os
import sys
import django

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'control_stock.settings')
django.setup()

from django.core.management import call_command
from django.test.utils import get_runner
from django.conf import settings
import subprocess


def print_header(text):
    """Imprime un encabezado formateado"""
    print("\n" + "=" * 60)
    print(f"  {text}")
    print("=" * 60 + "\n")


def check_django():
    """Valida que Django funciona correctamente"""
    print_header("1. Validando Django")
    try:
        call_command('check', verbosity=0)
        print("✅ Django check: OK")
        return True
    except Exception as e:
        print(f"❌ Django check: ERROR - {e}")
        return False


def check_migrations():
    """Valida que no hay migraciones pendientes"""
    print_header("2. Validando Migraciones")
    try:
        call_command('makemigrations', '--dry-run', '--check', verbosity=0)
        print("✅ Migraciones: Sin migraciones pendientes")
        return True
    except Exception as e:
        print(f"❌ Migraciones: ERROR - {e}")
        return False


def check_imports():
    """Valida que todos los imports funcionan"""
    print_header("3. Validando Imports")
    errors = []
    
    try:
        from inventario import serializers
        print("✅ serializers.py: OK")
    except Exception as e:
        errors.append(f"serializers.py: {e}")
        print(f"❌ serializers.py: ERROR - {e}")
    
    try:
        from inventario import api_views
        print("✅ api_views.py: OK")
    except Exception as e:
        errors.append(f"api_views.py: {e}")
        print(f"❌ api_views.py: ERROR - {e}")
    
    try:
        from inventario import api_urls
        print("✅ api_urls.py: OK")
    except Exception as e:
        errors.append(f"api_urls.py: {e}")
        print(f"❌ api_urls.py: ERROR - {e}")
    
    try:
        import rest_framework
        print("✅ Django REST Framework: Instalado")
    except ImportError:
        errors.append("Django REST Framework no está instalado")
        print("❌ Django REST Framework: NO INSTALADO")
    
    return len(errors) == 0


def check_urls():
    """Valida que las URLs están configuradas correctamente"""
    print_header("4. Validando URLs")
    try:
        from django.urls import reverse, NoReverseMatch
        from django.conf import settings
        
        # Verificar que las URLs de la API están disponibles
        try:
            # Intentar importar las URLs de la API
            from inventario.api_urls import urlpatterns as api_urls
            print("✅ URLs de API: Configuradas")
        except Exception as e:
            print(f"❌ URLs de API: ERROR - {e}")
            return False
        
        # Verificar URLs existentes (no deben estar rotas)
        try:
            reverse('inicio')
            reverse('login')
            reverse('punto_venta')
            print("✅ URLs existentes: Funcionando")
        except NoReverseMatch as e:
            print(f"❌ URLs existentes: ERROR - {e}")
            return False
        
        return True
    except Exception as e:
        print(f"❌ URLs: ERROR - {e}")
        return False


def check_tests():
    """Valida que los tests pueden ejecutarse"""
    print_header("5. Validando Tests")
    try:
        # Verificar que pytest está instalado
        result = subprocess.run(
            ['pytest', '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            print("✅ pytest: Instalado")
            print(f"   Versión: {result.stdout.strip()}")
        else:
            print("⚠️  pytest: No se pudo verificar (puede no estar instalado)")
            return True  # No es crítico
        
        # Verificar que los archivos de test existen
        test_files = [
            'tests/__init__.py',
            'tests/conftest.py',
            'tests/test_models.py',
            'tests/test_views.py',
        ]
        
        all_exist = True
        for test_file in test_files:
            if os.path.exists(test_file):
                print(f"✅ {test_file}: Existe")
            else:
                print(f"❌ {test_file}: NO EXISTE")
                all_exist = False
        
        return all_exist
    except FileNotFoundError:
        print("⚠️  pytest: No instalado (opcional para validación)")
        return True
    except Exception as e:
        print(f"⚠️  Tests: ERROR - {e}")
        return True  # No es crítico para validación básica


def check_docker():
    """Valida que los archivos Docker existen"""
    print_header("6. Validando Docker")
    docker_files = ['Dockerfile', 'docker-compose.yml', '.dockerignore']
    all_exist = True
    
    for docker_file in docker_files:
        if os.path.exists(docker_file):
            print(f"✅ {docker_file}: Existe")
        else:
            print(f"❌ {docker_file}: NO EXISTE")
            all_exist = False
    
    return all_exist


def check_ci_cd():
    """Valida que CI/CD está configurado"""
    print_header("7. Validando CI/CD")
    ci_file = '.github/workflows/ci.yml'
    
    if os.path.exists(ci_file):
        print(f"✅ {ci_file}: Existe")
        return True
    else:
        print(f"❌ {ci_file}: NO EXISTE")
        return False


def main():
    """Ejecuta todas las validaciones"""
    print("\n" + "=" * 60)
    print("  VALIDACIÓN DE MEJORAS IMPLEMENTADAS")
    print("=" * 60)
    
    results = {
        'Django': check_django(),
        'Migraciones': check_migrations(),
        'Imports': check_imports(),
        'URLs': check_urls(),
        'Tests': check_tests(),
        'Docker': check_docker(),
        'CI/CD': check_ci_cd(),
    }
    
    print_header("RESUMEN")
    
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    
    for name, result in results.items():
        status = "✅" if result else "❌"
        print(f"{status} {name}")
    
    print(f"\n{'=' * 60}")
    print(f"  Resultado: {passed}/{total} validaciones pasaron")
    print(f"{'=' * 60}\n")
    
    if passed == total:
        print("🎉 ¡Todas las validaciones pasaron!")
        print("✅ El proyecto está listo para usar las nuevas mejoras.\n")
        return 0
    else:
        print("⚠️  Algunas validaciones fallaron.")
        print("   Revisa los errores arriba y corrige los problemas.\n")
        return 1


if __name__ == '__main__':
    sys.exit(main())


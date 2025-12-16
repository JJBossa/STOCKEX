from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
import os

User = get_user_model()

class Command(BaseCommand):
    help = 'Crea un usuario normal (sin permisos de administrador) usando variables de entorno si no existe'

    def handle(self, *args, **options):
        # Obtener credenciales de variables de entorno
        username = os.environ.get('NORMAL_USER_USERNAME', 'user1')
        email = os.environ.get('NORMAL_USER_EMAIL', 'user1@example.com')
        password = os.environ.get('NORMAL_USER_PASSWORD')
        
        # Si no hay password en variables de entorno, usar un default
        # IMPORTANTE: En producción, SIEMPRE define NORMAL_USER_PASSWORD
        if not password:
            password = os.environ.get('DJANGO_NORMAL_USER_PASSWORD', 'u.123456')
            self.stdout.write(
                self.style.WARNING(
                    '⚠️  No se encontró NORMAL_USER_PASSWORD. Usando valor por defecto.\n'
                    '   ⚠️  IMPORTANTE: Define NORMAL_USER_PASSWORD en Render para producción!'
                )
            )
        
        # Verificar si el usuario ya existe
        if User.objects.filter(username=username).exists():
            self.stdout.write(
                self.style.WARNING(
                    f'El usuario "{username}" ya existe. No se creará nuevamente.'
                )
            )
            return
        
        # Crear el usuario normal (sin permisos de administrador)
        try:
            User.objects.create_user(
                username=username,
                email=email,
                password=password,
                is_staff=False,
                is_superuser=False
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f'✓ Usuario normal "{username}" creado exitosamente!\n'
                    f'  Email: {email}\n'
                    f'  Permisos: Usuario normal (sin acceso al admin)'
                )
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(
                    f'✗ Error al crear usuario normal: {str(e)}'
                )
            )


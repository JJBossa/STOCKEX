from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
import os

User = get_user_model()

class Command(BaseCommand):
    help = 'Crea un superusuario usando variables de entorno si no existe'

    def handle(self, *args, **options):
        # Obtener credenciales de variables de entorno
        username = os.environ.get('SUPERUSER_USERNAME', 'admin')
        email = os.environ.get('SUPERUSER_EMAIL', 'admin@example.com')
        password = os.environ.get('SUPERUSER_PASSWORD')
        
        # Si no hay password en variables de entorno, usar un default
        # IMPORTANTE: En producción, SIEMPRE define SUPERUSER_PASSWORD
        if not password:
            password = os.environ.get('DJANGO_SUPERUSER_PASSWORD', 'admin123')
            self.stdout.write(
                self.style.WARNING(
                    '⚠️  No se encontró SUPERUSER_PASSWORD. Usando valor por defecto.\n'
                    '   ⚠️  IMPORTANTE: Define SUPERUSER_PASSWORD en Render para producción!'
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
        
        # Crear el superusuario
        try:
            User.objects.create_superuser(
                username=username,
                email=email,
                password=password
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f'✓ Superusuario "{username}" creado exitosamente!\n'
                    f'  Email: {email}'
                )
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(
                    f'✗ Error al crear superusuario: {str(e)}'
                )
            )


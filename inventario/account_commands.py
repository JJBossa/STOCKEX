import os
import sys
import warnings
from getpass import GetPassWarning, getpass

from django.contrib.auth.models import Group, User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction


class CrearCuentaCommand(BaseCommand):
    prefijo = ''
    superusuario = False
    grupo = None

    def add_arguments(self, parser):
        parser.add_argument('--username')
        parser.add_argument('--email')
        parser.add_argument('--noinput', '--no-input', action='store_true')

    def handle(self, *args, **options):
        username = options['username'] or os.environ.get(f'{self.prefijo}_USERNAME', '')
        email = options['email'] or os.environ.get(f'{self.prefijo}_EMAIL', '')
        username = User.normalize_username(username.strip())
        if not username:
            raise CommandError('Indica el usuario mediante --username o la variable de entorno.')
        if User.objects.filter(username=username).exists():
            raise CommandError('El usuario ya existe. Usa el procedimiento de cambio de contraseña.')

        variable = f'{self.prefijo}_PASSWORD'
        password = os.environ.get(variable)
        if not password:
            if options['noinput'] or not sys.stdin.isatty():
                raise CommandError(f'Falta {variable} para la creación sin interacción.')
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('error', GetPassWarning)
                    password = getpass('Contraseña: ')
                    confirmation = getpass('Repite la contraseña: ')
            except (EOFError, GetPassWarning, KeyboardInterrupt):
                raise CommandError('Entrada segura cancelada o no disponible.') from None
            if not password or password != confirmation:
                raise CommandError('Las contraseñas deben coincidir y ser obligatorias.')

        usuario = User(
            username=username, email=User.objects.normalize_email(email),
            is_staff=self.superusuario, is_superuser=self.superusuario,
        )
        try:
            usuario.full_clean(exclude=['password'])
            validate_password(password, usuario)
        except ValidationError as error:
            raise CommandError(' '.join(error.messages)) from None

        try:
            with transaction.atomic():
                grupo = None
                if self.grupo:
                    grupo = Group.objects.filter(name=self.grupo).first()
                    if grupo is None:
                        raise CommandError('Configura los roles con crear_grupos_permisos.')
                usuario.set_password(password)
                usuario.save(force_insert=True)
                if grupo is not None:
                    usuario.groups.add(grupo)
        except IntegrityError:
            raise CommandError('No se pudo crear la cuenta. Comprueba si el usuario ya existe.') from None
        self.stdout.write(self.style.SUCCESS('Cuenta creada.'))

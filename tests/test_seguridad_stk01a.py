from io import StringIO

import pytest
from django.contrib.auth import SESSION_KEY
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models.deletion import ProtectedError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from inventario.models import (
    Cliente, CuentaPorCobrar, ItemVenta, NotificacionUsuario, PagoCliente, Venta,
)


pytestmark = pytest.mark.django_db

CLAVE_PRUEBA = 'Zafiro-metrónomo!1976-margen'


@pytest.fixture
def roles():
    call_command('crear_grupos_permisos', stdout=StringIO())
    return (
        Group.objects.get(name='Administrador'),
        Group.objects.get(name='Vendedor'),
    )


@pytest.fixture
def administrador(django_user_model, roles):
    usuario = django_user_model.objects.create_user('admin-operativo')
    usuario.groups.add(roles[0])
    return usuario


@pytest.fixture
def operador(django_user_model, roles):
    usuario = django_user_model.objects.create_user('operador')
    usuario.groups.add(roles[1])
    return usuario


@pytest.fixture
def venta(operador, producto):
    venta = Venta.objects.create(
        usuario=operador, numero_venta='REG-01', subtotal=10000, total=10000,
        metodo_pago='tarjeta',
    )
    ItemVenta.objects.create(
        venta=venta, producto=producto, nombre_producto=producto.nombre,
        cantidad=1, precio_unitario=10000, stock_anterior=51, stock_despues=50,
    )
    return venta


@pytest.fixture
def cuenta(venta):
    cliente = Cliente.objects.create(nombre='Cliente de regresión')
    cuenta = CuentaPorCobrar.objects.create(
        cliente=cliente, venta=venta, monto_total=venta.total,
        fecha_emision=timezone.localdate(), fecha_vencimiento=timezone.localdate(),
    )
    PagoCliente.objects.create(
        cuenta_por_cobrar=cuenta, monto=1000, metodo_pago='efectivo',
        fecha_pago=timezone.localdate(),
    )
    return cuenta


def test_administrador_de_grupo_gestiona_por_html_y_rest(client, administrador, producto):
    client.force_login(administrador)
    assert client.get(reverse('listar_usuarios')).status_code == 200
    assert client.get(reverse('agregar_producto')).status_code == 200
    response = client.patch(
        reverse('api:producto-detail', args=[producto.pk]),
        {'precio': 12500}, content_type='application/json',
    )
    assert response.status_code == 200
    producto.refresh_from_db()
    assert producto.precio == 12500
    assert not administrador.is_superuser


def test_nombre_historico_y_staff_no_conceden_permisos(client, bossa_user, producto):
    bossa_user.is_staff = True
    bossa_user.save(update_fields=['is_staff'])
    client.force_login(bossa_user)
    assert client.get(reverse('listar_usuarios')).status_code == 403
    assert client.post(reverse('eliminar_producto', args=[producto.pk])).status_code == 403
    assert client.delete(reverse('api:producto-detail', args=[producto.pk])).status_code == 403
    assert client.get(reverse('api:venta-list')).status_code == 403


@pytest.mark.parametrize('ruta', ['listar_usuarios', 'agregar_producto', 'procesar_venta'])
def test_anonimo_redirigido_al_login_en_rutas_protegidas(client, ruta):
    response = client.post(reverse(ruta))
    assert response.status_code == 302
    assert response.url.startswith(reverse('login'))


def test_api_rechaza_escritura_anonima(client):
    response = client.post(reverse('api:producto-list'))
    assert response.status_code == 403
    assert response.data['detail'].code == 'not_authenticated'


def test_operador_no_administra_usuarios_ni_su_propia_cuenta(client, operador, admin_user):
    client.force_login(operador)
    data = {'username': operador.username, 'is_superuser': 'on', 'is_staff': 'on'}
    assert client.post(reverse('crear_usuario'), data).status_code == 403
    assert client.post(reverse('editar_usuario', args=[operador.pk]), data).status_code == 403
    assert client.post(reverse('resetear_password', args=[admin_user.pk])).status_code == 403
    operador.refresh_from_db()
    assert not operador.is_superuser and not operador.is_staff


def test_operador_consulta_productos_pero_no_los_modifica(client, operador, producto):
    client.force_login(operador)
    assert client.get(reverse('api:producto-list')).status_code == 200
    assert client.post(reverse('agregar_producto')).status_code == 403
    for ruta in ('editar_producto', 'eliminar_producto', 'actualizar_stock_rapido',
                 'registrar_movimiento_stock'):
        assert client.post(reverse(ruta, args=[producto.pk])).status_code == 403
    assert client.post(reverse('api:producto-list')).status_code == 403
    assert client.patch(reverse('api:producto-detail', args=[producto.pk])).status_code == 403
    assert client.delete(reverse('api:producto-detail', args=[producto.pk])).status_code == 403
    assert client.post(reverse('api:producto-actualizar-stock', args=[producto.pk])).status_code == 403
    producto.refresh_from_db()
    assert producto.stock == 50 and producto.precio == 10000


def test_permiso_heredado_de_almacen_no_concede_edicion_de_catalogo(client, operador, producto):
    grupo = Group.objects.create(name='Almacenero')
    grupo.permissions.add(Permission.objects.get(
        content_type__app_label='inventario', codename='change_producto',
    ))
    operador.groups.add(grupo)
    operador.is_staff = True
    operador.save(update_fields=['is_staff'])
    client.force_login(operador)
    assert client.post(reverse('editar_producto', args=[producto.pk])).status_code == 403
    assert client.patch(reverse('api:producto-detail', args=[producto.pk])).status_code == 403
    assert client.post(reverse('admin:inventario_producto_change', args=[producto.pk])).status_code == 403


def test_historial_por_propietario_en_html_api_y_busqueda(client, operador, administrador, venta):
    otra = Venta.objects.create(
        usuario=administrador, numero_venta='OTRA-VENTA', subtotal=100, total=100,
    )
    client.force_login(operador)
    rutas = ('detalle_venta', 'api:venta-detail', 'imprimir_ticket_venta')
    for ruta in rutas:
        assert client.get(reverse(ruta, args=[venta.pk])).status_code == 200
        assert client.get(reverse(ruta, args=[otra.pk])).status_code == 404
    assert client.get(reverse('busqueda_global_api'), {
        'q': otra.numero_venta, 'tipo': 'ventas',
    }).json() == {'resultados': []}
    client.force_login(administrador)
    assert client.get(reverse('api:venta-detail', args=[venta.pk])).status_code == 200


def test_operador_incluso_staff_no_puede_cancelar_ni_ver_historial_global_en_admin(
    client, operador, venta, cuenta,
):
    operador.is_staff = True
    operador.save(update_fields=['is_staff'])
    client.force_login(operador)
    assert client.post(reverse('cancelar_venta', args=[venta.pk])).status_code == 403
    assert client.get(reverse('admin:inventario_venta_changelist')).status_code == 403
    assert client.get(reverse('detalle_cuenta_cobrar', args=[cuenta.pk])).status_code == 403
    assert client.post(reverse('registrar_pago', args=[cuenta.pk])).status_code == 403
    assert client.post(reverse('procesar_venta')).status_code == 423
    venta.refresh_from_db()
    assert not venta.cancelada


def test_notificaciones_de_fiado_preexistentes_requieren_permiso_actual(client, operador):
    NotificacionUsuario.objects.create(
        usuario=operador, tipo='cuenta_vencida', titulo='Alerta de fiado',
        mensaje='Información de un fiado',
    )
    client.force_login(operador)
    assert client.get(reverse('obtener_notificaciones_api')).json() == {
        'notificaciones': [], 'total': 0,
    }
    response = client.get(reverse('centro_notificaciones'))
    assert response.status_code == 200
    assert not response.context['notificaciones']


def test_superusuario_puede_consultar_pero_no_escribir_operaciones_suspendidas(
    client, admin_user, venta, cuenta,
):
    client.force_login(admin_user)
    assert client.get(reverse('detalle_cuenta_cobrar', args=[cuenta.pk])).status_code == 200
    for ruta, args in [
        ("procesar_venta", []),
        ("convertir_cotizacion_en_venta", [1]),
        ("crear_cuenta_cobrar", []),
        ("registrar_pago", [cuenta.pk]),
        ("crear_devolucion_venta", [venta.pk]),
        ("procesar_devolucion", [1]),
        ("rechazar_devolucion", [1]),
    ]:
        assert client.post(reverse(ruta, args=args)).status_code == 423
    assert client.post(reverse('admin:inventario_venta_add')).status_code == 403
    assert client.post(reverse('admin:inventario_venta_change', args=[venta.pk])).status_code == 403
    assert Venta.objects.count() == 1
    assert PagoCliente.objects.count() == 1

    anulacion = client.post(
        reverse("cancelar_venta", args=[venta.pk]), {"motivo": "Duplicada"}
    )
    assert anulacion.status_code == 409
    venta.refresh_from_db()
    assert not venta.cancelada
    assert not hasattr(venta, "anulacion")


def test_historial_no_se_borra_via_html_api_o_admin(client, admin_user, venta, cuenta):
    client.force_login(admin_user)
    ruta = reverse('limpiar_historial_ventas')
    assert client.get(ruta).status_code == 403
    assert client.post(ruta).status_code == 403
    assert client.delete(reverse('api:venta-detail', args=[venta.pk])).status_code == 405
    for modelo, pk in [
        ('venta', venta.pk), ('itemventa', venta.items.get().pk),
        ('cuentaporcobrar', cuenta.pk), ('pagocliente', cuenta.pagos.get().pk),
    ]:
        assert client.post(reverse(f'admin:inventario_{modelo}_delete', args=[pk]), {
            'post': 'yes',
        }).status_code == 403
    client.post(reverse('admin:inventario_venta_changelist'), {
        'action': 'delete_selected', '_selected_action': venta.pk, 'post': 'yes',
    })
    assert Venta.objects.filter(pk=venta.pk).exists()
    assert venta.items.count() == 1
    assert cuenta.pagos.count() == 1


def test_borrar_cliente_no_borra_fiados_en_cascada(client, administrador, cuenta):
    client.force_login(administrador)
    response = client.post(reverse('eliminar_cliente', args=[cuenta.cliente_id]))
    assert response.status_code == 302
    with pytest.raises(ProtectedError):
        cuenta.cliente.delete()
    assert CuentaPorCobrar.objects.filter(pk=cuenta.pk).exists()
    assert cuenta.pagos.count() == 1


def test_admin_operativo_crea_operador_sin_campos_privilegiados(
    client, administrador, django_user_model, roles,
):
    client.force_login(administrador)
    data = {'username': 'nuevo-operador', 'password': CLAVE_PRUEBA,
            'password_confirm': CLAVE_PRUEBA, 'is_staff': 'on', 'is_superuser': 'on',
            'groups': [roles[0].pk]}
    assert client.post(reverse('crear_usuario'), data).status_code == 302
    nuevo = django_user_model.objects.get(username=data['username'])
    assert nuevo.password != CLAVE_PRUEBA and nuevo.check_password(CLAVE_PRUEBA)
    assert not nuevo.is_staff and not nuevo.is_superuser
    assert list(nuevo.groups.all()) == [roles[1]]


def test_perfil_y_reset_administrativo_protegen_otros_admins(
    client, administrador, operador, admin_user, roles,
):
    client.force_login(administrador)
    for cuenta in (administrador, admin_user):
        for ruta in ('editar_usuario', 'resetear_password', 'eliminar_usuario'):
            assert client.post(reverse(ruta, args=[cuenta.pk])).status_code == 403
    response = client.post(reverse('editar_usuario', args=[operador.pk]), {
        'username': operador.username, 'is_active': 'on', 'is_staff': 'on',
        'is_superuser': 'on', 'groups': [roles[0].pk], 'password': CLAVE_PRUEBA,
    })
    assert response.status_code == 302
    operador.refresh_from_db()
    assert not operador.is_superuser and not operador.is_staff
    assert not operador.has_usable_password()
    assert list(operador.groups.all()) == [roles[1]]


def test_staff_con_permiso_de_usuarios_no_puede_otorgar_roles_via_admin(
    client, administrador, operador,
):
    administrador.is_staff = True
    administrador.save(update_fields=['is_staff'])
    client.force_login(administrador)
    assert client.post(reverse('admin:auth_user_change', args=[operador.pk]), {
        'username': operador.username, 'is_superuser': 'on',
    }).status_code == 403
    assert client.post(reverse('admin:auth_user_password_change', args=[operador.pk])).status_code == 403


@pytest.mark.parametrize('debil', ['1234567890', 'password', 'abc'])
def test_formularios_rechazan_claves_debiles(client, administrador, operador, django_user_model, debil):
    client.force_login(administrador)
    response = client.post(reverse('crear_usuario'), {
        'username': 'cuenta-invalida', 'password': debil, 'password_confirm': debil,
    })
    assert response.status_code == 200
    assert not django_user_model.objects.filter(username='cuenta-invalida').exists()
    hash_anterior = operador.password
    response = client.post(reverse('resetear_password', args=[operador.pk]), {
        'nueva_password': debil, 'confirmar_password': debil,
    })
    assert response.status_code == 200
    operador.refresh_from_db()
    assert operador.password == hash_anterior


def test_reset_guarda_hash_e_invalida_la_sesion(client, administrador, operador):
    sesion_operador = Client()
    sesion_operador.force_login(operador)
    client.force_login(administrador)
    assert client.post(reverse('resetear_password', args=[operador.pk]), {
        'nueva_password': CLAVE_PRUEBA, 'confirmar_password': CLAVE_PRUEBA,
    }).status_code == 302
    operador.refresh_from_db()
    assert operador.password != CLAVE_PRUEBA and operador.check_password(CLAVE_PRUEBA)
    assert sesion_operador.get(reverse('listar_ventas')).status_code == 302


def test_token_de_acceso_previo_al_reset_se_rechaza(api_client, operador):
    from rest_framework_simplejwt.tokens import RefreshToken

    token = RefreshToken.for_user(operador)
    api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
    ruta = reverse('api:venta-list')
    assert api_client.get(ruta).status_code == 200
    operador.set_password(CLAVE_PRUEBA)
    operador.save(update_fields=['password'])
    response = api_client.get(ruta)
    assert response.status_code == 403
    assert response.json()['code'] == 'password_changed'


def test_desactivar_operador_conserva_sus_ventas(client, administrador, operador, venta):
    sesion_operador = Client()
    sesion_operador.force_login(operador)
    client.force_login(administrador)
    ruta = reverse('eliminar_usuario', args=[operador.pk])
    assert client.get(ruta).status_code == 200
    assert client.post(ruta).status_code == 302
    operador.refresh_from_db()
    venta.refresh_from_db()
    assert not operador.is_active
    assert venta.usuario_id == operador.pk
    assert sesion_operador.get(reverse('listar_ventas')).status_code == 302


@pytest.mark.parametrize(('comando', 'prefijo'), [
    ('crear_superusuario', 'SUPERUSER'), ('crear_usuario_normal', 'NORMAL_USER'),
])
def test_comando_exige_credenciales_valida_y_jamas_sobrescribe(
    monkeypatch, django_user_model, roles, comando, prefijo,
):
    salida = StringIO()
    for campo in ('USERNAME', 'EMAIL', 'PASSWORD'):
        monkeypatch.delenv(f'{prefijo}_{campo}', raising=False)
    with pytest.raises(CommandError):
        call_command(comando, '--noinput', stdout=salida)
    with pytest.raises(CommandError):
        call_command(comando, '--noinput', '--username', 'cuenta-cli', stdout=salida)
    monkeypatch.setenv(f'{prefijo}_PASSWORD', '1234567890')
    with pytest.raises(CommandError):
        call_command(comando, '--noinput', '--username', 'cuenta-cli', stdout=salida)
    assert not django_user_model.objects.exists()

    monkeypatch.setenv(f'{prefijo}_PASSWORD', CLAVE_PRUEBA)
    call_command(comando, '--noinput', '--username', 'cuenta-cli', stdout=salida)
    usuario = django_user_model.objects.get(username='cuenta-cli')
    assert usuario.is_superuser == (prefijo == 'SUPERUSER')
    assert usuario.groups.filter(name='Vendedor').exists() == (prefijo == 'NORMAL_USER')
    assert usuario.check_password(CLAVE_PRUEBA)
    hash_anterior = usuario.password
    monkeypatch.setenv(f'{prefijo}_PASSWORD', 'Mirador-Ocaso-72-Atolón!')
    with pytest.raises(CommandError, match='ya existe'):
        call_command(comando, '--noinput', '--username', usuario.username, stdout=salida)
    usuario.refresh_from_db()
    assert usuario.password == hash_anterior
    assert CLAVE_PRUEBA not in salida.getvalue()


def test_logout_via_post_csrf_y_get_no_muta(operador):
    navegador = Client(enforce_csrf_checks=True)
    navegador.force_login(operador)
    assert navegador.get(reverse('inicio')).status_code == 200
    token = navegador.cookies['csrftoken'].value
    ruta = reverse('logout')
    assert navegador.get(ruta).status_code == 405
    assert SESSION_KEY in navegador.session
    assert navegador.post(ruta).status_code == 403
    assert SESSION_KEY in navegador.session
    assert navegador.post(ruta, {'csrfmiddlewaretoken': token}).status_code == 302
    assert SESSION_KEY not in navegador.session
    assert navegador.get(reverse('listar_ventas')).status_code == 302

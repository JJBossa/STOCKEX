from django.contrib import messages
from django.contrib.auth.forms import SetPasswordForm, UserCreationForm
from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.forms import ModelForm
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.debug import sensitive_post_parameters

from .access import permiso_requerido


class UsuarioForm(ModelForm):
    class Meta:
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'is_active')


class CrearUsuarioForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        fields = ('username', 'email', 'first_name', 'last_name')


def usuario_administrable(actor, user_id):
    usuario = get_object_or_404(User, pk=user_id)
    if not actor.is_superuser and (
        usuario == actor
        or usuario.is_staff
        or usuario.is_superuser
        or usuario.user_permissions.exists()
        or usuario.groups.exclude(name='Vendedor').exists()
    ):
        raise PermissionDenied
    return usuario


def mostrar_errores(request, form):
    for error_list in form.errors.values():
        for error in error_list:
            messages.error(request, error)


@permiso_requerido('auth.view_user')
def listar_usuarios(request):
    query = request.GET.get('q', '')
    usuarios = User.objects.order_by('username')
    if query:
        usuarios = usuarios.filter(
            Q(username__icontains=query) | Q(email__icontains=query)
            | Q(first_name__icontains=query) | Q(last_name__icontains=query)
        )
    paginator = Paginator(usuarios, 20)
    return render(request, 'inventario/listar_usuarios.html', {
        'usuarios': paginator.get_page(request.GET.get('page')),
        'query': query,
        'total_usuarios': paginator.count,
    })


@sensitive_post_parameters()
@permiso_requerido('auth.add_user')
def crear_usuario(request):
    if request.method == 'POST':
        data = request.POST.copy()
        data['password1'] = data.get('password', '')
        data['password2'] = data.get('password_confirm', '')
        form = CrearUsuarioForm(data)
        if form.is_valid():
            operador = Group.objects.filter(name='Vendedor').first()
            if operador is None:
                messages.error(request, 'Configura los roles con crear_grupos_permisos.')
            else:
                with transaction.atomic():
                    usuario = form.save()
                    usuario.groups.add(operador)
                messages.success(request, 'Operador creado exitosamente.')
                return redirect('listar_usuarios')
        else:
            mostrar_errores(request, form)
    return render(request, 'inventario/crear_usuario.html')


@permiso_requerido('auth.change_user')
def editar_usuario(request, user_id):
    usuario = usuario_administrable(request.user, user_id)
    if request.method == 'POST':
        data = request.POST.copy()
        if usuario == request.user:
            data['is_active'] = 'on'
        form = UsuarioForm(data, instance=usuario)
        if form.is_valid():
            form.save(commit=False).save(update_fields=UsuarioForm.Meta.fields)
            messages.success(request, 'Usuario actualizado exitosamente.')
            return redirect('listar_usuarios')
        mostrar_errores(request, form)
        usuario.refresh_from_db()
    return render(request, 'inventario/editar_usuario.html', {'usuario': usuario})


@sensitive_post_parameters()
@permiso_requerido('auth.change_user')
def resetear_password(request, user_id):
    usuario = usuario_administrable(request.user, user_id)
    if request.method == 'POST':
        form = SetPasswordForm(usuario, {
            'new_password1': request.POST.get('nueva_password', ''),
            'new_password2': request.POST.get('confirmar_password', ''),
        })
        if form.is_valid():
            form.save(commit=False).save(update_fields=['password'])
            messages.success(request, 'Contraseña actualizada exitosamente.')
            return redirect('listar_usuarios')
        mostrar_errores(request, form)
    return render(request, 'inventario/resetear_password.html', {'usuario': usuario})


@permiso_requerido('auth.change_user')
def eliminar_usuario(request, user_id):
    """Desactiva la cuenta y conserva su atribución en los registros."""
    usuario = usuario_administrable(request.user, user_id)
    if usuario == request.user or usuario.is_superuser:
        raise PermissionDenied
    if request.method == 'POST':
        usuario.is_active = False
        usuario.save(update_fields=['is_active'])
        messages.success(request, 'Usuario desactivado.')
        return redirect('listar_usuarios')
    return render(request, 'inventario/eliminar_usuario.html', {'usuario': usuario})

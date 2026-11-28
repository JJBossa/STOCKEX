import hashlib
import json
from uuid import NAMESPACE_URL, uuid4, uuid5

from django import forms
from django.contrib import messages
from django.db import IntegrityError, OperationalError
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .access import permiso_requerido
from .bloqueo_caja import sqlite_ocupado
from .caja import ErrorCaja, identificador
from .models import Cliente
from .peticion_financiera import ErrorJSON, comprobar_cuenta, leer_json


class AltaCliente(forms.Form):
    nombre = forms.CharField(max_length=200, label="Nombre")
    rut = forms.CharField(max_length=20, required=False, label="RUT")
    telefono = forms.CharField(max_length=50, required=False, label="Teléfono")
    email = forms.EmailField(required=False, label="Correo")
    limite_credito = forms.DecimalField(
        max_digits=12,
        decimal_places=0,
        min_value=0,
        required=False,
        label="Límite de crédito (CLP)",
    )
    notas = forms.CharField(max_length=500, required=False, label="Observaciones")
    tipo_cliente = forms.ChoiceField(
        choices=Cliente.TIPO_CLIENTE_CHOICES, required=False
    )
    direccion = forms.CharField(required=False)
    contacto = forms.CharField(max_length=200, required=False)


def guardar_cliente(usuario, parametros, clave):
    formulario = AltaCliente(parametros)
    if not formulario.is_valid():
        campo, errores = next(iter(formulario.errors.items()))
        raise ErrorCaja("cliente_invalido", errores[0], campo=campo)
    datos = {campo: valor or None for campo, valor in formulario.cleaned_data.items()}
    datos["tipo_cliente"] = datos["tipo_cliente"] or "natural"
    datos["limite_credito"] = int(datos["limite_credito"] or 0)
    try:
        cuerpo = json.dumps(datos, sort_keys=True, ensure_ascii=False).encode()
    except UnicodeEncodeError as error:
        raise ErrorCaja(
            "cliente_invalido", "Revisa los caracteres ingresados."
        ) from error
    if not clave:
        # Mantiene el contrato HTML de los clientes anteriores al formulario con clave.
        return Cliente.objects.create(**datos), True
    clave = identificador(clave, "Idempotency-Key")
    identificador_alta = uuid5(
        NAMESPACE_URL, f"stockex:alta-cliente:{usuario.pk}:{clave}"
    )
    huella = hashlib.sha256(cuerpo).hexdigest()
    cliente, creada = Cliente.objects.get_or_create(
        clave_alta=identificador_alta, defaults={**datos, "huella_alta": huella}
    )
    if cliente.huella_alta != huella:
        raise ErrorCaja(
            "clave_en_conflicto",
            "Esta clave de alta ya se usó con otros datos.",
            estado=409,
        )
    return cliente, creada


@never_cache
@permiso_requerido("inventario.add_cliente", administrativo=True)
@require_http_methods(["GET", "POST"])
def crear_cliente(request):
    clave = (
        request.POST.get("clave_alta")
        if request.content_type != "application/json"
        else None
    )
    if request.method == "POST":
        api = request.content_type == "application/json"
        try:
            if api:
                comprobar_cuenta(request)
                datos = leer_json(request)
                clave = request.headers.get("Idempotency-Key")
                if not clave:
                    raise ErrorCaja("clave_invalida", "Envía la clave de alta.")
                if not isinstance(datos, dict) or any(
                    campo not in AltaCliente.base_fields or not isinstance(valor, str)
                    for campo, valor in datos.items()
                ):
                    raise ErrorCaja(
                        "campos_invalidos", "Revisa los campos del cliente."
                    )
            else:
                datos = request.POST
            cliente, creada = guardar_cliente(request.user, datos, clave)
            if api:
                return JsonResponse(
                    {
                        "id": cliente.pk,
                        "nombre": cliente.nombre,
                        "rut": cliente.rut,
                        "activo": cliente.activo,
                        "repetida": not creada,
                    },
                    status=201 if creada else 200,
                )
            messages.success(request, "Cliente registrado.")
            return redirect("detalle_cliente", cliente_id=cliente.pk)
        except ErrorJSON as error:
            return JsonResponse({"error": error.codigo}, status=error.estado)
        except IntegrityError:
            error = ErrorCaja(
                "rut_en_conflicto", "Revisa que el RUT no esté registrado.", estado=409
            )
        except OperationalError as error_db:
            if not sqlite_ocupado(error_db):
                raise
            error = ErrorCaja(
                "base_ocupada",
                "La base está ocupada. Reintenta la misma solicitud.",
                estado=503,
            )
        except ErrorCaja as error_caja:
            error = error_caja
        if api:
            return JsonResponse(error.datos, status=error.estado)
        messages.error(request, error.datos["mensaje"])
    return render(
        request,
        "inventario/crear_cliente.html",
        {
            "datos": request.POST,
            "clave_alta": clave or str(uuid4()),
        },
    )

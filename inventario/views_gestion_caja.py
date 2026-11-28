from functools import wraps

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from . import caja
from .bloqueo_caja import sesion_activa
from .views_caja import (
    CLASIFICACIONES,
    METODOS,
    contexto_cierre,
    cursor_pagina,
    pagos_resumen,
    recibido_resumen,
)

IMPORTES = {
    "total_vigente": "Total vendido",
    "monto_anulado": "Importe anulado",
    "efectivo_inicial": "Efectivo inicial",
    "ingresos": "Ingresos adicionales",
    "retiros": "Retiros",
    "efectivo_esperado": "Efectivo esperado",
}
CANTIDADES = {
    "cantidad_vigente": "Ventas vigentes",
    "cantidad_anulada": "Ventas anuladas",
    "cantidad_ingresos": "Cantidad de ingresos",
    "cantidad_retiros": "Cantidad de retiros",
}


def consulta_html(*permisos):
    def decorar(vista):
        @never_cache
        @login_required
        @require_GET
        @wraps(vista)
        def consultar(request, *args, **kwargs):
            if not any(request.user.has_perm(permiso) for permiso in permisos):
                raise PermissionDenied
            try:
                return vista(request, *args, **kwargs)
            except caja.ErrorCaja as error:
                return render(
                    request,
                    "inventario/caja/error.html",
                    {"mensaje": error.datos["mensaje"]},
                    status=error.estado,
                )

        return consultar

    return decorar


def metricas_resumen(resumen):
    metricas = [
        (etiqueta, resumen[campo], True) for campo, etiqueta in IMPORTES.items()
    ]
    metricas.extend(
        (etiqueta, resumen[campo], False) for campo, etiqueta in CANTIDADES.items()
    )
    for metodo, pago in resumen["por_metodo"].items():
        nombre = METODOS.get(metodo, metodo)
        metricas.extend(
            [
                (f"{nombre} · importe", pago["importe"], True),
                (f"{nombre} · ventas", pago["cantidad"], False),
            ]
        )
    if "abonos" in resumen:
        abonos = resumen["abonos"]
        metricas.extend(
            [
                ("Abonos recibidos", abonos["importe"], True),
                ("Cantidad de abonos", abonos["cantidad"], False),
            ]
        )
        for metodo, pago in abonos["por_metodo"].items():
            metricas.extend(
                [
                    (f"{METODOS[metodo]} · abonos", pago["importe"], True),
                    (
                        f"{METODOS[metodo]} · cantidad de abonos",
                        pago["cantidad"],
                        False,
                    ),
                ]
            )
    return [(etiqueta, str(valor), importe) for etiqueta, valor, importe in metricas]


@consulta_html(caja.CONSULTAR_CAJA, caja.ABRIR_CAJA)
def gestion(request):
    consulta = request.user.has_perm(caja.CONSULTAR_CAJA)
    sesion, resumen = caja.consultar_caja(request.user) if consulta else (None, None)
    abierta = sesion is not None if consulta else sesion_activa().exists()
    estado = {"abierta": abierta, "cuenta": str(request.user.pk)}
    if sesion is not None:
        estado.update(
            id=str(sesion.pk),
            huella=str(sesion.version_resumen),
            esperado=str(resumen["efectivo_esperado"]),
            metricas=metricas_resumen(resumen),
        )
    contexto = {
        "abierta": abierta,
        "sesion": sesion,
        "resumen": resumen,
        "pagos": pagos_resumen(resumen) if resumen is not None else [],
        "recibido": recibido_resumen(resumen) if resumen is not None else [],
        "estado": estado,
        "max_importe": caja.MAX_IMPORTE,
        "max_contado": caja.MAX_CONTADO,
    }
    plantilla = (
        "inventario/caja/estado.html"
        if request.GET.get("fragmento") == "resumen"
        else "inventario/caja/gestion.html"
    )
    return render(request, plantilla, contexto)


class FiltrosCierres(forms.Form):
    desde = forms.DateField(
        label="Cerrado desde",
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    hasta = forms.DateField(
        label="Cerrado hasta",
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    clasificacion = forms.ChoiceField(
        label="Clasificación",
        required=False,
        choices=[("", "Todas"), *CLASIFICACIONES.items()],
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def clean(self):
        datos = super().clean()
        desde, hasta = datos.get("desde"), datos.get("hasta")
        if desde and hasta and desde > hasta:
            raise forms.ValidationError(
                "La fecha inicial debe ser anterior o igual a la final."
            )
        return datos


def enlace_siguiente(request, cursor):
    if cursor is None:
        return ""
    parametros = request.GET.copy()
    parametros["antes_de"] = cursor
    return "?" + parametros.urlencode()


@consulta_html(caja.CONSULTAR_CIERRES)
def historial(request):
    filtros = FiltrosCierres(request.GET)
    cierres, siguiente = (
        caja.listar_cierres(
            request.user, cursor_pagina(request), **filtros.cleaned_data
        )
        if filtros.is_valid()
        else ([], None)
    )
    return render(
        request,
        "inventario/caja/historial.html",
        {
            "filtros": filtros,
            "cierres": cierres,
            "siguiente": enlace_siguiente(request, siguiente),
        },
        status=200 if filtros.is_valid() else 400,
    )


@consulta_html(caja.CONSULTAR_CIERRES)
def detalle(request, sesion_id):
    sesion = caja.consultar_cierre(request.user, sesion_id)
    return render(
        request,
        "inventario/caja/detalle.html",
        contexto_cierre(sesion),
    )


@consulta_html(caja.CONSULTAR_CAJA, caja.CONSULTAR_CIERRES)
def movimientos(request, sesion_id):
    sesion, registros, siguiente = caja.listar_movimientos(
        request.user, sesion_id, cursor_pagina(request)
    )
    return render(
        request,
        "inventario/caja/movimientos.html",
        {
            "sesion": sesion,
            "movimientos": registros,
            "siguiente": enlace_siguiente(request, siguiente),
        },
    )

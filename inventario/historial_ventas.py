from calendar import monthrange
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from django import forms
from django.contrib.auth.models import User
from django.db.models import BigIntegerField, Count, Exists, OuterRef, Q, Sum
from django.db.models.functions import Cast
from django.http import QueryDict
from django.utils import timezone

from .models import Venta

SANTIAGO = ZoneInfo("America/Santiago")
PERIODOS = (
    ("hoy", "Hoy"),
    ("ayer", "Ayer"),
    ("semana", "Últimos 7 días"),
    ("mes", "Mes actual"),
    ("todas", "Todas las fechas"),
    ("personalizado", "Rango personalizado"),
)


def inicio_dia_chileno(dia):
    return datetime.combine(dia, time.min, tzinfo=SANTIAGO).astimezone(UTC)


def limites_periodo(periodo, desde=None, hasta=None):
    """Devuelve límites UTC semiabiertos a partir de fechas civiles de Chile."""
    hoy = timezone.localdate(timezone=SANTIAGO)
    if periodo == "hoy":
        desde = hasta = hoy
    elif periodo == "ayer":
        desde = hasta = hoy - timedelta(days=1)
    elif periodo == "semana":
        desde, hasta = hoy - timedelta(days=6), hoy
    elif periodo == "mes":
        desde = hoy.replace(day=1)
        hasta = hoy.replace(day=monthrange(hoy.year, hoy.month)[1])
    elif periodo == "todas":
        return None, None

    return (
        inicio_dia_chileno(desde) if desde else None,
        inicio_dia_chileno(hasta + timedelta(days=1)) if hasta else None,
    )


class FiltrosHistorialVentas(forms.Form):
    periodo = forms.ChoiceField(
        label="Período", choices=PERIODOS, widget=forms.RadioSelect
    )
    fecha_desde = forms.DateField(
        label="Desde",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        input_formats=["%Y-%m-%d"],
    )
    fecha_hasta = forms.DateField(
        label="Hasta",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        input_formats=["%Y-%m-%d"],
    )
    metodo_pago = forms.ChoiceField(
        label="Método de pago",
        choices=[("", "Todos"), *Venta.METODO_PAGO_CHOICES],
        required=False,
    )
    numero_venta = forms.CharField(
        label="Número de venta", max_length=50, required=False
    )
    modalidad = forms.ChoiceField(
        choices=[
            ("", "Todas"),
            *Venta.Modalidad.choices,
            ("historica", "Sin clasificar"),
        ],
        required=False,
    )
    estado = forms.ChoiceField(
        choices=[("", "Todos"), ("vigente", "Vigente"), ("anulada", "Anulada")],
        required=False,
    )
    vendedor = forms.ModelChoiceField(
        queryset=User.objects.none(), empty_label="Todos", required=False
    )

    def __init__(self, parametros, *, es_admin):
        datos = parametros.copy()
        if "periodo" not in datos:
            datos["periodo"] = (
                "personalizado"
                if datos.get("fecha_desde") or datos.get("fecha_hasta")
                else "hoy"
            )
        super().__init__(datos, label_suffix="")
        if es_admin:
            tiene_ventas = Venta.objects.filter(usuario_id=OuterRef("pk"))
            self.fields["vendedor"].queryset = (
                User.objects.filter(Exists(tiene_ventas))
                .only("username")
                .order_by("username")
            )
        else:
            del self.fields["vendedor"]
        for campo in self.fields.values():
            if isinstance(campo.widget, forms.Select):
                campo.widget.attrs["class"] = "form-select form-select-sm"
            elif not isinstance(campo.widget, forms.RadioSelect):
                campo.widget.attrs["class"] = "form-control form-control-sm"

    def clean(self):
        datos = super().clean()
        if datos.get("periodo") != "personalizado":
            return datos
        desde, hasta = datos.get("fecha_desde"), datos.get("fecha_hasta")
        if not desde and not hasta and not self.errors:
            raise forms.ValidationError(
                "Indica al menos una fecha para el rango personalizado."
            )
        if desde and hasta and desde > hasta:
            self.add_error(
                "fecha_hasta", "La fecha final debe ser igual o posterior a la inicial."
            )
        if hasta == date.max:
            self.add_error(
                "fecha_hasta", "Indica una fecha final anterior al 31/12/9999."
            )
        return datos

    def aplicar(self, ventas):
        if not self.is_valid():
            return ventas.none()

        datos = self.cleaned_data
        personalizado = datos["periodo"] == "personalizado"
        inicio, fin = limites_periodo(
            datos["periodo"],
            datos.get("fecha_desde") if personalizado else None,
            datos.get("fecha_hasta") if personalizado else None,
        )
        filtros = {}
        if inicio:
            filtros["fecha__gte"] = inicio
        if fin:
            filtros["fecha__lt"] = fin
        if datos["metodo_pago"]:
            filtros["metodo_pago"] = datos["metodo_pago"]
        if datos["numero_venta"]:
            filtros["numero_venta__icontains"] = datos["numero_venta"]
        modalidad = datos["modalidad"]
        if modalidad:
            if modalidad == "historica":
                filtros["modalidad__isnull"] = True
            else:
                filtros["modalidad"] = modalidad
        if datos["estado"]:
            filtros["cancelada"] = datos["estado"] == "anulada"
        if datos.get("vendedor"):
            filtros["usuario"] = datos["vendedor"]
        return ventas.filter(**filtros)

    def parametros(self, *, incluir_pagina=True):
        parametros = QueryDict(mutable=True)
        campos = [*self.fields, "page"] if incluir_pagina else self.fields
        for campo in campos:
            if self.data.get(campo):
                parametros[campo] = self.data[campo]
        return parametros


@dataclass(frozen=True)
class TotalesPago:
    metodo: str
    etiqueta: str
    total: int
    cantidad: int


@dataclass(frozen=True)
class ResumenVentas:
    total_vigente: int
    cantidad_vigente: int
    promedio: Decimal
    monto_anulado: int
    cantidad_anulada: int
    pagos: tuple[TotalesPago, ...]


def resumir_ventas(ventas):
    """Agrega el queryset autorizado y filtrado antes de paginarlo."""
    vigente = Q(cancelada=False)
    anulada = Q(cancelada=True)
    monto = Cast("total", BigIntegerField())
    operaciones = {
        "total_vigente": Sum(monto, filter=vigente, default=0),
        "cantidad_vigente": Count("pk", filter=vigente),
        "monto_anulado": Sum(monto, filter=anulada, default=0),
        "cantidad_anulada": Count("pk", filter=anulada),
    }
    metodos = dict(Venta.METODO_PAGO_CHOICES)
    por_metodo = {metodo: Q(metodo_pago=metodo) for metodo in metodos}
    por_metodo["otros"] = ~Q(metodo_pago__in=metodos)
    for metodo, condicion in por_metodo.items():
        operaciones[f"total_{metodo}"] = Sum(
            monto, filter=vigente & condicion, default=0
        )
        operaciones[f"cantidad_{metodo}"] = Count("pk", filter=vigente & condicion)

    totales = ventas.aggregate(**operaciones)
    total, cantidad = int(totales["total_vigente"]), totales["cantidad_vigente"]
    promedio = (
        (Decimal(total) / cantidad).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if cantidad
        else Decimal(0)
    )
    pagos = tuple(
        TotalesPago(
            metodo,
            etiqueta,
            int(totales[f"total_{metodo}"]),
            totales[f"cantidad_{metodo}"],
        )
        for metodo, etiqueta in [*metodos.items(), ("otros", "Otros históricos")]
        if metodo != "otros" or totales["cantidad_otros"]
    )
    return ResumenVentas(
        total,
        cantidad,
        promedio,
        int(totales["monto_anulado"]),
        totales["cantidad_anulada"],
        pagos,
    )

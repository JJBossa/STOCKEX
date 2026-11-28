from decimal import Decimal

from django import template

register = template.Library()
SEPARADORES_CL = str.maketrans(",.", ".,")


@register.filter
def clp(importe, decimales=0):
    return "$" + format(Decimal(importe), f",.{decimales}f").translate(SEPARADORES_CL)

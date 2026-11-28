import sqlite3
from uuid import uuid4

from django.db import connection

from .models import BloqueoCaja, SesionCaja


def bloquear_caja():
    """Adquiere el primer bloqueo financiero dentro de la transacción."""
    fila = BloqueoCaja.objects.filter(pk=1)
    if connection.vendor == "sqlite":
        # Incluso si falta la fila, UPDATE adquiere el bloqueo de escritor antes de leer.
        if not fila.update(id=1):
            BloqueoCaja.objects.create(pk=1)
        return

    try:
        fila.select_for_update().get()
    except BloqueoCaja.DoesNotExist:
        # Recupera la fila si un flush dejó la base sin la semilla de la migración.
        BloqueoCaja.objects.get_or_create(pk=1)
        fila.select_for_update().get()


def sesion_activa():
    return SesionCaja.objects.filter(cerrada_en__isnull=True)


def invalidar_resumen(sesion_id):
    SesionCaja.objects.filter(pk=sesion_id).update(version_resumen=uuid4())


def sqlite_ocupado(error):
    codigo = getattr(error.__cause__, "sqlite_errorcode", 0)
    return connection.vendor == "sqlite" and (codigo & 0xFF) in (
        sqlite3.SQLITE_BUSY,
        sqlite3.SQLITE_LOCKED,
    )

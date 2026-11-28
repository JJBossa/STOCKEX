from uuid import uuid4

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.urls import reverse
from django.utils import timezone

from inventario import caja, fiados
from inventario.models import CuentaPorCobrar, PagoCliente, SesionCaja

from .test_caja import abrir
from .test_fiados import fiar, pagar


@pytest.mark.django_db(transaction=True)
def test_0022_conserva_historia_y_protege_reversion(admin_user, client):
    anterior = [("inventario", "0021_nucleo_cierres_caja")]
    nueva = [("inventario", "0022_nucleo_fiados_abonos")]
    ejecutor = MigrationExecutor(connection)
    esquema_final = ejecutor.loader.graph.leaf_nodes()
    ejecutor.migrate(anterior)
    apps = ejecutor.loader.project_state(anterior).apps
    ClienteAnterior = apps.get_model("inventario", "Cliente")
    VentaAnterior = apps.get_model("inventario", "Venta")
    CuentaAnterior = apps.get_model("inventario", "CuentaPorCobrar")
    PagoAnterior = apps.get_model("inventario", "PagoCliente")
    SesionAnterior = apps.get_model("inventario", "SesionCaja")
    cliente = ClienteAnterior.objects.create(nombre="Histórico", limite_credito=-1)
    hoy = timezone.localdate()
    esperado = {
        "efectivo_inicial": 0,
        "efectivo_esperado": 0,
        "cantidad_vigente": 0,
        "total_vigente": 0,
        "por_metodo": {
            m: {"cantidad": 0, "importe": 0}
            for m in ("efectivo", "tarjeta", "transferencia", "credito", "mixto")
        },
        "cantidad_anulada": 0,
        "monto_anulado": 0,
        "ingresos": 0,
        "retiros": 0,
        "cantidad_ingresos": 0,
        "cantidad_retiros": 0,
        "diferencia": 0,
        "clasificacion": "cuadrada",
    }
    cerrada = SesionAnterior.objects.create(
        abierta_por_id=admin_user.pk,
        clave_apertura=uuid4(),
        efectivo_inicial=0,
        cerrada_por_id=admin_user.pk,
        cerrada_en=timezone.now(),
        efectivo_contado=0,
        clave_cierre=uuid4(),
        resumen_cierre=esperado,
    )
    venta = VentaAnterior.objects.create(
        cliente_id=cliente.pk,
        metodo_pago="credito",
        es_credito=True,
        total=100,
        numero_venta="V-HISTORICA-STK07",
        sesion_caja_id=cerrada.pk,
    )
    cuenta = CuentaAnterior.objects.create(
        cliente_id=cliente.pk,
        venta_id=venta.pk,
        numero_documento="CC-VENCIDA",
        monto_total=100,
        monto_pagado=125,
        estado="vencido",
        fecha_emision=hoy,
        fecha_vencimiento=hoy,
    )
    otra = CuentaAnterior.objects.create(
        cliente_id=cliente.pk,
        venta_id=venta.pk,
        numero_documento="CC-DUPLICADA",
        monto_total=100,
        fecha_emision=hoy,
        fecha_vencimiento=hoy,
    )
    pago = PagoAnterior.objects.create(
        cuenta_por_cobrar_id=cuenta.pk, fecha_pago=hoy, metodo_pago="otro", monto=125
    )
    modelos = (
        CuentaAnterior,
        PagoAnterior,
        VentaAnterior,
        SesionAnterior,
        ClienteAnterior,
    )
    pks = (cuenta.pk, pago.pk, venta.pk, cerrada.pk, cliente.pk)
    originales = [
        modelo.objects.values().get(pk=pk) for modelo, pk in zip(modelos, pks)
    ]
    try:
        MigrationExecutor(connection).migrate(nueva)
        migrada = CuentaPorCobrar.objects.get(pk=cuenta.pk)
        assert (
            migrada.estado == "vencido"
            and migrada.monto_pagado == 125
            and not migrada.fiado_seguro
        )
        assert (
            fiados.obtener_cuenta(cuenta.pk).inconsistente
            and fiados.obtener_cuenta(otra.pk).inconsistente
        )
        assert PagoCliente.objects.get(pk=pago.pk).sesion_caja_id is None
        assert caja.consultar_cierre(admin_user, cerrada.pk).resumen_cierre == esperado
        client.force_login(admin_user)
        detalle = client.get(reverse("caja_historial_detalle", args=[cerrada.pk]))
        assert (
            detalle.status_code == 200
            and "Ventas fiadas y cobros" not in detalle.content.decode()
        )
        MigrationExecutor(connection).migrate(anterior)
        assert originales == [
            modelo.objects.values().get(pk=pk) for modelo, pk in zip(modelos, pks)
        ]

        MigrationExecutor(connection).migrate(esquema_final)
        from inventario.models import Cliente

        abierto = abrir(admin_user)
        nueva_cliente = Cliente.objects.create(nombre="Nueva")
        _, deuda = fiar(admin_user, nueva_cliente)
        confirmado = pagar(admin_user, deuda, 25).registro
        with pytest.raises(RuntimeError, match="Conserva 0022"):
            MigrationExecutor(connection).migrate(anterior)
        assert PagoCliente.objects.get(pk=confirmado.pk).sesion_caja_id == abierto.pk
        assert SesionCaja.objects.get(pk=cerrada.pk).resumen_cierre == esperado
    finally:
        MigrationExecutor(connection).migrate(esquema_final)

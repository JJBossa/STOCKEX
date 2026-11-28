from django.conf import settings
from django.db import migrations, models
from django.db.models import deletion


def asignar_permiso(apps, schema_editor):
    alias = schema_editor.connection.alias
    tipo, _ = (
        apps.get_model("contenttypes", "ContentType")
        .objects.using(alias)
        .get_or_create(app_label="inventario", model="venta")
    )
    permiso, _ = (
        apps.get_model("auth", "Permission")
        .objects.using(alias)
        .get_or_create(
            content_type=tipo,
            codename="anular_venta",
            defaults={"name": "Puede anular ventas de punto de venta"},
        )
    )
    grupo, _ = (
        apps.get_model("auth", "Group")
        .objects.using(alias)
        .get_or_create(name="Administrador")
    )
    grupo.permissions.add(permiso)


def retirar_permiso(apps, schema_editor):
    apps.get_model("auth", "Permission").objects.using(
        schema_editor.connection.alias
    ).filter(
        content_type__app_label="inventario",
        content_type__model="venta",
        codename="anular_venta",
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("inventario", "0019_venta_historial_fecha"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="venta",
            options={
                "verbose_name": "Venta",
                "verbose_name_plural": "Ventas",
                "ordering": ["-fecha"],
                "permissions": (
                    ("registrar_venta", "Puede registrar ventas de punto de venta"),
                    ("anular_venta", "Puede anular ventas de punto de venta"),
                ),
            },
        ),
        migrations.CreateModel(
            name="AnulacionVenta",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("fecha", models.DateTimeField(auto_now_add=True)),
                ("motivo", models.CharField(max_length=250)),
                (
                    "usuario",
                    models.ForeignKey(
                        on_delete=deletion.PROTECT, to=settings.AUTH_USER_MODEL
                    ),
                ),
                (
                    "venta",
                    models.OneToOneField(
                        on_delete=deletion.PROTECT,
                        related_name="anulacion",
                        to="inventario.venta",
                    ),
                ),
            ],
            options={
                "constraints": (
                    models.CheckConstraint(
                        condition=~models.Q(motivo=""),
                        name="anulacion_venta_motivo_no_vacio",
                    ),
                )
            },
        ),
        migrations.RunPython(asignar_permiso, retirar_permiso),
    ]

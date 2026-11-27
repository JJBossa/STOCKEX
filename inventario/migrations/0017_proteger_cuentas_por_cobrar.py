import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('inventario', '0016_producto_inventario__nombre_2dddb1_idx_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='cuentaporcobrar',
            name='cliente',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='cuentas_por_cobrar',
                to='inventario.cliente',
                verbose_name='Cliente',
            ),
        ),
    ]

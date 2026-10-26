import django.core.validators
import django.db.models.deletion
from decimal import Decimal

from django.conf import settings
from django.db import migrations, models


def copiar_multiplicador_actual(apps, schema_editor):
    """Los feriados ya cargados guardan el multiplicador vigente hoy en el parámetro."""
    Parametro = apps.get_model("agenda", "Parametro")
    Feriado = apps.get_model("agenda", "Feriado")
    fila = Parametro.objects.filter(clave="multiplicador_feriado").first()
    valor = fila.valor if fila else Decimal("2")
    Feriado.objects.filter(multiplicador__isnull=True).update(multiplicador=valor)


class Migration(migrations.Migration):

    dependencies = [
        ("agenda", "0002_retiros_auditoria_notificaciones"),
    ]

    operations = [
        migrations.AddField(
            model_name="feriado",
            name="multiplicador",
            field=models.DecimalField(decimal_places=2, max_digits=5, null=True),
        ),
        migrations.RunPython(copiar_multiplicador_actual, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="feriado",
            name="multiplicador",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Si se deja vacío, toma el multiplicador por defecto de los parámetros.",
                max_digits=5,
                validators=[django.core.validators.MinValueValidator(1)],
            ),
        ),
        migrations.AlterField(
            model_name="parametro",
            name="clave",
            field=models.CharField(
                choices=[
                    ("tolerancia_minutos", "Tolerancia de entrada/salida (minutos)"),
                    ("anulacion_fichaje_minutos", "Plazo del empleado para anular fichajes y modificar/anular retiros (minutos)"),
                    ("multiplicador_feriado", "Multiplicador por defecto para feriados nuevos"),
                ],
                max_length=40,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name="tarifahora",
            name="empleado",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="tarifas", to=settings.AUTH_USER_MODEL
            ),
        ),
    ]

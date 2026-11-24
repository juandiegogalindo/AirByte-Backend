from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cuentas", "0002_perfil_usuario"),
    ]

    operations = [
        migrations.AddField(
            model_name="perfilusuario",
            name="consentimiento_aceptado_en",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="perfilusuario",
            name="consentimiento_version",
            field=models.CharField(blank=True, max_length=30),
        ),
    ]

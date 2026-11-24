from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cuentas", "0003_perfil_consentimiento"),
    ]

    operations = [
        migrations.AlterField(
            model_name="perfilusuario",
            name="consentimiento_version",
            field=models.CharField(blank=True, default="", max_length=30),
        ),
    ]

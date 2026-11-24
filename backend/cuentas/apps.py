from django.apps import AppConfig
from django.db.models.signals import post_migrate


def conceder_permiso_sanciones(sender, using, **kwargs):
    from django.contrib.auth.models import Group, Permission
    grupo, _ = Group.objects.using(using).get_or_create(name="Moderadores")
    permiso = Permission.objects.using(using).filter(
        content_type__app_label="cuentas", codename="gestionar_sanciones").first()
    if permiso:
        grupo.permissions.add(permiso)


class CuentasConfig(AppConfig):
    name = "cuentas"

    def ready(self):
        post_migrate.connect(conceder_permiso_sanciones, sender=self)

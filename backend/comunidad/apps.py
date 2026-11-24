from django.apps import AppConfig
from django.db.models.signals import post_migrate


def crear_moderadores(sender, using, **kwargs):
    from django.contrib.auth.models import Group, Permission
    grupo, _ = Group.objects.using(using).get_or_create(name="Moderadores")
    permisos = Permission.objects.using(using).filter(content_type__app_label="comunidad",
        codename__in=["view_reporte", "view_comentario", "ocultar_reporte", "ocultar_comentario"])
    grupo.permissions.add(*permisos)


class ComunidadConfig(AppConfig):
    name = "comunidad"

    def ready(self):
        post_migrate.connect(crear_moderadores, sender=self)

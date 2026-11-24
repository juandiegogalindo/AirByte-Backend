import uuid

from django.conf import settings
from django.db import models


def ruta_foto_perfil(instancia, nombre):
    extension = nombre.rsplit(".", 1)[-1].lower()
    return f"perfiles/{instancia.usuario_id}/{uuid.uuid4().hex}.{extension}"


class IdentidadGoogle(models.Model):
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    google_sub = models.CharField(max_length=255, unique=True)
    vinculada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "cuentas_identidad_google"


class PerfilUsuario(models.Model):
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    foto = models.FileField(upload_to=ruta_foto_perfil, blank=True)
    consentimiento_aceptado_en = models.DateTimeField(blank=True, null=True)
    consentimiento_version = models.CharField(max_length=30, blank=True, default="")

    class Meta:
        db_table = "cuentas_perfil_usuario"


class SancionCuenta(models.Model):
    SUSPENSION = "suspension"
    BANEO = "baneo"
    TIPOS = [(SUSPENSION, "Suspensión"), (BANEO, "Baneo")]

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="sanciones_recibidas")
    tipo = models.CharField(max_length=16, choices=TIPOS)
    motivo = models.CharField(max_length=500)
    creada_en = models.DateTimeField(auto_now_add=True)
    vence_en = models.DateTimeField(null=True, blank=True)
    activa = models.BooleanField(default=True)
    moderador = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                  related_name="sanciones_aplicadas", on_delete=models.SET_NULL)
    levantada_en = models.DateTimeField(null=True, blank=True)
    levantada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                      related_name="sanciones_levantadas", on_delete=models.SET_NULL)

    class Meta:
        permissions = [("gestionar_sanciones", "Puede suspender y banear cuentas")]
        indexes = [models.Index(fields=["usuario", "-creada_en"], name="sancion_usuario_fecha")]
        constraints = [models.UniqueConstraint(fields=["usuario"], condition=models.Q(activa=True),
                                                name="sancion_activa_por_usuario")]

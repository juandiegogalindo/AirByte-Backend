from django.conf import settings
from django.db import models


class Publicacion(models.Model):
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    texto = models.TextField()
    creado_en = models.DateTimeField(auto_now_add=True)
    oculto = models.BooleanField(default=False)
    ocultado_en = models.DateTimeField(null=True, blank=True)
    ocultado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     related_name="+", on_delete=models.SET_NULL)

    class Meta:
        abstract = True


class Reporte(Publicacion):
    localidad = models.ForeignKey("aire.Localidad", on_delete=models.PROTECT)
    categoria = models.CharField(max_length=16, choices=[(c, c) for c in ("olor", "humo", "quema", "otro")])

    class Meta:
        permissions = [("ocultar_reporte", "Puede ocultar reportes")]
        indexes = [models.Index(fields=["localidad", "-creado_en", "-id"], condition=models.Q(oculto=False),
                                name="muro_localidad")]


class Comentario(Publicacion):
    reporte = models.ForeignKey(Reporte, on_delete=models.CASCADE)

    class Meta:
        permissions = [("ocultar_comentario", "Puede ocultar comentarios")]
        indexes = [models.Index(fields=["reporte", "creado_en", "id"], name="hilo_reporte")]

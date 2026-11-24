from django.db import models


class Localidad(models.Model):
    slug = models.SlugField(unique=True)
    nombre = models.CharField(max_length=80)

    def __str__(self):
        return self.nombre


class Estacion(models.Model):
    slug = models.SlugField(unique=True)
    nombre = models.CharField(max_length=80)
    nombre_modelo = models.CharField(max_length=80, unique=True)
    latitud = models.FloatField()
    longitud = models.FloatField()
    localidad = models.ForeignKey(Localidad, on_delete=models.PROTECT)

    def __str__(self):
        return self.nombre


class VersionHistorico(models.Model):
    codigo = models.SlugField(unique=True)
    sha256 = models.CharField(max_length=64)
    fuente = models.CharField(max_length=255)
    fecha_carga = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "aire_version_historico"


class MedicionHoraria(models.Model):
    version = models.ForeignKey(VersionHistorico, on_delete=models.PROTECT)
    estacion = models.ForeignKey(Estacion, on_delete=models.PROTECT)
    instante = models.DateTimeField()
    pm25 = models.FloatField(null=True)
    pm10 = models.FloatField(null=True)
    precipitacion = models.FloatField(null=True)
    temperatura = models.FloatField(null=True)
    vel_viento = models.FloatField(null=True)
    dir_viento = models.FloatField(null=True)
    archivo_origen = models.CharField(max_length=255)

    class Meta:
        db_table = "aire_medicion_horaria"
        constraints = [models.UniqueConstraint(fields=["version", "estacion", "instante"], name="hora_por_version_estacion")]
        indexes = [models.Index(fields=["version", "estacion", "-instante"], condition=models.Q(pm25__isnull=False), name="ultima_lectura_pm25")]

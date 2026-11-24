from django.db import migrations
from django.utils.text import slugify


def cargar(apps, schema_editor):
    localidad = apps.get_model("aire", "Localidad")
    estacion = apps.get_model("aire", "Estacion")
    # Coordenadas oficiales de la Secretaría Distrital de Ambiente, convertidas de DMS.
    for nombre, modelo, zona, lat, lon in [
        ("Carvajal-Sevillana", "Carvajal-Sevillana", "Kennedy", 4.595833, -74.148500),
        ("Kennedy", "Kennedy", "Kennedy", 4.625050, -74.161333),
        ("Puente Aranda", "Puente Aranda", "Puente Aranda", 4.631767, -74.117483),
        ("Tunal", "Tunal", "Tunjuelito", 4.576225, -74.130956),
        ("Usaquén", "Usaquen", "Usaquén", 4.710350, -74.030417),
    ]:
        loc, _ = localidad.objects.get_or_create(slug=slugify(zona), defaults={"nombre": zona})
        estacion.objects.get_or_create(slug=slugify(nombre), defaults={
            "nombre": nombre, "nombre_modelo": modelo, "localidad": loc,
            "latitud": lat, "longitud": lon,
        })


class Migration(migrations.Migration):
    dependencies = [("aire", "0001_initial")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]

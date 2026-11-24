from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Max, Min, Q
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from config.api import Problema, api
from .actual import VERSION, actualizar_si_corresponde, pronosticar_24
from .inferencia import ESTACIONES, RETARDOS, VARIABLES, ModeloNoDisponible, predecir
from .models import Estacion, Localidad, MedicionHoraria

BOGOTA = ZoneInfo("America/Bogota")
UNIDAD = "µg/m³"
P90 = dict(zip(ESTACIONES, (55.2, 41.0, 35.0, 35.0, 26.0)))


def local(hora):
    return hora.astimezone(BOGOTA).isoformat() if hora else None


def buscar_estacion(slug):
    try:
        return Estacion.objects.get(slug=slug)
    except Estacion.DoesNotExist:
        raise Problema(404, "estacion_inexistente", "No se encontró la estación.")


def serie(estacion):
    return MedicionHoraria.objects.filter(version__codigo=settings.HISTORICO, estacion=estacion)


@api("GET")
def localidades(request):
    return JsonResponse({"resultados": list(Localidad.objects.order_by("nombre").values("slug", "nombre"))})


@api("GET")
def estaciones(request):
    qs = Estacion.objects.select_related("localidad").order_by("nombre")
    if "localidad" in request.GET:
        slug = request.GET["localidad"]
        if not Localidad.objects.filter(slug=slug).exists():
            raise Problema(400, "localidad_invalida", "Localidad desconocida.")
        qs = qs.filter(localidad__slug=slug)
    filtro = Q(medicionhoraria__version__codigo=settings.HISTORICO)
    qs = qs.annotate(desde=Min("medicionhoraria__instante", filter=filtro),
                     hasta=Max("medicionhoraria__instante", filter=filtro))
    return JsonResponse({"resultados": [{"slug": e.slug, "nombre": e.nombre,
        "localidad": e.localidad.slug, "localidad_nombre": e.localidad.nombre,
        "latitud": e.latitud, "longitud": e.longitud,
        "desde": local(e.desde), "hasta": local(e.hasta)} for e in qs]})


@api("GET")
def disponibilidad(request, slug):
    estacion = buscar_estacion(slug)
    qs = serie(estacion).filter(pm25__isnull=False)
    if "mes" not in request.GET:
        meses = qs.datetimes("instante", "month", order="ASC", tzinfo=BOGOTA)
        return JsonResponse({"meses": [mes.strftime("%Y-%m") for mes in meses]})
    try:
        mes = request.GET.get("mes", "")
        inicio = datetime.strptime(mes, "%Y-%m").replace(tzinfo=BOGOTA)
        if inicio.strftime("%Y-%m") != mes:
            raise ValueError
        fin = (inicio + timedelta(days=32)).replace(day=1)
    except (ValueError, OverflowError):
        raise Problema(400, "mes_invalido", "Usa un mes en formato AAAA-MM.")
    horas = qs.filter(instante__gte=inicio, instante__lt=fin).order_by("instante").values_list("instante", flat=True)
    return JsonResponse({"horas": [local(h) for h in horas]})


def seleccionar(request):
    estacion = buscar_estacion(request.GET.get("estacion"))
    try:
        hora = parse_datetime(request.GET.get("emision", ""))
        if hora is None or hora.utcoffset() is None:
            raise ValueError
        hora = hora.astimezone(BOGOTA)
        if hora.minute or hora.second or hora.microsecond:
            raise ValueError
    except (ValueError, OverflowError):
        raise Problema(400, "emision_invalida", "Selecciona una hora exacta con zona horaria.")
    qs = serie(estacion)
    limites = qs.aggregate(desde=Min("instante"), hasta=Max("instante"))
    if not limites["desde"] or not limites["desde"] <= hora <= limites["hasta"]:
        raise Problema(422, "fuera_de_cobertura", "Hora fuera del histórico de esta estación.",
                       **{k: local(v) for k, v in limites.items()})
    return estacion, qs, hora


def entradas(qs, estacion, hora, lectura):
    pasados = {h: hora - timedelta(hours=h) for h in RETARDOS}
    historial = dict(qs.filter(instante__in=pasados.values()).values_list("instante", "pm25"))
    return {
        **{f"{campo}_actual": getattr(lectura, atributo) for campo, atributo in VARIABLES.items()},
        "hora": hora.hour, "mes": hora.month,
        **{f"estacion_{nombre}": estacion.nombre_modelo == nombre for nombre in ESTACIONES},
        **{f"pm25_hace_{h}h": historial.get(instante) for h, instante in pasados.items()},
    }


@api("GET")
def consulta(request):
    estacion, qs, hora = seleccionar(request)
    evaluar = request.GET.get("evaluar", "false")
    if evaluar not in {"true", "false"}:
        raise Problema(400, "evaluar_invalido", "evaluar admite true o false.")
    lectura = qs.filter(instante__lte=hora, pm25__isnull=False).order_by("-instante").first()
    exacta = lectura is not None and lectura.instante == hora
    datos = {"estado": "ok" if exacta else "sin_medicion_en_emision", "estacion": estacion.slug,
             "version_datos": settings.HISTORICO, "zona_horaria": "America/Bogota", "emision": local(hora),
             "medicion": None, "pronostico": None}
    if lectura:
        datos["medicion"] = {"hora": local(lectura.instante), "pm25": lectura.pm25, "unidad": UNIDAD,
            "antiguedad_minutos": int((hora - lectura.instante).total_seconds() / 60), "fuente": "RMCAB"}
    if exacta:
        try:
            valor = predecir(entradas(qs, estacion, hora, lectura))
        except ModeloNoDisponible as error:
            raise Problema(503, "modelo_no_disponible", "El modelo no está disponible.") from error
        siguiente = hora + timedelta(hours=24)
        datos["pronostico"] = {"hora": local(siguiente), "pm25": valor, "unidad": UNIDAD, "horizonte_horas": 24}
        if evaluar == "true":
            observado = qs.filter(instante=siguiente).values_list("pm25", flat=True).first()
            datos["evaluacion"] = {"hora_observada": local(siguiente), "pm25_observado": observado,
                                   "unidad": UNIDAD, "fuente": "RMCAB"}
    return JsonResponse(datos)


@api("GET")
def recomendaciones(request):
    estacion, qs, hora = seleccionar(request)
    observado = qs.filter(instante=hora).values_list("pm25", flat=True).first()
    umbral = P90[estacion.nombre_modelo]
    if observado is None:
        consejo = "Falta una medición de PM2,5 en la hora seleccionada."
    elif observado > umbral:
        consejo = "Concentración alta respecto al historial local. Consulta las indicaciones de la Secretaría de Ambiente."
    else:
        consejo = "La lectura está dentro del rango horario habitual de esta estación."
    moderna = hora.date().isoformat() >= "2021-09-22"
    referencias = [
        {"nombre": "Colombia · Resolución 2254", "url": "https://www.minambiente.gov.co/wp-content/uploads/2021/10/Resolucion-2254-de-2017.pdf",
         "diaria": 37, "anual": 25, "vigencia": "24 h desde julio de 2018; anual desde enero de 2018"},
        {"nombre": f"OMS · Guía {2021 if moderna else 2005}", "url": "https://www.who.int/news-room/questions-and-answers/item/who-global-air-quality-guidelines",
         "diaria": 15 if moderna else 25, "anual": 5 if moderna else 10,
         "vigencia": "Septiembre de 2021" if moderna else "Edición 2005", "criterio": "Percentil 99 de las medias diarias"},
    ]
    return JsonResponse({"consejo": consejo, "p90_historico": umbral, "unidad": UNIDAD, "referencias": referencias})


@api("GET")
def actual(request):
    estacion = buscar_estacion(request.GET.get("estacion"))
    actualizar_si_corresponde()
    ahora = timezone.now()
    qs = MedicionHoraria.objects.filter(version__codigo=VERSION, estacion=estacion)
    lectura = qs.filter(instante__lte=ahora, pm25__isnull=False).order_by("-instante").first()
    datos = {"estacion": estacion.slug, "zona_horaria": "America/Bogota", "fuente": "RMCAB",
             "estado": "sin_lectura", "medicion": None, "horas": []}
    if lectura is None:
        return JsonResponse(datos)
    hora = lectura.instante.astimezone(BOGOTA)
    antiguedad = int((ahora - hora).total_seconds() / 60)
    datos["medicion"] = {"hora": local(hora), "pm25": lectura.pm25, "unidad": UNIDAD,
                         "antiguedad_minutos": antiguedad}
    datos["estado"] = "lectura_atrasada"
    if antiguedad >= 180:
        return JsonResponse(datos)
    try:
        pronostico = pronosticar_24(entradas(qs, estacion, hora, lectura))
    except (OSError, ValueError, ImportError):
        datos["estado"] = "modelo_no_disponible"
        return JsonResponse(datos)
    datos["estado"] = "ok"
    datos["horas"] = [{"hora": local(hora + timedelta(hours=h)), "pm25": valor, "unidad": UNIDAD}
                       for h, valor in pronostico]
    return JsonResponse(datos)

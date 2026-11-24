from django.core.paginator import EmptyPage, Paginator
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone

from aire.models import Localidad
from config.api import Problema, api, autenticado, campo, cuerpo
from .models import Comentario, Reporte


def localidad(slug):
    try:
        return Localidad.objects.get(slug=slug)
    except Localidad.DoesNotExist:
        raise Problema(400, "localidad_invalida", "Selecciona una localidad del piloto.")


def visible(qs, pk):
    try:
        return qs.get(pk=pk)
    except qs.model.DoesNotExist:
        raise Problema(404, "publicacion_inexistente", "Publicación no disponible.")


def presentar(obj):
    datos = {"id": obj.pk, "texto": obj.texto, "autor": obj.autor.username,
             "autor_id": obj.autor_id, "creado_en": obj.creado_en.isoformat()}
    if isinstance(obj, Reporte):
        datos.update(categoria=obj.categoria, localidad=obj.localidad.slug)
    return datos


def pagina(qs, request):
    try:
        indice = int(request.GET.get("pagina", 1))
        parte = Paginator(qs, 20).page(indice)
    except (ValueError, EmptyPage):
        raise Problema(400, "pagina_invalida", "Página no disponible.")
    return JsonResponse({"resultados": [presentar(obj) for obj in parte],
                         "pagina": indice, "paginas": parte.paginator.num_pages})


@api("GET", "POST")
def reportes(request):
    if request.method == "GET":
        qs = Reporte.objects.filter(oculto=False).select_related("autor", "localidad")
        if "localidad" in request.GET:
            qs = qs.filter(localidad=localidad(request.GET["localidad"]))
        return pagina(qs.order_by("-creado_en", "-id"), request)
    autor = autenticado(request)
    datos = cuerpo(request)
    categoria = campo(datos, "categoria", 16)
    if categoria not in dict(Reporte._meta.get_field("categoria").choices):
        raise Problema(400, "categoria_invalida", "Elige olor, humo, quema u otro.")
    reporte = Reporte.objects.create(localidad=localidad(campo(datos, "localidad", 50)), autor=autor,
                                    categoria=categoria, texto=campo(datos, "texto", 1000))
    return JsonResponse(presentar(reporte), status=201)


@api("GET", "POST")
def comentarios(request, pk):
    if request.method == "GET":
        reporte = visible(Reporte.objects.filter(oculto=False), pk)
        return pagina(Comentario.objects.filter(reporte=reporte, reporte__oculto=False, oculto=False)
                      .select_related("autor").order_by("creado_en", "id"), request)
    autor = autenticado(request)
    texto = campo(cuerpo(request), "texto", 500)
    with transaction.atomic():
        reporte = visible(Reporte.objects.select_for_update().filter(oculto=False), pk)
        comentario = Comentario.objects.create(reporte=reporte, autor=autor, texto=texto)
    return JsonResponse(presentar(comentario), status=201)


@api("POST")
@transaction.atomic
def ocultar_reporte(request, pk):
    usuario = autenticado(request)
    if not usuario.has_perm("comunidad.ocultar_reporte"):
        raise Problema(403, "permiso_requerido", "Solo una persona moderadora puede ocultar reportes.")
    reporte = visible(Reporte.objects.select_for_update(), pk)
    if not reporte.oculto:
        reporte.oculto = True
        reporte.ocultado_en = timezone.now()
        reporte.ocultado_por = usuario
        reporte.save(update_fields=["oculto", "ocultado_en", "ocultado_por"])
    return HttpResponse(status=204)


@api("POST")
@transaction.atomic
def ocultar_comentario(request, pk):
    usuario = autenticado(request)
    if not usuario.has_perm("comunidad.ocultar_comentario"):
        raise Problema(403, "permiso_requerido", "Solo una persona moderadora puede ocultar comentarios.")
    comentario = visible(Comentario.objects.select_for_update(), pk)
    if not comentario.oculto:
        comentario.oculto = True
        comentario.ocultado_en = timezone.now()
        comentario.ocultado_por = usuario
        comentario.save(update_fields=["oculto", "ocultado_en", "ocultado_por"])
    return HttpResponse(status=204)


@api("DELETE")
@transaction.atomic
def eliminar(request, pk, modelo):
    usuario = autenticado(request)
    obj = visible(modelo.objects.select_for_update(), pk)
    if obj.autor_id != usuario.pk:
        raise Problema(403, "autor_requerido", "Solo el autor puede eliminar la publicación.")
    obj.delete()
    return HttpResponse(status=204)

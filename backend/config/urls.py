from django.contrib import admin
from django.conf import settings
from django.shortcuts import redirect
from django.urls import include, path

from aire import views as aire
from comunidad import views as comunidad
from comunidad.models import Comentario, Reporte
from cuentas import views as cuentas

api = [
    path("localidades", aire.localidades),
    path("estaciones", aire.estaciones),
    path("estaciones/<slug:slug>/disponibilidad", aire.disponibilidad),
    path("consulta", aire.consulta),
    path("actual", aire.actual),
    path("recomendaciones", aire.recomendaciones),
    path("registro", cuentas.registro),
    path("sesion", cuentas.sesion),
    path("administracion/usuarios", cuentas.administracion_usuarios),
    path("administracion/usuarios/<int:pk>", cuentas.administracion_usuario),
    path("moderacion/usuarios", cuentas.usuarios_moderacion),
    path("moderacion/usuarios/<int:pk>/sancion", cuentas.sancionar_usuario),
    path("perfil", cuentas.perfil),
    path("perfil/foto", cuentas.foto_perfil),
    path("perfil/contrasena", cuentas.cambiar_contrasena),
    path("auth/google/iniciar", cuentas.iniciar_google),
    path("auth/google/pendiente", cuentas.alta_google_pendiente),
    path("auth/google/crear", cuentas.alta_google_crear),
    path("auth/google/callback", cuentas.callback_google),
    path("reportes", comunidad.reportes),
    path("reportes/<int:pk>", comunidad.eliminar, {"modelo": Reporte}),
    path("reportes/<int:pk>/ocultar", comunidad.ocultar_reporte),
    path("reportes/<int:pk>/comentarios", comunidad.comentarios),
    path("comentarios/<int:pk>/ocultar", comunidad.ocultar_comentario),
    path("comentarios/<int:pk>", comunidad.eliminar, {"modelo": Comentario}),
]

def panel_administracion(request):
    # La interfaz vive en React/Vite; conservar esta URL también en el puerto Django.
    return redirect(f"{settings.FRONTEND_URL}/administracion")


def panel_moderacion(request):
    return redirect(f"{settings.FRONTEND_URL}/moderacion")


urlpatterns = [
    path("administracion", panel_administracion),
    path("administracion/", panel_administracion),
    path("moderacion", panel_moderacion),
    path("moderacion/", panel_moderacion),
    path("admin/", admin.site.urls),
    path("api/v1/", include(api)),
]

handler400 = "config.errors.bad_request"
handler403 = "config.errors.permission_denied"
handler404 = "config.errors.page_not_found"
handler500 = "config.errors.server_error"

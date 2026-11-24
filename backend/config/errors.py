from django.conf import settings
from django.shortcuts import render


DETALLES = {
    400: ("Solicitud no válida", "Revisa los datos enviados e inténtalo de nuevo."),
    401: ("Inicia sesión para continuar", "Esta acción requiere una sesión activa."),
    403: ("No tienes permiso", "Tu cuenta no puede acceder a este contenido."),
    404: ("No encontramos esta página", "Puede que el enlace haya cambiado o ya no exista."),
    405: ("Acción no disponible", "No se puede completar esa acción desde esta página."),
    429: ("Demasiadas solicitudes", "Espera un momento antes de volver a intentarlo."),
    500: ("Algo salió mal", "Tuvimos un problema al cargar esta página."),
    502: ("Servicio temporalmente no disponible", "Vuelve a intentarlo en unos momentos."),
    503: ("Servicio temporalmente no disponible", "Estamos trabajando para restablecer el servicio."),
}


def pagina_error(request, codigo):
    titulo, descripcion = DETALLES.get(codigo, DETALLES[500])
    return render(request, "errors/page.html", {
        "codigo": codigo,
        "titulo": titulo,
        "descripcion": descripcion,
        "frontend_url": settings.FRONTEND_URL,
    }, status=codigo)


def bad_request(request, exception=None):
    return pagina_error(request, 400)


def permission_denied(request, exception=None):
    return pagina_error(request, 403)


def page_not_found(request, exception=None):
    return pagina_error(request, 404)


def server_error(request):
    return pagina_error(request, 500)

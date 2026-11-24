from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render

from .errors import DETALLES


class PaginasDeError:
    """Sustituye las respuestas técnicas de Django por errores amigables."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        codigo = response.status_code
        if codigo not in DETALLES:
            return response

        titulo, descripcion = DETALLES[codigo]
        if request.path.startswith("/api/"):
            if "application/json" in response.get("Content-Type", ""):
                return response
            return JsonResponse(
                {"codigo": codigo, "mensaje": descripcion},
                status=codigo,
            )

        return render(
            request,
            "errors/page.html",
            {
                "codigo": codigo,
                "titulo": titulo,
                "descripcion": descripcion,
                "frontend_url": settings.FRONTEND_URL,
            },
            status=codigo,
        )

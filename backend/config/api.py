import json
from functools import wraps

from django.http import JsonResponse


class Problema(Exception):
    def __init__(self, estado, codigo, mensaje, **datos):
        self.estado = estado
        self.datos = {"codigo": codigo, "mensaje": mensaje, **datos}
        super().__init__(mensaje)


def csrf_failure(request, reason=""):
    return JsonResponse({"codigo": "csrf", "mensaje": "Actualiza la sesión y vuelve a intentarlo."}, status=403)


def api(*metodos):
    def decorar(vista):
        @wraps(vista)
        def responder(request, *args, **kwargs):
            if request.method not in metodos:
                respuesta = JsonResponse({"codigo": "metodo", "mensaje": "Método no permitido."}, status=405)
                respuesta["Allow"] = ", ".join(metodos)
                return respuesta
            try:
                return vista(request, *args, **kwargs)
            except Problema as error:
                return JsonResponse(error.datos, status=error.estado)
        return responder
    return decorar


def cuerpo(request):
    try:
        datos = json.loads(request.body)
    except (ValueError, UnicodeError):
        datos = None
    if not isinstance(datos, dict):
        raise Problema(400, "json_invalido", "Se esperaba un objeto JSON.")
    return datos


def campo(datos, nombre, maximo, *, recortar=True):
    valor = datos.get(nombre)
    if isinstance(valor, str) and recortar:
        valor = valor.strip()
    if not isinstance(valor, str) or not 0 < len(valor) <= maximo:
        raise Problema(400, "campo_invalido", f"Revisa el campo {nombre}.", campos=[nombre])
    return valor


def autenticado(request):
    if not request.user.is_authenticated:
        raise Problema(401, "sesion_requerida", "Inicia sesión para continuar.")
    if not request.user.is_active:
        raise Problema(403, "cuenta_inactiva", "Esta cuenta no puede realizar esta acción.")
    return request.user

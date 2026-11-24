import secrets
import struct
import time
import uuid
from datetime import timedelta

from authlib.integrations.base_client import OAuthError
from authlib.integrations.django_client import OAuth
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.core.validators import validate_email
from django.db.models import Exists, OuterRef
from django.db import IntegrityError, transaction
from django.http import FileResponse, HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.cache import never_cache
from joserfc.errors import JoseError
from requests import RequestException

from config.api import Problema, api, autenticado, campo, cuerpo
from .models import IdentidadGoogle, PerfilUsuario, SancionCuenta

Usuario = get_user_model()
VERSION_TERMINOS = "2026-11"
ROLES_ADMIN = {"Usuario", "Moderador de contenido", "Administrador"}
oauth = OAuth()
oauth.register("google", client_id=settings.GOOGLE_CLIENT_ID, client_secret=settings.GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256", "default_timeout": 10})


def abrir_sesion(request, usuario):
    login(request, usuario, backend="django.contrib.auth.backends.ModelBackend")
    request.session.set_expiry(timezone.now() + timedelta(days=14))


def expirar_sanciones_vencidas():
    ahora = timezone.now()
    with transaction.atomic():
        ids = list(SancionCuenta.objects.filter(
            activa=True, tipo=SancionCuenta.SUSPENSION, vence_en__lte=ahora
        ).values_list("usuario_id", flat=True).distinct())
        if not ids:
            return
        list(Usuario.objects.select_for_update().filter(pk__in=ids).values_list("pk", flat=True))
        vencidas = SancionCuenta.objects.select_for_update().filter(
            usuario_id__in=ids, activa=True, tipo=SancionCuenta.SUSPENSION, vence_en__lte=ahora)
        usuarios = list(vencidas.values_list("usuario_id", flat=True))
        if usuarios:
            vencidas.update(activa=False, levantada_en=ahora)
            Usuario.objects.filter(pk__in=usuarios).update(is_active=True)


def sancion_activa(usuario):
    return SancionCuenta.objects.filter(usuario=usuario, activa=True).order_by("-creada_en").first()


def rechazar_por_sancion(sancion):
    if sancion.tipo == SancionCuenta.BANEO:
        raise Problema(403, "cuenta_baneada", f"Esta cuenta fue baneada. Motivo: {sancion.motivo}")
    fecha = timezone.localtime(sancion.vence_en).strftime("%d/%m/%Y %H:%M") if sancion.vence_en else "próximamente"
    raise Problema(403, "cuenta_suspendida",
                   f"Esta cuenta está suspendida hasta el {fecha}. Motivo: {sancion.motivo}")


def estado(request):
    expirar_sanciones_vencidas()
    usuario = request.user
    perfil = PerfilUsuario.objects.filter(usuario=usuario).only("foto").first() if usuario.is_authenticated else None
    return JsonResponse({"usuario": {"id": usuario.pk,
        "nombre": usuario.first_name.strip() or usuario.username,
        "usuario": usuario.username,
        "foto": f"/api/v1/perfil/foto?v={perfil.foto.name.rsplit('/', 1)[-1]}" if perfil and perfil.foto else None,
        "google_vinculado": IdentidadGoogle.objects.filter(usuario=usuario).exists(),
        "puede_moderar": usuario.has_perm("comunidad.ocultar_reporte"),
        "puede_moderar_cuentas": usuario.has_perm("cuentas.gestionar_sanciones"),
        "es_admin": usuario.is_superuser} if usuario.is_authenticated else None,
        "csrf": get_token(request), "google_disponible": bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)})


@never_cache
@api("GET", "POST", "DELETE")
def sesion(request):
    if request.method == "POST":
        expirar_sanciones_vencidas()
        datos = cuerpo(request)
        identificador = campo(datos, "usuario", 254)
        if "@" in identificador:
            usuario_base = Usuario.objects.filter(email__iexact=identificador).first()
            identificador = usuario_base.username if usuario_base else identificador
        usuario_base = Usuario.objects.filter(username__iexact=identificador).first()
        if usuario_base and not usuario_base.is_active:
            sancion = sancion_activa(usuario_base)
            if sancion:
                rechazar_por_sancion(sancion)
        usuario = authenticate(request, username=identificador,
                               password=campo(datos, "contrasena", 1024, recortar=False))
        if usuario is None:
            raise Problema(401, "credenciales", "Usuario o contraseña incorrectos.")
        abrir_sesion(request, usuario)
    elif request.method == "DELETE":
        autenticado(request)
        logout(request)
        return HttpResponse(status=204)
    return estado(request)


def perfil_json(usuario, perfil):
    return {"nombre": usuario.first_name, "usuario": usuario.username,
        "foto": f"/api/v1/perfil/foto?v={perfil.foto.name.rsplit('/', 1)[-1]}" if perfil.foto else None,
        "tiene_contrasena": usuario.has_usable_password()}


@never_cache
@api("GET")
def foto_perfil(request):
    usuario = autenticado(request)
    perfil_usuario = PerfilUsuario.objects.filter(usuario=usuario).first()
    if not perfil_usuario or not perfil_usuario.foto:
        raise Problema(404, "foto_no_encontrada", "No hay una foto de perfil.")
    tipo = "image/png" if perfil_usuario.foto.name.endswith(".png") else "image/jpeg"
    respuesta = FileResponse(perfil_usuario.foto.open("rb"), content_type=tipo)
    respuesta["X-Content-Type-Options"] = "nosniff"
    return respuesta


def dimensiones_jpeg(archivo):
    archivo.seek(0)
    datos = archivo.read(min(archivo.size, 512 * 1024))
    archivo.seek(0)
    if not datos.startswith(b"\xff\xd8"):
        return None
    marcadores_sof = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    posicion = 2
    while posicion + 4 <= len(datos):
        if datos[posicion] != 0xFF:
            return None
        while posicion < len(datos) and datos[posicion] == 0xFF:
            posicion += 1
        if posicion >= len(datos):
            break
        marcador = datos[posicion]
        posicion += 1
        if marcador in {0xD8, 0xD9, 0x01, *range(0xD0, 0xD8)}:
            continue
        if posicion + 2 > len(datos):
            break
        longitud = int.from_bytes(datos[posicion:posicion + 2], "big")
        if longitud < 2 or posicion + longitud > len(datos):
            break
        if marcador in marcadores_sof and longitud >= 7:
            alto, ancho = struct.unpack(">HH", datos[posicion + 3:posicion + 7])
            return ancho, alto
        if marcador == 0xDA:
            break
        posicion += longitud
    return None


def validar_foto(archivo):
    maximo = 5 * 1024 * 1024
    if archivo.size > maximo:
        raise Problema(413, "foto_grande", "La foto debe pesar máximo 5 MB.")
    archivo.seek(0)
    cabecera = archivo.read(24)
    archivo.seek(0)
    if cabecera.startswith(b"\x89PNG\r\n\x1a\n") and cabecera[12:16] == b"IHDR":
        ancho, alto = struct.unpack(">II", cabecera[16:24])
        archivo.seek(-12, 2)
        final = archivo.read(12)
        extension = "png" if final[4:] == b"IEND\xaeB`\x82" else None
        archivo.seek(0)
    elif cabecera.startswith(b"\xff\xd8\xff"):
        dimensiones = dimensiones_jpeg(archivo)
        archivo.seek(-2, 2)
        extension = "jpg" if archivo.read(2) == b"\xff\xd9" else None
        archivo.seek(0)
        if dimensiones:
            ancho, alto = dimensiones
        else:
            ancho, alto = 0, 0
    else:
        extension, ancho, alto = None, 0, 0
    if not extension or not ancho or not alto or ancho > 4096 or alto > 4096:
        raise Problema(400, "foto_invalida", "Sube una imagen PNG o JPG válida, de hasta 4096 × 4096 px.")
    archivo.name = f"foto.{extension}"


@api("GET", "POST")
def perfil(request):
    usuario = autenticado(request)
    perfil_usuario, _ = PerfilUsuario.objects.get_or_create(usuario=usuario)
    if request.method == "GET":
        return JsonResponse(perfil_json(usuario, perfil_usuario))

    nombre = request.POST.get("nombre", "").strip()
    nuevo_usuario = request.POST.get("usuario", "").strip()
    if len(nombre) > 150:
        raise Problema(400, "perfil_invalido", "El nombre puede tener hasta 150 caracteres.")
    try:
        nuevo_usuario = Usuario._meta.get_field("username").clean(nuevo_usuario, usuario)
    except ValidationError as error:
        raise Problema(400, "perfil_invalido", "Revisa el nombre de usuario.") from error
    if Usuario.objects.filter(username__iexact=nuevo_usuario).exclude(pk=usuario.pk).exists():
        raise Problema(409, "usuario_ocupado", "Ese nombre de usuario ya está en uso.")

    foto = request.FILES.get("foto")
    if foto:
        validar_foto(foto)
    foto_anterior = perfil_usuario.foto.name if perfil_usuario.foto else ""
    try:
        with transaction.atomic():
            usuario.first_name = nombre
            usuario.username = nuevo_usuario
            usuario.save(update_fields=["first_name", "username"])
            if foto:
                perfil_usuario.foto = foto
            elif request.POST.get("eliminar_foto") == "1":
                perfil_usuario.foto = ""
            perfil_usuario.save()
            foto_nueva = perfil_usuario.foto.name if perfil_usuario.foto else ""
            if foto_anterior and foto_anterior != foto_nueva:
                transaction.on_commit(lambda nombre=foto_anterior: default_storage.delete(nombre))
    except IntegrityError as error:
        raise Problema(409, "usuario_ocupado", "Ese nombre de usuario ya está en uso.") from error
    return JsonResponse(perfil_json(usuario, perfil_usuario))


@api("POST")
def cambiar_contrasena(request):
    usuario = autenticado(request)
    datos = cuerpo(request)
    nueva = campo(datos, "nueva", 1024, recortar=False)
    confirmacion = campo(datos, "confirmacion", 1024, recortar=False)
    if nueva != confirmacion:
        raise Problema(400, "contrasena_no_coincide", "Las contraseñas nuevas no coinciden.")
    if usuario.has_usable_password():
        actual = datos.get("actual", "")
        if not isinstance(actual, str) or not usuario.check_password(actual):
            raise Problema(400, "contrasena_actual_invalida", "La contraseña actual no es correcta.")
    try:
        validate_password(nueva, usuario)
    except ValidationError as error:
        raise Problema(400, "contrasena_invalida", " ".join(error.messages)) from error
    usuario.set_password(nueva)
    usuario.save(update_fields=["password"])
    update_session_auth_hash(request, usuario)
    return JsonResponse({"ok": True})


@api("POST")
def registro(request):
    datos = cuerpo(request)
    if datos.get("acepto_terminos") is not True:
        raise Problema(400, "terminos_requeridos", "Acepta los términos y el aviso de tratamiento de datos para crear tu cuenta.")
    usuario = Usuario(username=campo(datos, "usuario", 150))
    email = datos.get("email", "")
    if not isinstance(email, str) or len(email) > 254:
        raise Problema(400, "registro_invalido", "Revisa el correo electrónico.", campos=["email"])
    usuario.email = email.strip().lower()
    if usuario.email and Usuario.objects.filter(email__iexact=usuario.email).exists():
        raise Problema(409, "correo_ocupado", "Ese correo ya está asociado a una cuenta.")
    clave = campo(datos, "contrasena", 1024, recortar=False)
    try:
        usuario.full_clean(exclude=["password"], validate_unique=False)
        validate_password(clave, usuario)
    except ValidationError as error:
        raise Problema(400, "registro_invalido", " ".join(error.messages)) from error
    usuario.set_password(clave)
    try:
        with transaction.atomic():
            usuario.save(force_insert=True)
            PerfilUsuario.objects.create(usuario=usuario,
                consentimiento_aceptado_en=timezone.now(), consentimiento_version=VERSION_TERMINOS)
    except IntegrityError as error:
        raise Problema(409, "usuario_ocupado", "Ese usuario ya existe.") from error
    return JsonResponse({"id": usuario.pk, "nombre": usuario.username}, status=201)


def exigir_administrador(request):
    administrador = autenticado(request)
    if not administrador.is_superuser:
        raise Problema(403, "permiso_requerido", "Solo una cuenta administradora puede consultar los usuarios.")
    return administrador


def rol_de_usuario(usuario):
    if usuario.is_superuser:
        return "Administrador"
    if usuario.groups.filter(name="Moderadores").exists():
        return "Moderador de contenido"
    return "Usuario"


def usuario_admin_json(usuario):
    return {
        "id": usuario.pk,
        "usuario": usuario.username,
        "nombre": usuario.first_name,
        "correo": usuario.email,
        "rol": rol_de_usuario(usuario),
        "activo": usuario.is_active,
        "google_vinculado": IdentidadGoogle.objects.filter(usuario_id=usuario.pk).exists(),
        "creado_en": usuario.date_joined.isoformat(),
    }


def validar_datos_admin(datos, usuario=None, *, crear=False):
    username = campo(datos, "usuario", 150)
    try:
        username = Usuario._meta.get_field("username").clean(username, usuario or Usuario())
    except ValidationError as error:
        raise Problema(400, "usuario_invalido", "Revisa el nombre de usuario.") from error
    if Usuario.objects.filter(username__iexact=username).exclude(pk=usuario.pk if usuario else None).exists():
        raise Problema(409, "usuario_ocupado", "Ese nombre de usuario ya está en uso.")

    nombre = datos.get("nombre", "")
    if not isinstance(nombre, str) or len(nombre.strip()) > 150:
        raise Problema(400, "nombre_invalido", "El nombre puede tener hasta 150 caracteres.")
    nombre = nombre.strip()

    correo = datos.get("correo", "")
    if not isinstance(correo, str) or len(correo.strip()) > 254:
        raise Problema(400, "correo_invalido", "Revisa el correo electrónico.")
    correo = correo.strip().lower()
    if correo:
        try:
            validate_email(correo)
        except ValidationError as error:
            raise Problema(400, "correo_invalido", "Revisa el correo electrónico.") from error
        duplicado = Usuario.objects.filter(email__iexact=correo)
        if usuario:
            duplicado = duplicado.exclude(pk=usuario.pk)
        if duplicado.exists():
            raise Problema(409, "correo_ocupado", "Ese correo ya está asociado a otra cuenta.")

    rol = datos.get("rol", "Usuario")
    if not isinstance(rol, str) or rol not in ROLES_ADMIN:
        raise Problema(400, "rol_invalido", "Selecciona un rol válido.")
    activo = datos.get("activo", True)
    if not isinstance(activo, bool):
        raise Problema(400, "estado_invalido", "El estado de la cuenta no es válido.")

    contrasena = datos.get("contrasena", "")
    if not isinstance(contrasena, str) or (crear and not contrasena) or len(contrasena) > 1024:
        raise Problema(400, "contrasena_invalida", "Escribe una contraseña válida.")
    instancia = usuario or Usuario(username=username, email=correo, first_name=nombre)
    if contrasena:
        try:
            validate_password(contrasena, instancia)
        except ValidationError as error:
            raise Problema(400, "contrasena_invalida", " ".join(error.messages)) from error

    return {"username": username, "first_name": nombre, "email": correo,
            "rol": rol, "is_active": activo, "contrasena": contrasena}


def aplicar_rol(usuario, rol):
    es_admin = rol == "Administrador"
    usuario.is_superuser = es_admin
    usuario.is_staff = es_admin
    moderadores, _ = Group.objects.get_or_create(name="Moderadores")
    if rol == "Moderador de contenido":
        usuario.groups.add(moderadores)
    else:
        usuario.groups.remove(moderadores)


def bloquear_ultimo_administrador(objetivo, rol_nuevo=None, activo_nuevo=None, *, eliminar=False):
    pierde_permisos_admin = eliminar or (
        rol_nuevo is not None and rol_nuevo != "Administrador"
    ) or activo_nuevo is False
    if not objetivo.is_superuser or not pierde_permisos_admin:
        return
    activos = list(Usuario.objects.select_for_update().filter(
        is_superuser=True, is_active=True
    ).order_by("pk").values_list("pk", flat=True))
    if objetivo.pk in activos and len(activos) <= 1:
        raise Problema(409, "ultimo_administrador", "Debe quedar al menos un administrador activo.")


@never_cache
@api("GET", "POST")
def administracion_usuarios(request):
    exigir_administrador(request)
    if request.method == "POST":
        datos = cuerpo(request)
        valores = validar_datos_admin(datos, crear=True)
        with transaction.atomic():
            usuario = Usuario(
                username=valores["username"],
                first_name=valores["first_name"],
                email=valores["email"],
                is_active=valores["is_active"],
            )
            usuario.set_password(valores["contrasena"])
            es_admin = valores["rol"] == "Administrador"
            usuario.is_superuser = es_admin
            usuario.is_staff = es_admin
            try:
                usuario.save(force_insert=True)
            except IntegrityError as error:
                raise Problema(409, "usuario_ocupado", "Ya existe una cuenta con esos datos.") from error
            aplicar_rol(usuario, valores["rol"])
        return JsonResponse(usuario_admin_json(usuario), status=201)

    usuarios = Usuario.objects.annotate(
        google_vinculado=Exists(IdentidadGoogle.objects.filter(usuario_id=OuterRef("pk")))
    ).prefetch_related("groups").order_by("username")
    total = usuarios.count()
    resultados = []
    for usuario in usuarios[:500]:
        grupos = [grupo.name for grupo in usuario.groups.all()]
        rol = "Administrador" if usuario.is_superuser else (
            "Moderador de contenido" if "Moderadores" in grupos else "Usuario")
        resultados.append({
            "id": usuario.pk,
            "usuario": usuario.username,
            "nombre": usuario.first_name,
            "correo": usuario.email,
            "rol": rol,
            "activo": usuario.is_active,
            "google_vinculado": usuario.google_vinculado,
            "creado_en": usuario.date_joined.isoformat(),
        })
    return JsonResponse({"resultados": resultados, "total": total, "limite": 500})


@never_cache
@api("PATCH", "DELETE")
def administracion_usuario(request, pk):
    administrador = exigir_administrador(request)
    try:
        objetivo = Usuario.objects.get(pk=pk)
    except Usuario.DoesNotExist as error:
        raise Problema(404, "usuario_no_encontrado", "No encontramos esa cuenta.") from error

    if request.method == "DELETE":
        if objetivo.pk == administrador.pk:
            raise Problema(400, "no_puedes_eliminarte", "No puedes eliminar tu propia cuenta desde esta pantalla.")
        with transaction.atomic():
            objetivo = Usuario.objects.select_for_update().get(pk=pk)
            bloquear_ultimo_administrador(objetivo, eliminar=True)
            perfil = PerfilUsuario.objects.filter(usuario=objetivo).only("foto").first()
            foto_anterior = perfil.foto.name if perfil and perfil.foto else ""
            objetivo.delete()
            if foto_anterior:
                transaction.on_commit(lambda nombre=foto_anterior: default_storage.delete(nombre))
        return HttpResponse(status=204)

    datos = cuerpo(request)
    valores = validar_datos_admin(datos, objetivo)
    if objetivo.pk == administrador.pk and (
        valores["rol"] != "Administrador" or not valores["is_active"]
    ):
        raise Problema(400, "no_puedes_quitarte_admin", "No puedes quitarte el rol administrador ni desactivar tu propia cuenta.")

    with transaction.atomic():
        objetivo = Usuario.objects.select_for_update().get(pk=pk)
        bloquear_ultimo_administrador(objetivo, valores["rol"], valores["is_active"])
        SancionCuenta.objects.filter(usuario=objetivo, activa=True).update(
            activa=False, levantada_en=timezone.now(), levantada_por=administrador)
        objetivo.username = valores["username"]
        objetivo.first_name = valores["first_name"]
        objetivo.email = valores["email"]
        objetivo.is_active = valores["is_active"]
        aplicar_rol(objetivo, valores["rol"])
        campos = ["username", "first_name", "email", "is_active", "is_staff", "is_superuser"]
        if valores["contrasena"]:
            objetivo.set_password(valores["contrasena"])
            campos.append("password")
        try:
            objetivo.save(update_fields=campos)
        except IntegrityError as error:
            raise Problema(409, "usuario_ocupado", "Ya existe una cuenta con esos datos.") from error
        if objetivo.pk == administrador.pk and valores["contrasena"]:
            update_session_auth_hash(request, objetivo)
    return JsonResponse(usuario_admin_json(objetivo))


def exigir_moderador_cuentas(request):
    moderador = autenticado(request)
    if not moderador.has_perm("cuentas.gestionar_sanciones"):
        raise Problema(403, "permiso_requerido", "No tienes permiso para moderar cuentas.")
    return moderador


def presentar_cuenta_moderacion(usuario, sancion=None):
    grupos = {grupo.name for grupo in usuario.groups.all()}
    rol = "Administrador" if usuario.is_superuser else (
        "Moderador de contenido" if "Moderadores" in grupos else "Usuario")
    return {
        "id": usuario.pk,
        "usuario": usuario.username,
        "nombre": usuario.first_name,
        "correo": usuario.email,
        "rol": rol,
        "activo": usuario.is_active,
        "google_vinculado": getattr(usuario, "google_vinculado", None) if hasattr(usuario, "google_vinculado")
        else IdentidadGoogle.objects.filter(usuario_id=usuario.pk).exists(),
        "estado_sancion": sancion.tipo if sancion and sancion.activa else ("inactiva" if not usuario.is_active else "normal"),
        "motivo_sancion": sancion.motivo if sancion else "",
        "sancion_hasta": sancion.vence_en.isoformat() if sancion and sancion.vence_en else None,
        "creado_en": usuario.date_joined.isoformat(),
    }


@never_cache
@api("GET")
def usuarios_moderacion(request):
    exigir_moderador_cuentas(request)
    expirar_sanciones_vencidas()
    usuarios = list(Usuario.objects.prefetch_related("groups").annotate(
        google_vinculado=Exists(IdentidadGoogle.objects.filter(usuario_id=OuterRef("pk")))
    ).order_by("username")[:500])
    ids = [usuario.pk for usuario in usuarios]
    sanciones = SancionCuenta.objects.filter(usuario_id__in=ids).order_by("usuario_id", "-creada_en")
    ultima_sancion = {}
    for sancion in sanciones:
        ultima_sancion.setdefault(sancion.usuario_id, sancion)
    resultados = [presentar_cuenta_moderacion(usuario, ultima_sancion.get(usuario.pk))
                  for usuario in usuarios]
    return JsonResponse({"resultados": resultados, "total": len(resultados), "limite": 500})


@never_cache
@api("POST")
@transaction.atomic
def sancionar_usuario(request, pk):
    moderador = exigir_moderador_cuentas(request)
    datos = cuerpo(request)
    accion = datos.get("accion")
    if accion not in ("suspender", "banear", "levantar"):
        raise Problema(400, "accion_invalida", "Elige suspender, banear o levantar la sanción.")
    objetivo = Usuario.objects.select_for_update().filter(pk=pk).first()
    if not objetivo:
        raise Problema(404, "usuario_no_encontrado", "No encontramos esa cuenta.")
    if objetivo.pk == moderador.pk:
        raise Problema(400, "no_puedes_sancionarte", "No puedes suspender ni banear tu propia cuenta.")
    if objetivo.is_superuser:
        raise Problema(403, "cuenta_administradora", "Las cuentas administradoras se gestionan desde el panel de administración.")

    actual = SancionCuenta.objects.select_for_update().filter(usuario=objetivo, activa=True).first()
    if accion == "levantar":
        if not actual:
            raise Problema(409, "sin_sancion_activa", "Esta cuenta no tiene una sanción activa.")
        actual.activa = False
        actual.levantada_en = timezone.now()
        actual.levantada_por = moderador
        actual.save(update_fields=["activa", "levantada_en", "levantada_por"])
        objetivo.is_active = True
        objetivo.save(update_fields=["is_active"])
    else:
        motivo = campo(datos, "motivo", 500)
        if not objetivo.is_active and not actual:
            raise Problema(409, "cuenta_inactiva", "Esta cuenta ya está desactivada por administración.")
        if actual:
            actual.activa = False
            actual.levantada_en = timezone.now()
            actual.levantada_por = moderador
            actual.save(update_fields=["activa", "levantada_en", "levantada_por"])
        tipo = SancionCuenta.BANEO if accion == "banear" else SancionCuenta.SUSPENSION
        vence_en = None
        if tipo == SancionCuenta.SUSPENSION:
            dias = datos.get("dias", 7)
            if isinstance(dias, bool) or not isinstance(dias, int) or dias not in (1, 7, 30):
                raise Problema(400, "duracion_invalida", "La suspensión debe durar 1, 7 o 30 días.")
            vence_en = timezone.now() + timedelta(days=dias)
        sancion = SancionCuenta.objects.create(usuario=objetivo, tipo=tipo, motivo=motivo,
                                                vence_en=vence_en, moderador=moderador)
        objetivo.is_active = False
        objetivo.save(update_fields=["is_active"])

    ultima = sancion if accion != "levantar" else actual
    return JsonResponse(presentar_cuenta_moderacion(objetivo, ultima))


@never_cache
@api("POST")
def iniciar_google(request):
    accion = cuerpo(request).get("accion", "entrar")
    if accion not in ("entrar", "vincular"):
        raise Problema(400, "accion_invalida", "Acción desconocida.")
    if accion == "vincular":
        autenticado(request)
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise Problema(503, "google_sin_configurar", "Falta configurar el acceso con Google.")
    try:
        cliente = oauth.google
        datos = cliente.create_authorization_url(settings.GOOGLE_REDIRECT_URI)
    except RequestException as error:
        raise Problema(503, "google_indisponible", "Google no está disponible.") from error
    cliente.framework.expires_in = 600
    cliente.save_authorize_data(request, redirect_uri=settings.GOOGLE_REDIRECT_URI, **datos)
    request.session["intento_google"] = {"state": datos["state"], "vence": time.time() + 600,
        "accion": accion, "usuario": request.user.pk}
    return JsonResponse({"url": datos["url"]})


def obtener_alta_google(request):
    expirar_sanciones_vencidas()
    pendiente = request.session.get("alta_google_pendiente")
    if not isinstance(pendiente, dict) or pendiente.get("vence", 0) < time.time():
        request.session.pop("alta_google_pendiente", None)
        raise Problema(401, "alta_google_expirada", "Vuelve a continuar con Google para crear tu cuenta.")
    return pendiente


@never_cache
@api("GET")
def alta_google_pendiente(request):
    pendiente = obtener_alta_google(request)
    return JsonResponse({"nombre": pendiente["nombre"], "correo": pendiente["correo"]})


@never_cache
@api("POST")
def alta_google_crear(request):
    pendiente = obtener_alta_google(request)
    if request.POST.get("acepto_terminos") != "true":
        raise Problema(400, "terminos_requeridos", "Acepta los términos y el aviso de tratamiento de datos para crear tu cuenta.")
    nombre = request.POST.get("nombre", "").strip()
    if not nombre or len(nombre) > 150:
        raise Problema(400, "nombre_invalido", "Escribe un nombre de hasta 150 caracteres.")
    foto = request.FILES.get("foto")
    if foto:
        validar_foto(foto)

    sub = pendiente.get("sub", "")
    correo = pendiente.get("correo", "")
    usuario_pendiente_id = pendiente.get("usuario_id")
    foto_anterior = ""
    try:
        with transaction.atomic():
            if usuario_pendiente_id:
                try:
                    usuario = Usuario.objects.select_for_update().get(pk=usuario_pendiente_id)
                except Usuario.DoesNotExist as error:
                    raise Problema(401, "alta_google_expirada", "Vuelve a continuar con Google para completar tu cuenta.") from error
                if not usuario.is_active:
                    sancion = sancion_activa(usuario)
                    if sancion:
                        rechazar_por_sancion(sancion)
                    raise Problema(403, "cuenta_inactiva", "Cuenta inactiva.")
                identidad = IdentidadGoogle.objects.select_for_update().filter(
                    google_sub=sub, usuario=usuario).first()
                if not identidad:
                    raise Problema(409, "identidad_ocupada", "Esta cuenta de Google ya no está vinculada.")
                perfil, _ = PerfilUsuario.objects.get_or_create(usuario=usuario)
            else:
                if IdentidadGoogle.objects.filter(google_sub=sub).exists():
                    raise Problema(409, "identidad_ocupada", "Esta cuenta de Google ya está vinculada.")
                if correo and Usuario.objects.filter(email__iexact=correo).exists():
                    raise Problema(409, "vincular_desde_cuenta", "Entra con tu cuenta y vincula Google desde tu perfil.")
                usuario = Usuario.objects.create_user(
                    username=f"ciudadano-{uuid.uuid4().hex[:12]}", email=correo, first_name=nombre)
                IdentidadGoogle.objects.create(usuario=usuario, google_sub=sub)
                perfil = PerfilUsuario(usuario=usuario)

            usuario.first_name = nombre
            usuario.save(update_fields=["first_name"])
            foto_anterior = perfil.foto.name if perfil.foto else ""
            if foto:
                perfil.foto = foto
            perfil.consentimiento_aceptado_en = timezone.now()
            perfil.consentimiento_version = VERSION_TERMINOS
            perfil.save()
            foto_nueva = perfil.foto.name if perfil.foto else ""
            if foto_anterior and foto_anterior != foto_nueva:
                transaction.on_commit(lambda nombre_foto=foto_anterior: default_storage.delete(nombre_foto))
    except IntegrityError as error:
        raise Problema(409, "identidad_ocupada", "No pudimos vincular esta identidad de Google.") from error

    request.session.pop("alta_google_pendiente", None)
    abrir_sesion(request, usuario)
    return estado(request)


@transaction.atomic
def resolver_identidad(claims, vincular_a):
    sub = claims.get("sub")
    if not isinstance(sub, str) or not 0 < len(sub) <= 255:
        raise Problema(400, "identidad_invalida", "Google no confirmó la identidad.")
    identidad = IdentidadGoogle.objects.select_related("usuario").filter(google_sub=sub).first()
    if identidad:
        if vincular_a and identidad.usuario_id != vincular_a.pk:
            raise Problema(409, "identidad_ocupada", "Esta identidad pertenece a otra cuenta.")
        usuario = identidad.usuario
    else:
        usuario = vincular_a
        if usuario is None:
            raise Problema(409, "registro_pendiente", "Completa tu perfil para crear una cuenta.")
        IdentidadGoogle.objects.create(usuario=usuario, google_sub=sub)
    if not usuario.is_active:
        sancion = sancion_activa(usuario)
        if sancion:
            rechazar_por_sancion(sancion)
        raise Problema(403, "cuenta_inactiva", "Cuenta inactiva.")
    return usuario


@never_cache
@api("GET")
def callback_google(request):
    expirar_sanciones_vencidas()
    intento = request.session.get("intento_google", {})
    recibido = request.GET.get("state", "")
    resultado = "intento_invalido"
    if recibido and secretos_iguales(recibido, intento.get("state", "")):
        request.session.pop("intento_google")
        cliente = oauth.google
        try:
            if intento["vence"] < time.time() or intento["usuario"] != request.user.pk:
                raise Problema(400, "intento_invalido", "El intento caducó.")
            if request.GET.get("error") == "access_denied":
                raise Problema(400, "cancelado", "Acceso cancelado.")
            if not request.GET.get("code"):
                raise Problema(400, "intento_invalido", "Falta el código.")
            token = cliente.authorize_access_token(request, leeway=0)
            claims = token.get("userinfo") or {}
            if not isinstance(claims, dict):
                raise Problema(400, "identidad_invalida", "Google no confirmó la identidad.")
            if intento["accion"] == "vincular":
                usuario = resolver_identidad(claims, request.user)
                abrir_sesion(request, usuario)
                resultado = "ok"
            else:
                sub = claims.get("sub")
                if not isinstance(sub, str) or not 0 < len(sub) <= 255:
                    raise Problema(400, "identidad_invalida", "Google no confirmó la identidad.")
                identidad = IdentidadGoogle.objects.select_related("usuario").filter(google_sub=sub).first()
                if identidad:
                    if not identidad.usuario.is_active:
                        sancion = sancion_activa(identidad.usuario)
                        if sancion:
                            rechazar_por_sancion(sancion)
                        raise Problema(403, "cuenta_inactiva", "Cuenta inactiva.")
                    perfil = PerfilUsuario.objects.filter(usuario=identidad.usuario).only(
                        "consentimiento_aceptado_en").first()
                    if not perfil or not perfil.consentimiento_aceptado_en:
                        nombre = claims.get("name", "")
                        nombre = nombre.strip()[:150] if isinstance(nombre, str) else ""
                        request.session["alta_google_pendiente"] = {
                            "sub": sub,
                            "correo": identidad.usuario.email,
                            "nombre": nombre or identidad.usuario.first_name or identidad.usuario.username,
                            "usuario_id": identidad.usuario_id,
                            "vence": time.time() + 900,
                        }
                        resultado = "registro_pendiente"
                    else:
                        abrir_sesion(request, identidad.usuario)
                        resultado = "ok"
                else:
                    email = claims.get("email") if claims.get("email_verified") is True else ""
                    email = email.strip().lower() if isinstance(email, str) else ""
                    if len(email) > 254:
                        raise Problema(400, "identidad_invalida", "Google devolvió un correo no válido.")
                    if email and Usuario.objects.filter(email__iexact=email).exists():
                        raise Problema(409, "vincular_desde_cuenta", "Entra con tu cuenta y vincula Google.")
                    nombre = claims.get("name", "")
                    nombre = nombre.strip()[:150] if isinstance(nombre, str) else ""
                    request.session["alta_google_pendiente"] = {
                        "sub": sub, "correo": email, "nombre": nombre,
                        "vence": time.time() + 900,
                    }
                    resultado = "registro_pendiente"
        except Problema as error:
            resultado = error.datos["codigo"]
        except IntegrityError:
            resultado = "identidad_ocupada"
        except (OAuthError, JoseError, ValueError, KeyError):
            resultado = "identidad_invalida"
        except RequestException:
            resultado = "google_indisponible"
        finally:
            cliente.framework.clear_state_data(request.session, recibido)
    if resultado == "registro_pendiente":
        destino = "/registro/google"
    elif resultado == "ok" and request.user.is_superuser:
        destino = "/administracion"
    elif resultado == "ok" and request.user.has_perm("cuentas.gestionar_sanciones"):
        destino = "/moderacion"
    else:
        destino = f"/comunidad?acceso={resultado}"
    respuesta = redirect(destino)
    respuesta["Referrer-Policy"] = "no-referrer"
    return respuesta


def secretos_iguales(a, b):
    return secrets.compare_digest(a.encode(), b.encode())

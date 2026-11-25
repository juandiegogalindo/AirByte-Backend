from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from joserfc.errors import JoseError

from .models import IdentidadGoogle


@override_settings(GOOGLE_CLIENT_ID="test", GOOGLE_CLIENT_SECRET="test")
class GoogleTest(TestCase):
    iniciar = "/api/v1/auth/google/iniciar"
    callback = "/api/v1/auth/google/callback"
    crear = "/api/v1/auth/google/crear"

    def setUp(self):
        parches = patch("cuentas.views.oauth")
        self.google = parches.start().google
        self.addCleanup(parches.stop)
        self.google.create_authorization_url.return_value = {"url": "https://accounts.google.com/", "state": "inicio"}
        self.google.authorize_access_token.return_value = {"userinfo": {"sub": "google-123",
            "email": "demo@example.com", "email_verified": True}, "access_token": "efimero"}

    def iniciar_intento(self, client, accion="entrar"):
        csrf = client.get("/api/v1/sesion").json()["csrf"]
        return client.post(self.iniciar, {"accion": accion}, content_type="application/json", HTTP_X_CSRFTOKEN=csrf)

    def completar(self, client):
        return client.get(self.callback, {"state": "inicio", "code": "codigo"})

    def test_nueva_cuenta_y_retorno(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(self.iniciar_intento(client).status_code, 200)
        self.assertEqual(self.completar(client).url, "/registro/google")
        self.assertFalse(IdentidadGoogle.objects.exists())
        csrf = client.get("/api/v1/sesion").json()["csrf"]
        sin_terminos = client.post(self.crear, {"nombre": "Demo"}, HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(sin_terminos.status_code, 400)
        creada = client.post(self.crear, {"nombre": "Demo", "acepto_terminos": "true"}, HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(creada.status_code, 200)
        cuenta = IdentidadGoogle.objects.get().usuario
        self.assertFalse(cuenta.has_usable_password())
        self.assertNotIn("efimero", str(dict(client.session)))
        self.assertEqual(self.completar(client).url, "/comunidad?acceso=intento_invalido")
        client.logout()
        self.iniciar_intento(client)
        self.assertEqual(self.completar(client).url, "/comunidad?acceso=ok")
        self.assertEqual(int(client.session["_auth_user_id"]), cuenta.pk)
        self.assertEqual(User.objects.count(), 1)

    def test_vincular_sin_apropiarse_por_correo(self):
        local = User.objects.create_user("local", email="demo@example.com")
        self.iniciar_intento(self.client)
        self.assertEqual(self.completar(self.client).url, "/comunidad?acceso=vincular_desde_cuenta")
        self.assertFalse(IdentidadGoogle.objects.exists())
        self.client.force_login(local)
        self.iniciar_intento(self.client, "vincular")
        self.assertEqual(self.completar(self.client).url, "/comunidad?acceso=ok")
        self.assertEqual(IdentidadGoogle.objects.get().usuario, local)
        otro = User.objects.create_user("otro")
        self.client.force_login(otro)
        self.iniciar_intento(self.client, "vincular")
        self.assertEqual(self.completar(self.client).url, "/comunidad?acceso=identidad_ocupada")

    def test_state_cancelacion_y_token_rechazado(self):
        self.iniciar_intento(self.client)
        self.assertEqual(self.client.get(self.callback, {"state": "otro", "code": "x"}).url,
                         "/comunidad?acceso=intento_invalido")
        self.google.authorize_access_token.assert_not_called()
        self.assertEqual(self.client.get(self.callback, {"state": "inicio", "error": "access_denied"}).url,
                         "/comunidad?acceso=cancelado")
        self.iniciar_intento(self.client)
        self.google.authorize_access_token.side_effect = JoseError("Token rechazado por el proveedor OIDC")
        self.assertEqual(self.completar(self.client).url, "/comunidad?acceso=identidad_invalida")
        self.assertFalse(IdentidadGoogle.objects.exists())


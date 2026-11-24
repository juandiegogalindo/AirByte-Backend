from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from joserfc.errors import JoseError

from .models import IdentidadGoogle


@override_settings(GOOGLE_CLIENT_ID="test", GOOGLE_CLIENT_SECRET="test")
class GoogleTest(TestCase):
    iniciar = "/api/v1/auth/google/iniciar"
    callback = "/api/v1/auth/google/callback"

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
        self.assertEqual(self.completar(client).url, "/?acceso=ok")
        cuenta = IdentidadGoogle.objects.get().usuario
        self.assertFalse(cuenta.has_usable_password())
        self.assertNotIn("efimero", str(dict(client.session)))
        self.assertEqual(self.completar(client).url, "/?acceso=intento_invalido")
        client.logout()
        self.iniciar_intento(client)
        self.assertEqual(self.completar(client).url, "/?acceso=ok")
        self.assertEqual(int(client.session["_auth_user_id"]), cuenta.pk)
        self.assertEqual(User.objects.count(), 1)

    def test_vincular_sin_apropiarse_por_correo(self):
        local = User.objects.create_user("local", email="demo@example.com")
        self.iniciar_intento(self.client)
        self.assertEqual(self.completar(self.client).url, "/?acceso=vincular_desde_cuenta")
        self.assertFalse(IdentidadGoogle.objects.exists())
        self.client.force_login(local)
        self.iniciar_intento(self.client, "vincular")
        self.assertEqual(self.completar(self.client).url, "/?acceso=ok")
        self.assertEqual(IdentidadGoogle.objects.get().usuario, local)
        otro = User.objects.create_user("otro")
        self.client.force_login(otro)
        self.iniciar_intento(self.client, "vincular")
        self.assertEqual(self.completar(self.client).url, "/?acceso=identidad_ocupada")

    def test_state_cancelacion_y_token_rechazado(self):
        self.iniciar_intento(self.client)
        self.assertEqual(self.client.get(self.callback, {"state": "otro", "code": "x"}).url,
                         "/?acceso=intento_invalido")
        self.google.authorize_access_token.assert_not_called()
        self.assertEqual(self.client.get(self.callback, {"state": "inicio", "error": "access_denied"}).url,
                         "/?acceso=cancelado")
        self.iniciar_intento(self.client)
        self.google.authorize_access_token.side_effect = JoseError("Token rechazado por el proveedor OIDC")
        self.assertEqual(self.completar(self.client).url, "/?acceso=identidad_invalida")
        self.assertFalse(IdentidadGoogle.objects.exists())


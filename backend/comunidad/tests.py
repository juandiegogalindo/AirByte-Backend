from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Group, User
from django.test import Client, TestCase


class ComunidadTest(TestCase):
    def test_sesiones_autoria_y_moderacion(self):
        api = "/api/v1"
        clave = "Test-Community-2025!"
        visitante = Client(enforce_csrf_checks=True)
        autor = Client(enforce_csrf_checks=True)
        reporte = {"localidad": "tunjuelito", "categoria": "humo", "texto": "Humo cerca al parque"}
        csrf = lambda client: {"HTTP_X_CSRFTOKEN": client.get(api + "/sesion").json()["csrf"]}
        self.assertEqual(visitante.get(api + "/reportes").status_code, 200)
        self.assertEqual(visitante.post(api + "/reportes", reporte, content_type="application/json", **csrf(visitante)).status_code, 401)
        self.assertEqual(autor.post(api + "/registro", {"usuario": "usuario-demo", "contrasena": clave},
            content_type="application/json", **csrf(autor)).status_code, 201)
        self.assertEqual(autor.post(api + "/sesion", {"usuario": "usuario-demo", "contrasena": clave},
            content_type="application/json", **csrf(autor)).status_code, 200)
        self.assertEqual(autor.post(api + "/reportes", reporte, content_type="application/json").status_code, 403)
        self.assertEqual(autor.post(api + "/reportes", {**reporte, "categoria": "falsa"},
            content_type="application/json", **csrf(autor)).status_code, 400)
        nuevo = autor.post(api + "/reportes", reporte, content_type="application/json", **csrf(autor))
        self.assertEqual(nuevo.status_code, 201)
        pk = nuevo.json()["id"]
        hilo = f"{api}/reportes/{pk}/comentarios"
        comentario = autor.post(hilo, {"texto": "También lo observé"}, content_type="application/json", **csrf(autor))
        self.assertEqual(comentario.status_code, 201)
        otro = Client()
        otro.force_login(User.objects.create_user("otro"))
        self.assertEqual(otro.delete(f"{api}/reportes/{pk}").status_code, 403)
        staff = User.objects.create_user("moderador", is_staff=True)
        staff.groups.add(Group.objects.get(name="Moderadores"))
        otro.force_login(staff)
        self.assertEqual(otro.post("/admin/comunidad/reporte/", {"action": "ocultar", "_selected_action": [pk]}).status_code, 302)
        self.assertEqual(LogEntry.objects.filter(user=staff, object_id=str(pk)).count(), 1)
        self.assertEqual(visitante.get(hilo).status_code, 404)
        self.assertEqual(autor.post(hilo, {"texto": "Oculto"}, content_type="application/json", **csrf(autor)).status_code, 404)
        self.assertEqual(autor.delete(f"{api}/reportes/{pk}", **csrf(autor)).status_code, 204)
        self.assertEqual(autor.delete(api + "/sesion", **csrf(autor)).status_code, 204)
        self.assertIsNone(autor.get(api + "/sesion").json()["usuario"])


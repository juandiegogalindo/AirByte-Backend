from django.contrib import admin
from django.db import transaction
from django.utils import timezone

from .models import Comentario, Reporte


@admin.register(Reporte, Comentario)
class ModeracionAdmin(admin.ModelAdmin):
    list_display = ("id", "autor", "texto", "creado_en", "oculto")
    list_filter = ("oculto",)
    actions = ["ocultar"]

    def has_ocultar_permission(self, request):
        return request.user.has_perm(f"comunidad.ocultar_{self.opts.model_name}")

    @admin.action(permissions=["ocultar"], description="Ocultar publicaciones seleccionadas")
    @transaction.atomic
    def ocultar(self, request, queryset):
        for obj in queryset.select_for_update().filter(oculto=False):
            obj.oculto = True
            obj.ocultado_en = timezone.now()
            obj.ocultado_por = request.user
            obj.save(update_fields=["oculto", "ocultado_en", "ocultado_por"])
            self.log_change(request, obj, "Publicación ocultada.")

from django.core.management.base import BaseCommand, CommandError
from requests import RequestException

from aire.actual import sincronizar


class Command(BaseCommand):
    help = "Guarda las observaciones recientes publicadas por la RMCAB."

    def handle(self, *args, **options):
        try:
            filas = sincronizar()
        except (RequestException, ValueError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(f"{filas} filas horarias actualizadas.")

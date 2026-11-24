import logging
import re


class OcultarConsultaOAuth(logging.Filter):
    def filter(self, record):
        mensaje = record.getMessage()
        limpio = re.sub(r"(/api/v1/auth/google/callback)\?[^\s\x22]+", r"\1", mensaje)
        if limpio != mensaje:
            record.msg = limpio
            record.args = ()
        return True


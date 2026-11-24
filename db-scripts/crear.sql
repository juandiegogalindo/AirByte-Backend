-- Ejecuta este archivo conectado a la base postgres, no a airbyte.
CREATE DATABASE airbyte
    WITH OWNER = airbyte
    ENCODING = 'UTF8'
    TEMPLATE = template0;

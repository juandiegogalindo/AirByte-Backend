-- Ejecuta este archivo conectado a la base postgres, no a airbyte.
-- DROP ... WITH (FORCE) desconecta las sesiones que el usuario conectado pueda terminar.
DROP DATABASE IF EXISTS airbyte WITH (FORCE);

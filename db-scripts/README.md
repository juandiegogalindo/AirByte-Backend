# Scripts de PostgreSQL

Los archivos `.sql` usan el nombre de base `airbyte` y están pensados para el Query Tool de pgAdmin. Los archivos `.ps1` leen `.env` desde la raíz del proyecto y requieren `createdb`, `dropdb`, `psql` en el `PATH`, el rol indicado por `PGUSER` y una base configurada con `PGDATABASE`.

## Archivos SQL para pgAdmin

- Ejecuta [eliminar.sql](eliminar.sql) desde una conexión a la base `postgres` como un rol que pueda borrar `airbyte`.
- Ejecuta [crear.sql](crear.sql) desde `postgres`; crea `airbyte` y la asigna al rol `airbyte`.
- Ejecuta [poblar.sql](poblar.sql) desde la nueva base `airbyte`. Es un volcado SQL del esquema, catálogos y datos históricos `rmcab-v1`; después aplica las migraciones nuevas con `python backend/manage.py migrate`.

`poblar.sql` mide aproximadamente 44 MB y contiene 271.584 horas históricas. Es una instantánea del esquema y datos históricos; no contiene usuarios, fotos ni publicaciones. Si cambian las migraciones o el histórico, aplica las migraciones pendientes con Django. Para una carga reproducible desde el CSV, usa el script PowerShell de abajo, que llama a las migraciones e importador de Django.

## Crear y poblar

```powershell
.\db-scripts\crear-base.ps1
.\db-scripts\poblar-base.ps1
```

`crear-base.ps1` crea la base vacía con propietario `PGUSER`. `poblar-base.ps1` aplica las migraciones de Django, crea los catálogos de localidades y estaciones, y carga `datos/RMCAB/dataset_RMCAB_limpio.csv` como `rmcab-v1`. La carga histórica se puede repetir sin duplicar lecturas.

Para importar otra edición del consolidado:

```powershell
.\db-scripts\poblar-base.ps1 -Archivo .\datos\RMCAB\dataset_RMCAB_limpio_v2.csv -VersionDatos rmcab-v2
```

Si solo quieres aplicar migraciones y catálogos, sin cargar el CSV:

```powershell
.\db-scripts\poblar-base.ps1 -SoloMigraciones
```

## Eliminar y recrear

Detén Django y desconecta pgAdmin de esa base antes de borrarla. El script intenta cerrar las sesiones que `PGUSER` tenga permiso de terminar; PostgreSQL no permite que el rol de la aplicación desconecte sesiones de superusuario. Luego ejecuta:

```powershell
.\db-scripts\eliminar-base.ps1
.\db-scripts\crear-base.ps1
.\db-scripts\poblar-base.ps1
```

El script de eliminación pide escribir el nombre exacto de `PGDATABASE` antes de borrar y se niega a operar sobre `postgres`, `template0` o `template1`. No elimina archivos ni bases ajenas al proyecto.

Los scripts no crean usuarios ni contraseñas predeterminadas. Después de poblar una base nueva, crea la cuenta administradora con `python backend/manage.py createsuperuser`.

param(
    [string]$Archivo,
    [string]$VersionDatos = 'rmcab-v1',
    [switch]$SoloMigraciones
)

. (Join-Path $PSScriptRoot 'common.ps1')
$config = Get-AirByteDbConfig
$python = Join-Path $config.Root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) { throw 'No encuentro Python. Instala el entorno del proyecto o agrega python al PATH.' }
    $python = if ($pythonCommand.Source) { $pythonCommand.Source } else { $pythonCommand.Name }
}
$manage = Join-Path $config.Root 'backend\manage.py'

if (-not $SoloMigraciones) {
    if (-not $Archivo) { $Archivo = Join-Path $config.Root 'datos\RMCAB\dataset_RMCAB_limpio.csv' }
    if (-not [System.IO.Path]::IsPathRooted($Archivo)) { $Archivo = Join-Path $config.Root $Archivo }
    if (-not (Test-Path -LiteralPath $Archivo -PathType Leaf)) {
        throw "No encuentro el consolidado '$Archivo'. Indica -Archivo o usa -SoloMigraciones."
    }
}

$psql = Resolve-PostgresTool 'psql'
& $psql '--no-psqlrc' "--dbname=$($config.Database)" '--tuples-only' '--no-align' '--command=SELECT 1'
if ($LASTEXITCODE -ne 0) {
    throw "No se pudo conectar a '$($config.Database)'. Créala primero con crear-base.ps1 y revisa PGHOST, PGPORT y PGUSER en .env."
}

Write-Host 'Aplicando migraciones y catálogos iniciales…'
& $python $manage 'migrate' '--noinput'
if ($LASTEXITCODE -ne 0) { throw 'Fallaron las migraciones de Django.' }

if (-not $SoloMigraciones) {
    Write-Host "Importando el histórico '$VersionDatos'…"
    & $python $manage 'importar_rmcab' '--archivo' $Archivo '--version-datos' $VersionDatos
    if ($LASTEXITCODE -ne 0) { throw 'Falló la importación del histórico RMCAB.' }
}

Write-Host 'Base de datos poblada.'
Write-Host 'No se crearon usuarios predeterminados. Crea el administrador con: python backend/manage.py createsuperuser'

. (Join-Path $PSScriptRoot 'common.ps1')
$config = Get-AirByteDbConfig

$createdb = Resolve-PostgresTool 'createdb'
$arguments = @('--maintenance-db=postgres', "--owner=$($config.User)", '--encoding=UTF8', '--template=template0', $config.Database)
& $createdb @arguments
if ($LASTEXITCODE -ne 0) {
    throw "No se pudo crear '$($config.Database)'. Comprueba que no exista y que el rol '$($config.User)' tenga permiso CREATEDB."
}
Write-Host "Base '$($config.Database)' creada con propietario '$($config.User)'. Ejecuta poblar-base.ps1 para aplicar las migraciones y cargar el histórico."

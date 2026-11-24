param([string]$ConfirmarNombre)

. (Join-Path $PSScriptRoot 'common.ps1')
$config = Get-AirByteDbConfig

Write-Warning "Esta operación eliminará permanentemente la base '$($config.Database)' y todos sus datos."
Write-Host 'Detén Django y desconecta pgAdmin de esta base. --force cierra las sesiones que PGUSER tenga permiso de terminar.'
if (-not $ConfirmarNombre) { $ConfirmarNombre = Read-Host "Escribe exactamente '$($config.Database)' para confirmar" }
if ($ConfirmarNombre -cne $config.Database) {
    Write-Host 'Operación cancelada; no se eliminó ninguna base.'
    return
}

$dropdb = Resolve-PostgresTool 'dropdb'
$arguments = @('--if-exists', '--force', '--maintenance-db=postgres', $config.Database)
& $dropdb @arguments
if ($LASTEXITCODE -ne 0) {
    throw "No se pudo eliminar '$($config.Database)'. Cierra las conexiones activas de pgAdmin y comprueba que PGUSER tenga permisos."
}
Write-Host "Base '$($config.Database)' eliminada."

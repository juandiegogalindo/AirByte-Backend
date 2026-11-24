function Get-AirByteDbConfig {
    $root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    $envPath = Join-Path $root '.env'
    if (-not (Test-Path -LiteralPath $envPath)) {
        throw "No existe el archivo .env en $root. Cópialo desde .env.example y completa PGDATABASE, PGUSER y PGPASSWORD."
    }

    $values = @{}
    foreach ($line in Get-Content -LiteralPath $envPath) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#')) { continue }
        if ($trimmed -match '^([A-Z][A-Z0-9_]*)=(.*)$') {
            $value = $Matches[2].Trim()
            if ($value.Length -ge 2 -and (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'")))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            $values[$Matches[1]] = $value
        }
    }

    $database = if ($env:PGDATABASE) { $env:PGDATABASE } elseif ($values.PGDATABASE) { $values.PGDATABASE } else { 'airbyte' }
    $user = if ($env:PGUSER) { $env:PGUSER } elseif ($values.PGUSER) { $values.PGUSER } else { 'airbyte' }
    foreach ($identifier in @($database, $user)) {
        if ($identifier -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
            throw 'PGDATABASE y PGUSER deben contener solo letras, números y guion bajo, y no pueden comenzar por número.'
        }
    }
    if ($database -in @('postgres', 'template0', 'template1')) {
        throw "Por seguridad, los scripts no operan sobre la base del sistema '$database'."
    }

    $env:PGDATABASE = $database
    $env:PGUSER = $user
    foreach ($name in @('PGHOST', 'PGPORT', 'PGPASSWORD')) {
        if (-not [Environment]::GetEnvironmentVariable($name, 'Process') -and $values.ContainsKey($name)) {
            [Environment]::SetEnvironmentVariable($name, $values[$name], 'Process')
        }
    }

    return [pscustomobject]@{ Root = $root; Database = $database; User = $user }
}

function Resolve-PostgresTool([string]$name) {
    $command = Get-Command $name -ErrorAction SilentlyContinue
    if ($command) {
        if ($command.Source) { return $command.Source }
        return $command.Name
    }

    $installRoot = 'C:\Program Files\PostgreSQL'
    if (Test-Path -LiteralPath $installRoot) {
        $installations = Get-ChildItem -LiteralPath $installRoot -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^\d+(\.\d+)?$' } |
            Sort-Object { if ($_.Name -match '^\d+$') { [version]"$($_.Name).0" } else { [version]$_.Name } } -Descending
        foreach ($installation in $installations) {
            $candidate = Join-Path $installation.FullName "bin\$name.exe"
            if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
        }
    }
    throw "No encuentro '$name'. Agrega la carpeta bin de PostgreSQL al PATH y vuelve a intentarlo."
}

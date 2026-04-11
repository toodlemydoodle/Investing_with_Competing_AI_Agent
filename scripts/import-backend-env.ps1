param(
    [string]$EnvPath
)

$ErrorActionPreference = 'Stop'

if (-not $EnvPath) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
    $EnvPath = Join-Path $RepoRoot 'backend\.env'
}

$loadedValues = @{}

if (-not (Test-Path $EnvPath)) {
    return $loadedValues
}

foreach ($rawLine in Get-Content $EnvPath) {
    $line = $rawLine.Trim()
    if (-not $line -or $line.StartsWith('#')) {
        continue
    }

    $separatorIndex = $line.IndexOf('=')
    if ($separatorIndex -lt 1) {
        continue
    }

    $key = $line.Substring(0, $separatorIndex).Trim()
    $value = $line.Substring($separatorIndex + 1).Trim()

    if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
        $value = $value.Substring(1, $value.Length - 2)
    }

    $loadedValues[$key] = $value
    [Environment]::SetEnvironmentVariable($key, $value, 'Process')
}

return $loadedValues

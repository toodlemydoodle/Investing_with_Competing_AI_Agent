$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $RepoRoot '.tools\python\python.exe'
$BackendDir = Join-Path $RepoRoot 'backend'
$HostAddress = '127.0.0.1'
$Port = 8000

if (-not (Test-Path $PythonExe)) {
    throw 'Embedded Python not found under .tools\python\python.exe'
}

Push-Location $BackendDir
try {
    Write-Host "Starting backend on http://$HostAddress`:$Port"
    & $PythonExe -m uvicorn app.main:app --host $HostAddress --port $Port
} finally {
    Pop-Location
}

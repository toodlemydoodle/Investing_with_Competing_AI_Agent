param(
    [bool]$IncludeMoomoo = $true,
    [string]$MoomooPackagePath
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $RepoRoot '.tools\python\python.exe'
$PipExe = Join-Path $RepoRoot '.tools\python\Scripts\pip.exe'
$EnvSource = Join-Path $RepoRoot '.env.example'
$BackendEnv = Join-Path $RepoRoot 'backend\.env'

if (-not (Test-Path $PythonExe)) {
    throw 'Embedded Python not found under .tools\python\python.exe'
}

if (-not (Test-Path $PipExe)) {
    throw 'Embedded pip not found under .tools\python\Scripts\pip.exe'
}

if (-not (Test-Path $BackendEnv)) {
    Copy-Item $EnvSource $BackendEnv
    Write-Host 'Created backend\.env from .env.example'
}

Push-Location $RepoRoot
try {
    Write-Host 'Checking packaging tools...'
    & $PythonExe -c "import setuptools, wheel" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Installing packaging tools...'
        & $PipExe install --disable-pip-version-check --upgrade setuptools wheel
        if ($LASTEXITCODE -ne 0) {
            throw 'Failed to install packaging tools.'
        }
    }

    Write-Host 'Installing backend runtime dependencies...'
    if ($IncludeMoomoo) {
        & $PipExe install --disable-pip-version-check --no-build-isolation -e .\backend[moomoo]
    } else {
        & $PipExe install --disable-pip-version-check --no-build-isolation -e .\backend
    }
    if ($LASTEXITCODE -ne 0) {
        throw 'Backend package install failed.'
    }

    & $PythonExe -c "import sys; sys.path.insert(0, 'backend'); import app.main" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw 'Backend import verification failed after install.'
    }

    if ($IncludeMoomoo) {
        Write-Host 'Checking moomoo package availability...'
        & $PythonExe -c "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('moomoo') else 1)"
        if ($LASTEXITCODE -ne 0) {
            if ($MoomooPackagePath) {
                if (-not (Test-Path $MoomooPackagePath)) {
                    throw "Moomoo package path not found: $MoomooPackagePath"
                }
                Write-Host "Installing moomoo package from $MoomooPackagePath"
                & $PipExe install --disable-pip-version-check --no-build-isolation $MoomooPackagePath
                if ($LASTEXITCODE -ne 0) {
                    throw 'Local moomoo package install failed.'
                }
            } else {
                throw 'Moomoo package is not installed in embedded Python. Install it separately or rerun with -MoomooPackagePath <local package path>.'
            }
        }
    }
} finally {
    Pop-Location
}

Write-Host 'Backend setup complete.'
Write-Host 'Next: run scripts\run-backend.ps1'

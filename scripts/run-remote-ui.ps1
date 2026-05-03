param(
    [string]$TunnelToken = '',
    [string]$CloudflaredPath = '',
    [string]$BackendHealthUrl = '',
    [string]$EnvFile = '',
    [int]$BackendWarmupSeconds = 20,
    [switch]$BackendAlreadyRunning
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$EnvLoader = Join-Path $PSScriptRoot 'import-backend-env.ps1'
$BackendScript = Join-Path $PSScriptRoot 'run-backend.ps1'
$TunnelScript = Join-Path $PSScriptRoot 'run-cloudflare-tunnel.ps1'

if (-not (Test-Path $EnvLoader)) {
    throw 'Missing scripts\import-backend-env.ps1'
}

if (-not (Test-Path $TunnelScript)) {
    throw 'Missing scripts\run-cloudflare-tunnel.ps1'
}

if (-not $EnvFile) {
    $EnvFile = Join-Path $RepoRoot 'backend\.env'
}

$null = & $EnvLoader -EnvPath $EnvFile

if (-not $TunnelToken) {
    $TunnelToken = $env:CLOUDFLARE_TUNNEL_TOKEN
}

if (-not $BackendHealthUrl) {
    $BackendHealthUrl = $env:CLOUDFLARE_BACKEND_HEALTH_URL
}

if (-not $BackendHealthUrl) {
    $BackendHealthUrl = 'http://127.0.0.1:8000/health'
}

$backendProc = $null

if (-not $BackendAlreadyRunning) {
    if (-not (Test-Path $BackendScript)) {
        throw 'Missing scripts\run-backend.ps1'
    }

    Write-Host 'Starting backend...'
    $backendProc = Start-Process powershell -ArgumentList @(
        '-ExecutionPolicy', 'Bypass', '-File', $BackendScript
    ) -NoNewWindow -PassThru -WorkingDirectory $RepoRoot

    $deadline = (Get-Date).AddSeconds([Math]::Max($BackendWarmupSeconds, 5))
    $healthy = $false
    do {
        Start-Sleep -Seconds 1
        try {
            $null = Invoke-WebRequest -Uri $BackendHealthUrl -UseBasicParsing -TimeoutSec 3
            $healthy = $true
        } catch {
            $healthy = $false
        }
    } until ($healthy -or (Get-Date) -ge $deadline)

    if (-not $healthy) {
        Write-Warning "Backend did not respond at $BackendHealthUrl within $BackendWarmupSeconds seconds. Proceeding anyway."
    }
}

if (-not $TunnelToken) {
    throw 'CLOUDFLARE_TUNNEL_TOKEN is empty. Check that backend\.env contains it.'
}

Write-Host 'Backend ready. Starting Cloudflare Tunnel...'
try {
    & $TunnelScript -TunnelToken $TunnelToken -CloudflaredPath $CloudflaredPath -BackendHealthUrl $BackendHealthUrl -EnvFile $EnvFile -SkipBackendCheck
} finally {
    if ($backendProc -and -not $backendProc.HasExited) {
        Write-Host 'Stopping backend...'
        $backendProc.Kill()
    }
}

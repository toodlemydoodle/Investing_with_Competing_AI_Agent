param(
    [string]$TunnelToken = '',
    [string]$CloudflaredPath = '',
    [string]$BackendHealthUrl = '',
    [string]$EnvFile = '',
    [switch]$SkipBackendCheck
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$EnvLoader = Join-Path $PSScriptRoot 'import-backend-env.ps1'

if (-not (Test-Path $EnvLoader)) {
    throw 'Missing scripts\import-backend-env.ps1'
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

function Resolve-CloudflaredPath {
    param(
        [string]$RequestedPath
    )

    if ($RequestedPath) {
        if (Test-Path $RequestedPath) {
            return (Resolve-Path $RequestedPath).Path
        }
        $requestedCommand = Get-Command $RequestedPath -ErrorAction SilentlyContinue
        if ($requestedCommand) {
            return $requestedCommand.Source
        }
        throw "cloudflared was not found at `$RequestedPath`."
    }

    $command = Get-Command 'cloudflared' -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $candidates = @(
        (Join-Path $env:ProgramFiles 'cloudflared\cloudflared.exe'),
        (Join-Path $env:ProgramFiles 'Cloudflare\cloudflared\cloudflared.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'cloudflared\cloudflared.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Cloudflare\cloudflared\cloudflared.exe')
    )
    $existingCandidates = @($candidates | Where-Object { $_ -and (Test-Path $_) })

    if ($existingCandidates.Count -gt 0) {
        return $existingCandidates[0]
    }

    throw 'cloudflared was not found on PATH or in the standard Windows install folders. Install it first, then rerun this script.'
}

if (-not $TunnelToken) {
    throw 'Set CLOUDFLARE_TUNNEL_TOKEN or pass -TunnelToken before starting the Cloudflare tunnel.'
}

$resolvedCloudflaredPath = Resolve-CloudflaredPath -RequestedPath $CloudflaredPath

if (-not $SkipBackendCheck) {
    try {
        $null = Invoke-WebRequest -Uri $BackendHealthUrl -UseBasicParsing -TimeoutSec 5
    } catch {
        throw "Backend health check failed at $BackendHealthUrl. Start the local app first or rerun with -SkipBackendCheck."
    }
}

Write-Host 'Starting Cloudflare Tunnel for the local arena UI...'
Write-Host "cloudflared path: $resolvedCloudflaredPath"
Write-Host "Backend health endpoint: $BackendHealthUrl"

& $resolvedCloudflaredPath tunnel --no-autoupdate --loglevel warn run --token $TunnelToken

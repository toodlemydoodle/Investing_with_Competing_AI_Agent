$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$DbPaths = @(
    (Join-Path $RepoRoot 'backend\trader.db'),
    (Join-Path $RepoRoot 'trader.db')
)
$EmbeddedPython = Join-Path $RepoRoot '.tools\python\python.exe'
$BrokerCutoffPath = Join-Path $RepoRoot 'backend\.broker-order-sync-cutoff.txt'

$backendProcesses = @(
    Get-Process python -ErrorAction SilentlyContinue |
        Where-Object {
            try {
                $_.Path -eq $EmbeddedPython
            } catch {
                $false
            }
        }
)

if ($backendProcesses.Count -gt 0) {
    Write-Host ('Stopping embedded backend process(es): ' + (($backendProcesses | Select-Object -ExpandProperty Id) -join ', '))
    $backendProcesses | Stop-Process -Force
    Start-Sleep -Seconds 2
}

$cutoffUtc = (Get-Date).ToUniversalTime().ToString('o')
Set-Content -Path $BrokerCutoffPath -Value $cutoffUtc -NoNewline
Write-Host "Set broker order sync cutoff to $cutoffUtc"

$existingPaths = @($DbPaths | Where-Object { Test-Path $_ })
if ($existingPaths.Count -eq 0) {
    Write-Host 'No trader.db files found under backend or repo root.'
    exit 0
}

for ($attempt = 1; $attempt -le 5; $attempt++) {
    try {
        foreach ($dbPath in $existingPaths) {
            if (Test-Path $dbPath) {
                Remove-Item -Force $dbPath
                Write-Host "Removed $dbPath"
            }
        }
        exit 0
    } catch {
        if ($attempt -eq 5) {
            throw
        }
        Start-Sleep -Milliseconds 500
    }
}

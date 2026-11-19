param([switch]$Prod)
$ErrorActionPreference = "Stop"

$root = Split-Path $PSScriptRoot -Parent
$venv = Join-Path $root ".venv\Scripts\python.exe"
if (!(Test-Path -LiteralPath $venv)) {
    throw "Python venv not found at $venv"
}

if ($Prod) {
    Push-Location (Join-Path $PSScriptRoot "frontend")
    try { npm run build } finally { Pop-Location }
    # Kill any stale process listening on 8787 before binding
    $stale = Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue
    if ($stale) {
        $pidToKill = $stale.OwningProcess | Select-Object -Unique
        Write-Host "Stopping existing process ($pidToKill) on port 8787..." -ForegroundColor Yellow
        Stop-Process -Id $pidToKill -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 600
    }

    Write-Host "Serving dashboard at http://127.0.0.1:8787" -ForegroundColor Cyan
    Push-Location $root
    try { & $venv -m uvicorn web.backend.app:app --host 127.0.0.1 --port 8787 }
    finally { Pop-Location }
}
else {
    Start-Process -FilePath $venv -ArgumentList @(
        "-m", "uvicorn", "web.backend.app:app",
        "--host", "127.0.0.1", "--port", "8787", "--reload"
    ) -WorkingDirectory $root

    Push-Location (Join-Path $PSScriptRoot "frontend")
    try {
        if (!(Test-Path -LiteralPath "node_modules")) { npm install }
        Write-Host "Dashboard dev server -> http://localhost:5173" -ForegroundColor Cyan
        npm run dev
    }
    finally { Pop-Location }
}

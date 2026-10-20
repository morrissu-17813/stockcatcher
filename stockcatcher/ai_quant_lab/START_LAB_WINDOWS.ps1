$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$dashboard = Join-Path $root 'dashboard'
Set-Location $root
Write-Host '=== Tianji AI Quant Lab V17 | isolated paper-only ===' -ForegroundColor Cyan
Write-Host 'Starting backend API at http://127.0.0.1:8765 and Vue dashboard at http://127.0.0.1:5173.' -ForegroundColor Yellow

if ((-not (Test-Path (Join-Path $dashboard 'node_modules\vite'))) -or (-not (Test-Path (Join-Path $dashboard 'node_modules\lightweight-charts')))) {
    Write-Host 'Frontend dependencies are missing; installing dashboard dependencies...' -ForegroundColor Yellow
    Set-Location $dashboard
    npm install
    if ($LASTEXITCODE -ne 0) { throw 'npm install failed. Open dashboard and run npm install, then retry.' }
    Set-Location $root
}

$backendCommand = "Set-Location '$root'; python server.py"
$frontendCommand = "Set-Location '$dashboard'; npm run dev -- --host 127.0.0.1"
Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoExit','-Command',$backendCommand) -WorkingDirectory $root
Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoExit','-Command',$frontendCommand) -WorkingDirectory $dashboard
Start-Sleep -Seconds 5
Start-Process 'http://127.0.0.1:5173/'
Write-Host 'Dashboard opened. Autonomous research remains OFF until you click start.' -ForegroundColor Green

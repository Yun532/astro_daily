$ErrorActionPreference = 'Stop'
$projectRoot = 'E:\astro-daliy'
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$logDir = Join-Path $projectRoot 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$logFile = Join-Path $logDir "daily-report-$stamp.log"
Set-Location $projectRoot
& $python -m astro_daily run *> $logFile
exit $LASTEXITCODE

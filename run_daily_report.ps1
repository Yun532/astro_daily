$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$logDir = Join-Path $projectRoot 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$logFile = Join-Path $logDir "daily-report-$stamp.log"
$retryExitCode = 75
Set-Location $projectRoot
$command = "`"$python`" -m astro_daily run --defer-if-unfresh >> `"$logFile`" 2>&1"
cmd.exe /c $command
$firstExitCode = $LASTEXITCODE
if ($firstExitCode -eq $retryExitCode) {
    Add-Content -Path $logFile -Value "Deferred retry requested. Sleeping 3600 seconds before final attempt."
    Start-Sleep -Seconds 3600
    $retryCommand = "`"$python`" -m astro_daily run --defer-if-unfresh --final-attempt >> `"$logFile`" 2>&1"
    cmd.exe /c $retryCommand
    exit $LASTEXITCODE
}
exit $firstExitCode

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $projectRoot 'logs'
$pidFile = Join-Path $logDir 'clawbot-chat.pid'
$childPidFile = Join-Path $logDir 'clawbot-chat-child.pid'

function Stop-ByPidFile {
    param(
        [string]$Path,
        [string]$Label
    )

    if (-not (Test-Path $Path)) {
        Write-Output "No $Label pid file found."
        return
    }

    $pidText = (Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    if ($pidText -notmatch '^\d+$') {
        Remove-Item -LiteralPath $Path -Force
        Write-Output "Removed invalid $Label pid file."
        return
    }

    $process = Get-Process -Id ([int]$pidText) -ErrorAction SilentlyContinue
    if ($process) {
        Stop-Process -Id $process.Id -Force
        Write-Output "Stopped $Label. PID: $pidText"
    } else {
        Write-Output "$Label was not running. PID: $pidText"
    }

    Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
}

Stop-ByPidFile -Path $childPidFile -Label 'ClawBot chat child'
Stop-ByPidFile -Path $pidFile -Label 'ClawBot chat supervisor'

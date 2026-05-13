$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$logDir = Join-Path $projectRoot 'logs'
$childPidFile = Join-Path $logDir 'clawbot-chat-child.pid'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$supervisorLog = Join-Path $logDir "clawbot-chat-supervisor-$stamp.log"

function Write-SupervisorLog {
    param([string]$Message)
    "[$(Get-Date -Format o)] $Message" | Add-Content -LiteralPath $supervisorLog -Encoding UTF8
}

Set-Location $projectRoot
Write-SupervisorLog "ClawBot chat supervisor started."

try {
    while ($true) {
        $runStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        $stdoutLog = Join-Path $logDir "clawbot-chat-$runStamp.out.log"
        $stderrLog = Join-Path $logDir "clawbot-chat-$runStamp.err.log"

        Write-SupervisorLog "Starting clawbot-chat. stdout=$stdoutLog stderr=$stderrLog"
        $process = Start-Process `
            -FilePath $python `
            -ArgumentList @('-m', 'astro_daily', '--log-level', 'INFO', 'clawbot-chat') `
            -WorkingDirectory $projectRoot `
            -RedirectStandardOutput $stdoutLog `
            -RedirectStandardError $stderrLog `
            -WindowStyle Hidden `
            -PassThru

        Set-Content -LiteralPath $childPidFile -Value $process.Id -Encoding ASCII
        Write-SupervisorLog "clawbot-chat child started. pid=$($process.Id)"

        Wait-Process -Id $process.Id
        $exitCode = $process.ExitCode
        Remove-Item -LiteralPath $childPidFile -Force -ErrorAction SilentlyContinue
        Write-SupervisorLog "clawbot-chat exited with code $exitCode. Restarting in 10 seconds."
        Start-Sleep -Seconds 10
    }
}
finally {
    Remove-Item -LiteralPath $childPidFile -Force -ErrorAction SilentlyContinue
    Write-SupervisorLog "ClawBot chat supervisor stopped."
}

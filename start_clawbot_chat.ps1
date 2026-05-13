$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$logDir = Join-Path $projectRoot 'logs'
$pidFile = Join-Path $logDir 'clawbot-chat.pid'

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (Test-Path $pidFile) {
    $existingPid = (Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    if ($existingPid -match '^\d+$') {
        $existingProcess = Get-Process -Id ([int]$existingPid) -ErrorAction SilentlyContinue
        if ($existingProcess) {
            Write-Output "ClawBot chat listener already appears to be running. PID: $existingPid"
            exit 0
        }
    }
}

$process = Start-Process `
    -FilePath 'powershell.exe' `
    -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $projectRoot 'run_clawbot_chat_forever.ps1')) `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -PassThru

Set-Content -LiteralPath $pidFile -Value $process.Id -Encoding ASCII
Write-Output "Started ClawBot chat supervisor. PID: $($process.Id)"
Write-Output "Logs: $logDir\clawbot-chat-supervisor-*.log and $logDir\clawbot-chat-*.out.log"

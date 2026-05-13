$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $projectRoot 'logs'
$pidFile = Join-Path $logDir 'clawbot-chat.pid'
$childPidFile = Join-Path $logDir 'clawbot-chat-child.pid'

function Get-PidStatus {
    param(
        [string]$Path,
        [string]$Label
    )

    if (-not (Test-Path $Path)) {
        return [PSCustomObject]@{
            Label = $Label
            Status = 'no pid file'
            Pid = $null
            Started = $null
            Running = $false
        }
    }

    $pidText = (Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    if ($pidText -notmatch '^\d+$') {
        return [PSCustomObject]@{
            Label = $Label
            Status = 'invalid pid file'
            Pid = $pidText
            Started = $null
            Running = $false
        }
    }

    $process = Get-Process -Id ([int]$pidText) -ErrorAction SilentlyContinue
    if (-not $process) {
        return [PSCustomObject]@{
            Label = $Label
            Status = 'stopped'
            Pid = $pidText
            Started = $null
            Running = $false
        }
    }

    return [PSCustomObject]@{
        Label = $Label
        Status = 'running'
        Pid = $pidText
        Started = $process.StartTime
        Running = $true
    }
}

$supervisorStatus = Get-PidStatus -Path $pidFile -Label 'ClawBot chat supervisor'
$childStatus = Get-PidStatus -Path $childPidFile -Label 'ClawBot chat child'

Write-Output "$($supervisorStatus.Label) status: $($supervisorStatus.Status)"
if ($supervisorStatus.Pid) { Write-Output "$($supervisorStatus.Label) pid: $($supervisorStatus.Pid)" }
if ($supervisorStatus.Started) { Write-Output "$($supervisorStatus.Label) started: $($supervisorStatus.Started)" }

Write-Output "$($childStatus.Label) status: $($childStatus.Status)"
if ($childStatus.Pid) { Write-Output "$($childStatus.Label) pid: $($childStatus.Pid)" }
if ($childStatus.Started) { Write-Output "$($childStatus.Label) started: $($childStatus.Started)" }

$latestSupervisor = Get-ChildItem -LiteralPath $logDir -Filter 'clawbot-chat-supervisor-*.log' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
$latestOut = Get-ChildItem -LiteralPath $logDir -Filter 'clawbot-chat-*.out.log' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
$latestErr = Get-ChildItem -LiteralPath $logDir -Filter 'clawbot-chat-*.err.log' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if ($latestSupervisor) {
    Write-Output "Latest supervisor log: $($latestSupervisor.FullName)"
    Write-Output "supervisor log updated: $($latestSupervisor.LastWriteTime)"
}
if ($latestOut) {
    Write-Output "Latest stdout: $($latestOut.FullName)"
    Write-Output "stdout updated: $($latestOut.LastWriteTime)"
}
if ($latestErr) {
    Write-Output "Latest stderr: $($latestErr.FullName)"
    Write-Output "stderr updated: $($latestErr.LastWriteTime)"
}

if ($supervisorStatus.Running -and $childStatus.Running) {
    exit 0
}
exit 1

# Register Windows Task Scheduler: SOKUHO daily sync at 12:00 noon
# Usage: .\scripts\register_sokuho_scheduled_task.ps1
# Remove: Unregister-ScheduledTask -TaskName "SOKUHO Daily Sync" -Confirm:$false
# 只在正式機註冊；開發機不跑排程（兩邊同時跑會重複寄通知）。

$TaskName = "SOKUHO Daily Sync"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ScriptPath = Join-Path $PSScriptRoot "scheduled_sync_sokuho.ps1"

if (-not (Test-Path $ScriptPath)) {
    throw "Script not found: $ScriptPath"
}

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`"" `
    -WorkingDirectory $ProjectRoot

$Trigger = New-ScheduledTaskTrigger -Daily -At "12:00PM"

# Interactive：Docker Desktop 與 Gmail 重授權（開 Edge）都需要使用者已登入。
$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Settings $Settings `
    -Description "SOKUHO Gmail sync and PosInsight import" `
    -Force

Write-Host "Registered: $TaskName"
Write-Host "Schedule: daily at 12:00"
Write-Host "Script:   $ScriptPath"
Write-Host "Logs:     $ProjectRoot\logs\sokuho_sync_YYYYMMDD.log"
Write-Host ""
Write-Host "Test now:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Check:     Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"

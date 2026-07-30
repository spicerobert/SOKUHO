# Register Windows Task Scheduler: SOKUHO daily sync at 12:00 noon
# Usage: .\scripts\register_sokuho_scheduled_task.ps1
# Remove: Unregister-ScheduledTask -TaskName "SOKUHO Daily Sync" -Confirm:$false

$TaskName = "SOKUHO Daily Sync"
$ScriptPath = "E:\Git\SOKUHO\scripts\scheduled_sync_sokuho.ps1"

if (-not (Test-Path $ScriptPath)) {
    throw "Script not found: $ScriptPath"
}

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`"" `
    -WorkingDirectory "E:\Git\SOKUHO"

$Trigger = New-ScheduledTaskTrigger -Daily -At "12:00PM"

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
Write-Host "Logs:     E:\Git\SOKUHO\logs\sokuho_sync_YYYYMMDD.log"
Write-Host ""
Write-Host "Test now:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Check:     Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"

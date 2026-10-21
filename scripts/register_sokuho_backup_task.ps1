<#
註冊 backup_sokuho_db.py 的每日排程。設計與還原方式見 backup_sokuho_db.py 檔頭。

  06:30  PosInsight 的 .bak 送到 .env 的 SOKUHO_BAK_DEST（錯開 Integration_of_POS 06:00 的備份）

  powershell -ep bypass -f scripts\register_sokuho_backup_task.ps1              # 註冊
  powershell -ep bypass -f scripts\register_sokuho_backup_task.ps1 -WhatIfOnly  # 只看設定
  powershell -ep bypass -f scripts\register_sokuho_backup_task.ps1 -Unregister  # 移除

只在正式機註冊。LogonType 用 Interactive：Docker Desktop 登入後才起來。
失敗只看 LastTaskResult 與日誌（logs\backup_sokuho_db.log）。
#>
[CmdletBinding()]
param(
  [string]$At = "06:30",
  [switch]$WhatIfOnly,
  [switch]$Unregister
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$TaskName = "SOKUHO - 每日 .bak 備份"
$LogFile = Join-Path $ProjectRoot "logs\backup_sokuho_db.log"

if ($Unregister) {
  if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "已移除排程：$TaskName"
  } else {
    Write-Host "找不到排程：$TaskName（本來就不存在）"
  }
  exit 0
}

# 註冊時就解析 uv 絕對路徑：排程環境的 PATH 可能沒有 uv
$UvExe = (Get-Command uv -ErrorAction Stop).Source
$cmdLine = "/c `"`"$UvExe`" run python scripts\backup_sokuho_db.py >> `"$LogFile`" 2>&1`""
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $cmdLine -WorkingDirectory $ProjectRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -DontStopIfGoingOnBatteries `
  -AllowStartIfOnBatteries `
  -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Write-Host "名稱：$TaskName"
Write-Host "時間：每日 $At；錯過後補跑；時限 1 小時"
Write-Host "命令：cmd.exe $cmdLine（工作目錄 $ProjectRoot）"

if ($WhatIfOnly) { Write-Host "-WhatIfOnly：沒有實際註冊"; exit 0 }

New-Item -ItemType Directory -Force (Split-Path -Parent $LogFile) | Out-Null
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
  -User "$env:USERDOMAIN\$env:USERNAME" -RunLevel Limited -Force `
  -Description "PosInsight 的 .bak 送到檔案伺服器（SOKUHO_BAK_DEST）。詳見 scripts\backup_sokuho_db.py 檔頭。" | Out-Null
Write-Host "已註冊。"

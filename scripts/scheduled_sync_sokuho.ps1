# SOKUHO 每日自動同步：Gmail 增量下載 → 匯入 PosInsight
# 由 Windows 工作排程器呼叫；日誌寫入 logs/sokuho_sync_YYYYMMDD.log
# PosInsight 在正式機的 integration_pos_db 容器內（Integration_of_POS 管理），本腳本不啟動 Docker；
# 連不上時 sync_and_import_sokuho.py 會 exit 1，由 finally 的通知信回報。

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $ProjectRoot "logs"
$LogFile = Join-Path $LogDir ("sokuho_sync_{0:yyyyMMdd}.log" -f (Get-Date))

function Write-Log {
    # -Raw：原樣寫入（給子程序輸出用，因其已自帶時間戳，避免雙重時間戳）。
    param([string]$Message, [switch]$Raw)
    $line = if ($Raw) { $Message } else { "{0:yyyy-MM-dd HH:mm:ss}  {1}" -f (Get-Date), $Message }
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    # 用 Write-Host 而非 Write-Output，避免污染函式的輸出串流
    # （否則 Invoke-Logged 會把所有 log 行連同結束碼一起回傳）。
    Write-Host $line
}

# 執行原生指令並逐行記錄輸出。python 會把正常訊息寫到 stderr，
# 若在 $ErrorActionPreference = "Stop" 下用 2>&1 管線會被誤判為終止錯誤，
# 故此處暫時切成 Continue，改以結束碼（$LASTEXITCODE）判斷成敗。
function Invoke-Logged {
    param([string]$Exe, [string[]]$Arguments)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Exe @Arguments 2>&1 | ForEach-Object {
            # 2>&1 會把 stderr 包成 ErrorRecord；取其文字內容而非物件型別名。
            $text = if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message } else { [string]$_ }
            Write-Log -Raw $text
        }
        return $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $prev
    }
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $ProjectRoot
$env:PYTHONIOENCODING = "utf-8"
# 排程環境的 PATH 可能沒有 uv；依序找 PATH、使用者安裝位置、開發機舊位置。
$UvExe = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $UvExe) {
    $UvExe = @("$env:USERPROFILE\.local\bin\uv.exe", "D:\Python\Scripts\uv.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
}
# GMAIL_LOGIN_HINT / EDGE_PROFILE_DIR / NOTIFY_EMAIL 一律由 .env 提供（每台機器的 Edge 設定檔不同）。
# 不可在這裡設預設值：Python 的 load_dotenv() 不覆蓋既有環境變數，會讓 .env 失效。
# 讓 PowerShell 以 UTF-8 解碼子程序（python）輸出，避免中文在 log 變亂碼。
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

Write-Log "=== SOKUHO scheduled sync started ==="

$exitCode = 0
$errorMsg = $null

try {
    if (-not $UvExe) {
        throw "找不到 uv（PATH、$env:USERPROFILE\.local\bin、D:\Python\Scripts 都沒有）"
    }

    Write-Log "執行 sync_and_import_sokuho.py"
    $exitCode = Invoke-Logged -Exe $UvExe -Arguments @("run", "python", "scripts/sync_and_import_sokuho.py")
    if ($exitCode -ne 0) {
        throw "sync_and_import_sokuho.py 結束碼：$exitCode"
    }

    Write-Log "=== SOKUHO scheduled sync completed OK ==="
}
catch {
    $exitCode = 1
    $errorMsg = $_.Exception.Message
    Write-Log "ERROR: $errorMsg"
    Write-Log "=== SOKUHO scheduled sync failed ==="
}
finally {
    Write-Log "檢查是否需寄送同步結果通知信（僅失敗／異常時寄出）"
    $notifyArgs = @(
        "run", "python", "scripts/send_sync_notification.py",
        "--exit-code", $exitCode
    )
    if ($LogFile) { $notifyArgs += @("--log-file", $LogFile) }
    if ($errorMsg) { $notifyArgs += @("--error-message", $errorMsg) }
    $null = Invoke-Logged -Exe $UvExe -Arguments $notifyArgs
}

exit $exitCode

# SOKUHO 每日自動同步：啟動 Docker → Gmail 增量下載 → 匯入 PosInsight
# 由 Windows 工作排程器呼叫；日誌寫入 logs/sokuho_sync_YYYYMMDD.log

$ErrorActionPreference = "Stop"

$ProjectRoot = "E:\Git\SOKUHO"
$UvExe = "D:\Python\Scripts\uv.exe"
$DockerExe = "D:\Docker\resources\bin\docker.exe"
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

# 執行原生指令並逐行記錄輸出。docker / python 會把正常訊息寫到 stderr，
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
$env:Path = "D:\Python\Scripts;D:\Docker\resources\bin;" + $env:Path
# 強制公司 Gmail / Edge 設定檔，避免排程重授權時開到個人設定檔。
# 換機時請先查 Local State 對應 robert@auntstella.com.tw 的 Folder，再改 EDGE_PROFILE_DIR。
$env:GMAIL_LOGIN_HINT = if ($env:GMAIL_LOGIN_HINT) { $env:GMAIL_LOGIN_HINT } else { "robert@auntstella.com.tw" }
$env:EDGE_PROFILE_DIR = if ($env:EDGE_PROFILE_DIR) { $env:EDGE_PROFILE_DIR } else { "Profile 1" }
$env:NOTIFY_EMAIL = if ($env:NOTIFY_EMAIL) { $env:NOTIFY_EMAIL } else { "robert@auntstella.com.tw" }
# 讓 PowerShell 以 UTF-8 解碼子程序（python/docker）輸出，避免中文在 log 變亂碼。
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

Write-Log "=== SOKUHO scheduled sync started ==="
Write-Log ("Gmail hint={0}; Edge profile={1}" -f $env:GMAIL_LOGIN_HINT, $env:EDGE_PROFILE_DIR)

$exitCode = 0
$errorMsg = $null

try {
    if (-not (Test-Path $UvExe)) {
        throw "找不到 uv：$UvExe"
    }
    if (-not (Test-Path $DockerExe)) {
        throw "找不到 docker：$DockerExe"
    }

    # pos_insight_db 可能由另一個 compose 專案（E:\Git\POS_Insight）建立並與本專案共用；
    # 若容器已存在就直接啟動，避免從 SOKUHO 目錄跑 compose 因容器名稱衝突而失敗。
    Write-Log "確認 PosInsight 資料庫容器狀態"
    $containerStatus = & $DockerExe inspect --format "{{.State.Status}}" pos_insight_db 2>$null
    if ($containerStatus -eq "running") {
        Write-Log "pos_insight_db 已在執行中，略過啟動"
    }
    elseif ($containerStatus) {
        Write-Log "pos_insight_db 已存在（狀態：$containerStatus），啟動容器"
        $null = Invoke-Logged -Exe $DockerExe -Arguments @("start", "pos_insight_db")
    }
    else {
        Write-Log "pos_insight_db 不存在，以 docker compose 建立"
        $null = Invoke-Logged -Exe $DockerExe -Arguments @("compose", "up", "-d")
    }

    $maxWaitSec = 90
    $waited = 0
    $healthy = $false
    while ($waited -lt $maxWaitSec) {
        $status = & $DockerExe inspect --format "{{.State.Health.Status}}" pos_insight_db 2>$null
        if ($status -eq "healthy") {
            $healthy = $true
            break
        }
        if ($status -eq "running") {
            # 舊容器可能沒有 healthcheck 狀態，稍等後視為就緒
            Start-Sleep -Seconds 5
            $healthy = $true
            break
        }
        Start-Sleep -Seconds 3
        $waited += 3
    }

    if (-not $healthy) {
        throw "pos_insight_db 在 ${maxWaitSec}s 內未就緒，請手動執行 docker compose up -d"
    }
    Write-Log "PosInsight 資料庫已就緒"

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
    Write-Log "寄送同步結果通知信"
    $notifyArgs = @(
        "run", "python", "scripts/send_sync_notification.py",
        "--exit-code", $exitCode
    )
    if ($LogFile) { $notifyArgs += @("--log-file", $LogFile) }
    if ($errorMsg) { $notifyArgs += @("--error-message", $errorMsg) }
    $null = Invoke-Logged -Exe $UvExe -Arguments $notifyArgs
}

exit $exitCode

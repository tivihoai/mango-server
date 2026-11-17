# Cai dat Mango Server 1.2.1 len may Windows.
# Chay sau khi MangoServer-Setup.exe giai nen goi (hoac chay truc tiep):
#   powershell -ExecutionPolicy Bypass -File .\install_server.ps1 `
#     -MangoMCPDir "<thu muc goi MangoMCP Full da giai nen>" `
#     -ServerSrc "<thu muc code server 1.2.1>" `
#     -Port 8443 -DataDir "C:\MangoMCPServer\data"
# Mat khau quan tri truyen qua bien moi truong MANGO_ADMIN_PASSWORD (GUI
# truyen xuong, khong nam tren dong lenh). Neu khong co bien nay thi doc
# tu file tam %TEMP%\MangoServer-admin-password.txt (GUI che do silent
# ghi ra do) roi xoa ngay.
# Yeu cau quyen Admin.
#
# Cac buoc:
#  1. Chuan bi Python runtime: dung C:\MangoMCP\python neu co san; neu
#     chua co thi lay thu muc python tu goi MangoMCP Full ra
#     C:\MangoMCPServer\python (chi lay runtime, KHONG cai MangoMCP).
#  2. Dung Server cu (neu co) + xoa Task cu (de nang cap tai cho).
#     GIU NGUYEN thu muc data/ (registry/auth/audit/packages); neu data
#     da co thi backup 1 ban truoc khi thay code.
#  3. Copy code Server 1.2.1 vao C:\MangoMCPServer\server\.
#  4. Kiem tra/cai thu vien: websockets + mcp + uvicorn (Server can).
#  5. Ghi start_server.bat + server-config.json (port/data-dir da chon).
#  6. Dat mat khau quan tri + tao token Agent (qua set_admin.py; KHONG
#     in mat khau/token ra man hinh hay log).
#  7. Dang ky Scheduled Task MangoServer (SYSTEM, chay luc Windows khoi
#     dong, "Run whether user is logged on or not", quyen cao nhat) de
#     Server TU CHAY LAI sau khi may khoi dong ma KHONG can ai dang nhap.
#  8. Chay Server lan dau + kiem tra /health tra version 1.2.1.
#  9. Dang ky Mango Server trong Windows Uninstall.
#
# Bao mat: script nay KHONG in mat khau/secret/bearer/token ra man hinh
# hay log (chi in ten task, cong, thu muc). Neu buoc nao that bai, script
# dung ngay va in ro ly do.
param(
    [string]$MangoMCPDir = "",
    [string]$ServerSrc = "",
    [string]$InstallDir = "C:\MangoMCPServer",
    [int]$Port = 8443,
    [string]$DataDir = "",
    [string]$BindHost = "127.0.0.1"
)
$ErrorActionPreference = "Stop"

# Ghi log cai dat ra file de xem lai loi (cua so PowerShell tat la mat).
$installLog = Join-Path $env:TEMP "MangoServer-install.log"
try { Start-Transcript -Path $installLog -Force | Out-Null } catch { }

function Step($msg) { Write-Host ""; Write-Host "=== $msg ===" }
function Ok($msg) { Write-Host "[OK] $msg" }
function Warn($msg) { Write-Host "[CANH BAO] $msg" }
function Fail($msg) { throw $msg }

# ---------- 0. Kiem tra quyen Admin + tham so ----------
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Fail "Can quyen Admin de cai dat. Hay chay lai PowerShell / Setup.exe bang 'Run as administrator'."
}
if ([string]::IsNullOrWhiteSpace($ServerSrc)) { $ServerSrc = Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not (Test-Path "$ServerSrc\run_server.py")) {
    Fail "Khong thay code Server 1.2.1 tai $ServerSrc (thieu run_server.py)."
}
if (-not (Test-Path "$ServerSrc\mangoserver\app.py")) {
    Fail "Khong thay code Server 1.2.1 tai $ServerSrc (thieu mangoserver\app.py)."
}
if (-not (Test-Path "$ServerSrc\set_admin.py")) {
    Fail "Khong thay $ServerSrc\set_admin.py (can de dat mat khau quan tri khong tuong tac)."
}
if ($Port -lt 1 -or $Port -gt 65535) { Fail "Cong khong hop le: $Port (phai 1..65535)." }
if ([string]::IsNullOrWhiteSpace($DataDir)) { $DataDir = "$InstallDir\data" }
$serverDir = "$InstallDir\server"
$tokenOutFile = Join-Path $env:TEMP "MangoServer-agent-token.txt"
Write-Host "Mango Server 1.2.1 - cai dat vao $InstallDir (cong $Port, data $DataDir, host $BindHost)"

# Mat khau quan tri: uu tien bien moi truong (GUI truyen xuong); neu khong
# co thi doc file tam cua che do silent roi xoa ngay. KHONG in ra log.
$adminPassword = $env:MANGO_ADMIN_PASSWORD
if ([string]::IsNullOrWhiteSpace($adminPassword)) {
    $pwFile = Join-Path $env:TEMP "MangoServer-admin-password.txt"
    if (Test-Path $pwFile) {
        try { $adminPassword = (Get-Content $pwFile -Raw -Encoding UTF8).Trim() } catch { $adminPassword = "" }
        try { Remove-Item $pwFile -Force -ErrorAction SilentlyContinue } catch { }
        if ($adminPassword) { Write-Host "Da doc mat khau quan tri tu file tam (da xoa file)." }
    }
}
if ([string]::IsNullOrWhiteSpace($adminPassword)) {
    Fail "Thieu mat khau quan tri: GUI phai truyen MANGO_ADMIN_PASSWORD hoac ghi file tam truoc khi goi script nay."
}
if ($adminPassword.Length -lt 4) { Fail "Mat khau quan tri phai co it nhat 4 ky tu." }

$pyExe = ""
$pywExe = ""

# ---------- 1. Chuan bi Python runtime ----------
Step "1/9 - Chuan bi Python runtime"
$mangoPy = "C:\MangoMCP\python\python.exe"
$localPy = "$InstallDir\python\python.exe"
if (Test-Path $mangoPy) {
    $pyExe = $mangoPy
    Ok "Dung Python co san: $pyExe"
} elseif (Test-Path $localPy) {
    $pyExe = $localPy
    Ok "Dung Python da cai truoc: $pyExe"
} else {
    $pySrc = $null
    foreach ($candidate in @("$MangoMCPDir\python", "$MangoMCPDir\MangoMCP\python")) {
        if ($candidate -and (Test-Path "$candidate\python.exe")) { $pySrc = $candidate; break }
    }
    if (-not $pySrc) {
        Fail "Khong tim thay Python runtime: may chua co C:\MangoMCP\python va goi cai khong co thu muc python. Hay cai MangoMCP 0.14.2 truoc, hoac build lai Setup.exe co goi MangoMCP Full."
    }
    Write-Host "Chua co Python - dang copy runtime tu goi Full ($pySrc)..."
    New-Item -ItemType Directory -Force -Path "$InstallDir\python" | Out-Null
    # robocopy tra 1 khi copy thanh cong - khong dung $LASTEXITCODE de ket luan.
    robocopy "$pySrc" "$InstallDir\python" /E /NFL /NDL /NJH /NJS /R:2 /W:2 | Out-Null
    if (-not (Test-Path $localPy)) {
        Fail "Copy Python runtime that bai: khong thay $localPy sau khi copy."
    }
    $pyExe = $localPy
    Ok "Da copy Python runtime vao $InstallDir\python"
}
try {
    & $pyExe --version 2>$null | Out-Null
    Ok "Python chay duoc: $pyExe"
} catch {
    Fail "Python tai $pyExe khong chay duoc: $($_.Exception.Message)"
}
$pywExe = $pyExe -replace "python\.exe$", "pythonw.exe"
if (-not (Test-Path $pywExe)) { $pywExe = $pyExe }

# ---------- 2. Dung Server cu + xoa Task cu (nang cap tai cho) ----------
Step "2/9 - Dung Server cu (neu co) de nang cap"
$killed = 0
try {
    $procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction SilentlyContinue
    foreach ($p in $procs) {
        $cmd = [string]$p.CommandLine
        if ($cmd -and $cmd -match "run_server\.py") {
            try {
                Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
                $killed++
                Write-Host "Da tat $($p.Name) (PID $($p.ProcessId)) dang chay Server."
            } catch { }
        }
    }
} catch { }
try {
    $t = Get-ScheduledTask -TaskName "MangoServer" -ErrorAction SilentlyContinue
    if ($t) {
        try { Stop-ScheduledTask -TaskName "MangoServer" -ErrorAction SilentlyContinue | Out-Null } catch { }
        Start-Sleep -Seconds 2
        Unregister-ScheduledTask -TaskName "MangoServer" -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
        Ok "Da xoa Task MangoServer cu (se dang ky lai o buoc 7)."
    }
} catch { }
if ($killed -eq 0) { Ok "Khong thay Server cu dang chay." } else { Ok "Da tat $killed process Server cu." }
Start-Sleep -Seconds 2
# Backup data cu (neu co) truoc khi thay code - chi backup, KHONG xoa.
if (Test-Path $DataDir) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backupDir = "$InstallDir\data-backup-$stamp"
    try {
        Copy-Item -Recurse $DataDir $backupDir -ErrorAction Stop
        Ok "Da backup data cu vao $backupDir (giu nguyen $DataDir)."
    } catch {
        Warn "Khong backup duoc data cu ($($_.Exception.Message)) - van tiep tuc, data cu khong bi xoa."
    }
} else {
    New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
    Ok "Da tao thu muc data moi: $DataDir"
}

# ---------- 3. Copy code Server 1.2.1 ----------
Step "3/9 - Copy code Server 1.2.1 vao $serverDir"
New-Item -ItemType Directory -Force -Path $serverDir | Out-Null
robocopy "$ServerSrc" "$serverDir" /E /XD __pycache__ /NFL /NDL /NJH /NJS /R:2 /W:2 | Out-Null
if (-not (Test-Path "$serverDir\run_server.py")) { Fail "Copy Server that bai: khong thay $serverDir\run_server.py sau khi copy." }
if (-not (Test-Path "$serverDir\mangoserver\app.py")) { Fail "Copy Server that bai: khong thay $serverDir\mangoserver\app.py sau khi copy." }
if (-not (Test-Path "$serverDir\mangoserver\dashboard.py")) { Fail "Copy Server that bai: khong thay $serverDir\mangoserver\dashboard.py sau khi copy." }
if (-not (Test-Path "$serverDir\set_admin.py")) { Fail "Copy Server that bai: khong thay $serverDir\set_admin.py sau khi copy." }
Ok "Da copy Server 1.2.1 (run_server.py + mangoserver/ + set_admin.py)."

# ---------- 4. Kiem tra/cai thu vien ----------
Step "4/9 - Kiem tra thu vien (websockets + mcp + uvicorn)"
# $ErrorActionPreference = "Stop" bien stderr cua lenh python thanh loi ket
# thuc. Tam ha xuong "Continue" trong buoc nay de kiem tra $LASTEXITCODE.
$oldEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    $missing = @()
    foreach ($mod in @("websockets", "mcp", "uvicorn")) {
        & $pyExe -c "import $mod" 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { $missing += $mod }
    }
    if ($missing.Count -gt 0) {
        Write-Host "Thieu thu vien: $($missing -join ', ') - dang cai bang pip..."
        $specs = @()
        if ($missing -contains "websockets") { $specs += "websockets>=12,<18" }
        if ($missing -contains "mcp") { $specs += "mcp>=1.8,<2" }
        if ($missing -contains "uvicorn") { $specs += "uvicorn>=0.30" }
        & $pyExe -m pip install --no-warn-script-location $specs
        if ($LASTEXITCODE -ne 0) { Fail "Cai thu vien that bai ($($missing -join ', ')). Kiem tra mang tren may nay roi chay lai." }
        Ok "Da cai thu vien: $($missing -join ', ')."
    } else {
        Ok "Da co du websockets + mcp + uvicorn."
    }
    & $pyExe -c "import websockets; print('websockets', websockets.__version__)" 2>$null | Out-Null
} finally {
    $ErrorActionPreference = $oldEAP
}

# ---------- 5. Ghi start_server.bat + server-config.json ----------
Step "5/9 - Ghi start_server.bat + server-config.json"
$batPath = "$InstallDir\start_server.bat"
$batLines = @(
    "@echo off",
    "cd /d $serverDir",
    "`"$pyExe`" run_server.py start --data-dir `"$DataDir`" --host $BindHost --port $Port >> `"$InstallDir\server.log`" 2>&1"
)
[System.IO.File]::WriteAllLines($batPath, $batLines, (New-Object System.Text.UTF8Encoding $false))
Ok "Da ghi $batPath"
$cfgObj = New-Object PSObject -Property @{
    version = "1.2.1"
    host = $BindHost
    port = $Port
    data_dir = $DataDir
    install_dir = $InstallDir
    python = $pyExe
}
[System.IO.File]::WriteAllText("$InstallDir\server-config.json", ($cfgObj | ConvertTo-Json -Depth 4), (New-Object System.Text.UTF8Encoding $false))
Ok "Da ghi $InstallDir\server-config.json (cong $Port, data $DataDir)"

# ---------- 6. Dat mat khau quan tri + tao token Agent ----------
Step "6/9 - Dat mat khau quan tri + tao token Agent"
# set_admin.py chi in trang thai, KHONG in mat khau/token. Token tho (neu
# tao moi) chi ghi vao file tam $tokenOutFile de GUI hien 1 lan roi xoa.
if (Test-Path $tokenOutFile) { try { Remove-Item $tokenOutFile -Force -ErrorAction SilentlyContinue } catch { } }
$env:MANGO_ADMIN_PASSWORD = $adminPassword
$adminPassword = $null
$oldEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    # --force: cai dat la thao tac dat mat khau TUONG MINH (nguoi cai vua nhap
    # mat khau o GUI / /ADMINPASSWORD) nen PHAI ghi de mat khau cu. Khong co
    # --force, set_admin.py giu mat khau cu khi data/auth.json da ton tai
    # (cai de len Server cu, hoac cai lai sau khi go ma giu data/) roi bao
    # thanh cong gia — mat khau moi nhap khong bao gio duoc luu (loi 1.2.0,
    # 17/11/2026). Chi mat khau bi ghi de; token Agent + may da enroll giu nguyen.
    & $pyExe "$serverDir\set_admin.py" --data-dir "$DataDir" --token-out "$tokenOutFile" --force
    if ($LASTEXITCODE -ne 0) { Fail "Dat mat khau quan tri that bai (xem dong tren). Kiem tra lai $DataDir\auth.json." }
} finally {
    $ErrorActionPreference = $oldEAP
    $env:MANGO_ADMIN_PASSWORD = $null
}
if (Test-Path $tokenOutFile) {
    Ok "Da tao token Agent moi (file tam $tokenOutFile - GUI se hien 1 lan roi xoa)."
} else {
    Ok "Mat khau quan tri da xong; token Agent da co tu truoc (khong tao moi)."
}

# ---------- 7. Dang ky Scheduled Task MangoServer (SYSTEM, luc khoi dong) ----------
Step "7/9 - Dang ky Scheduled Task MangoServer (SYSTEM, khoi dong)"
# Task chay luc Windows khoi dong bang SYSTEM ("Run whether user is logged
# on or not", quyen cao nhat) nen Server TU CHAY LAI sau khi may khoi dong
# ma KHONG can ai dang nhap. Khong dung shortcut Startup (ban sua mot nua).
$action = New-ScheduledTaskAction -Execute $batPath -WorkingDirectory $serverDir
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Days 0) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "MangoServer" -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null
$taskCheck = Get-ScheduledTask -TaskName "MangoServer" -ErrorAction Stop
Ok "Da dang ky Task MangoServer (trigger AtStartup, user SYSTEM, RunLevel Highest; tu chay lai toi da 3 lan neu crash)."

# ---------- 8. Chay Server lan dau + kiem tra /health ----------
Step "8/9 - Chay Server lan dau (Task MangoServer)"
Write-Host "Dang chay Server bang Task MangoServer (log vao $InstallDir\server.log)..."
Start-ScheduledTask -TaskName "MangoServer"
$healthOk = $false
$healthUrl = "http://${BindHost}:${Port}/health"
for ($i = 1; $i -le 10; $i++) {
    Start-Sleep -Seconds 3
    try {
        $resp = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
        $body = $resp.Content
        Write-Host "  /health lan $i : $body"
        if ($body -match '"version"\s*:\s*"1\.2\.1"') { $healthOk = $true; break }
        if ($body -match '"status"\s*:\s*"ok"') { $healthOk = $true; break }
    } catch {
        Write-Host "  /health lan $i : chua tra loi ($($_.Exception.Message))"
    }
}
if (-not $healthOk) {
    Warn "Server chua tra /health sau ~30 giay - co the khoi dong cham. Hay xem $InstallDir\server.log; neu khong co log, chay Task MangoServer bang tay de xem loi."
} else {
    Ok "Server 1.2.1 dang chay: $healthUrl"
}

# ---------- 9. Dang ky Uninstall (hien trong Windows Uninstall) ----------
Step "9/9 - Dang ky Mango Server trong Windows Uninstall"
$uninstKey = "MangoServer"
$uninstExe = "powershell -NoProfile -ExecutionPolicy Bypass -File `"$serverDir\uninstall_server.ps1`""
$regOK = $false
foreach ($base in @("HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                    "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")) {
    try {
        $key = "$base\$uninstKey"
        New-Item -Path $key -Force | Out-Null
        Set-ItemProperty -Path $key -Name "DisplayName" -Value "Mango Server" -Force
        Set-ItemProperty -Path $key -Name "DisplayVersion" -Value "1.2.1" -Force
        Set-ItemProperty -Path $key -Name "Publisher" -Value "Mango" -Force
        Set-ItemProperty -Path $key -Name "UninstallString" -Value $uninstExe -Force
        Set-ItemProperty -Path $key -Name "InstallLocation" -Value $InstallDir -Force
        Set-ItemProperty -Path $key -Name "NoModify" -Value 1 -Type DWord -Force
        Set-ItemProperty -Path $key -Name "NoRepair" -Value 1 -Type DWord -Force
        Ok "Da dang ky Uninstall tai $key (ban 1.2.1)."
        $regOK = $true
        break
    } catch {
        Warn "Khong ghi duoc $base : $($_.Exception.Message)"
    }
}
if (-not $regOK) { Warn "Khong dang ky duoc Uninstall - app se khong hien trong Windows Uninstall." }

Write-Host ""
Write-Host "=== XONG! Mango Server 1.2.1 da cai tren may nay ==="
Write-Host "Dashboard     : http://${BindHost}:${Port}/dashboard"
Write-Host "Health        : $healthUrl"
Write-Host "Thu muc cai   : $InstallDir"
Write-Host "Code Server   : $serverDir"
Write-Host "Thu muc data  : $DataDir"
Write-Host "Python        : $pyExe"
Write-Host "Task          : MangoServer (SYSTEM, chay luc Windows khoi dong - tu chay lai sau khi khoi dong may, khong can dang nhap)"
Write-Host "Nhat ky       : $InstallDir\server.log"
Write-Host "Buoc tiep theo: mo dashboard, dang nhap bang mat khau quan tri, vao tab Ma dang ky de lay ma cho may con."
Write-Host "De may con o xa noi duoc: mo Cloudflare Tunnel tro ve http://${BindHost}:${Port} (lay hostname https) hoac mo cong $Port tren router/tuong lua."

# --- Ket thuc: bao dam ma thoat 0 khi cai xong (robocopy tra 1 khi copy
# thanh cong nen $LASTEXITCODE co the con 1; installer C# doc ma thoat
# powershell nen phai reset ve 0 neu khong se bao loi gia). ---
$LASTEXITCODE = 0
exit 0

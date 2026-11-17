# Cai dat Mango Client 2.1.9 len may con Windows.
# Chay sau khi MangoClient-Setup.exe giai nen goi (hoac chay truc tiep):
#   powershell -ExecutionPolicy Bypass -File .\install_client.ps1 `
#     -MangoMCPDir "<thu muc goi MangoMCP Full da giai nen>" `
#     -ClientSrc "<thu muc code client 2.1.1>" `
#     -GuiUser "<tai khoan dung de dieu khien giao dien>" `
#     -GuiPassword "<mat khau cua tai khoan do>"
# Yeu cau quyen Admin.
#
# 2.1.2 (16/11/2026): doi ten mien Server (moi); updater tu chay lai qua
#  Task MangoClient (2.x) truoc, roi moi MangoServerClient (1.x); tu dong
#  cap nhat + tu khoi dong lai client sau khi ap dung goi, khong hoi
#  nguoi dung.
# 2.1.8 (17/11/2026): them tham so -ServerHost/-ServerPort (ban CustomHost)
#  de cai vao Server khac; ban chuan truyen -ServerHost mac dinh tu C#.
# 2.1.9: bo host mac dinh trong script — khong truyen -ServerHost thi giu
#  host trong server-client.json cu (neu co), neu khong co thi BAO LOI RO
#  RANG, khong fallback ve host mac dinh nao nua.
# 2.1.1 khac 2.1.0 (3 sua, 16/11/2026):
#  - (BUG 1) Ten tai khoan khong con bi luu kem dau nhay: C# truyen bang dau "
#    (command-line Windows chi hieu dau "), .ps1 nay cat them dau ' / " thua.
#  - (BUG 3) Copy agent-desktop.exe + MangoOverlay.exe tu goi MangoMCP Full
#    vao C:\MangoClient\bin\ (client tu dung du, khong phu thuoc C:\MangoMCP)
#    va ghi desktop_binary tro toi do trong server-client.json.
#  - Client chay bang SYSTEM luc Windows khoi dong (Task "At startup",
#    SYSTEM, "Run whether user is logged on or not") — dieu khien duoc
#    bang lenh cmd/powershell ngay ca khi chua ai dang nhap. KHONG dung
#    auto-logon (Quan tri vien khong muon tu dang nhap).
#  - Chi khi can dieu khien giao dien/manhinh/chuot thi dung tai khoan
#    /mat khau DA LUU (tham so -GuiUser/-GuiPassword, luu vao `users`
#    trong server-client.json) de mo GUI agent vao session nguoi dung.
#  - Client chay AN bang pythonw.exe (khong cua so cmd nao) — khong con
#    run_client_log.bat, khong the tat nham cua so client nhu 2.0.
#  - Them tool config_set_user_password (doi mat khau user da luu tu xa).
#
# Cac buoc:
#  1. Chuan bi Python runtime: dung C:\MangoMCP\python neu co san; neu chua
#     co thi lay thu muc python tu goi MangoMCP Full ra C:\MangoClient\python
#     (chi lay runtime, KHONG cai MangoMCP).
#  2. Dung client cu (2.0.0) + xoa Task cu (de nang cap tai cho, khong khoa file).
#  3. Copy code Client 2.1.1 vao C:\MangoClient\ (ghi de code cu; GIU LAI
#     server-client.json neu da co).
#  3b. Copy agent-desktop.exe + MangoOverlay.exe vao C:\MangoClient\bin\.
#  4. Kiem tra thu vien websockets (client can de noi WebSocket ra Server).
#  4b. Sua SSL: dat SSL_CERT_FILE tro toi cacert.pem cua certifi.
#  5. Tao/cap nhat C:\MangoClient\server-client.json (server_host /
#     server_port / use_tls / machine_name tu dong + tai khoan da luu +
#     desktop_binary tro toi C:\MangoClient\bin\agent-desktop.exe).
#     KHONG ghi machine_id/secret - client 2.1.1 tu enroll bang URL se ghi.
#  6. Dang ky Scheduled Task MangoClient (chay luc Windows khoi dong bang
#     SYSTEM, an, pythonw.exe, ghi client.log).
#  7. Chay client lan dau (client tu enroll bang URL, hien pending tren
#     dashboard).
#  8. Dang ky Mango Client trong Windows Uninstall.
#
# Bao mat: script nay KHONG in mat khau/secret/bearer/token ra man hinh
# hay log (chi in ten tai khoan). Neu buoc nao that bai, script dung ngay
# va in ro ly do.
param(
    [string]$MangoMCPDir = "",
    [string]$ClientSrc = "",
    [string]$InstallDir = "C:\MangoClient",
    [string]$GuiUser = "",
    [string]$GuiPassword = "",
    [string]$ServerHost = "",
    [int]$ServerPort = 0
)
$ErrorActionPreference = "Stop"

# Ghi log cai dat ra file de xem lai loi (cua so PowerShell tat la mat).
# Log o %TEMP%\MangoClient-install.log - neu cai loi, mo file nay xem.
$installLog = Join-Path $env:TEMP "MangoClient-install.log"
try { Start-Transcript -Path $installLog -Force | Out-Null } catch { }

function Step($msg) { Write-Host ""; Write-Host "=== $msg ===" }
function Ok($msg) { Write-Host "[OK] $msg" }
function Warn($msg) { Write-Host "[CANH BAO] $msg" }
function Fail($msg) { throw $msg }

# ---------- 0. Kiem tra quyen Admin + tham so ----------
# 2.1.1 — Cat dau nhay thua o ten tai khoan (LOI 2.1.0): PsQuote ben C#
# dung dau ' nhung command-line Windows chi hieu dau " lam gioi han chuoi,
# nen gia tri truyen sang la 'admin' (kem dau nhay) va luu luon vao config
# -> LogonUser 1326 + config_set_user_password USER_NOT_FOUND. C# 2.1.1 da
# doi sang dau " nhung van cat phong o day de phong gia tri cu con sot.
if ($GuiUser) {
    $GuiUser = $GuiUser.Trim()
    while ($GuiUser.Length -ge 2 -and (($GuiUser.StartsWith("'") -and $GuiUser.EndsWith("'")) -or ($GuiUser.StartsWith('"') -and $GuiUser.EndsWith('"')))) {
        $GuiUser = $GuiUser.Substring(1, $GuiUser.Length - 2).Trim()
    }
    if ($GuiUser -and ($GuiUser.Contains("'") -or $GuiUser.Contains('"'))) { Warn "Ten tai khoan '$GuiUser' van con dau nhay — hay kiem tra lai (ten Windows khong nen co dau nhay)." }
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Fail "Can quyen Admin de cai dat. Hay chay lai PowerShell / Setup.exe bang 'Run as administrator'."
}
if ([string]::IsNullOrWhiteSpace($ClientSrc)) { $ClientSrc = Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not (Test-Path "$ClientSrc\run_client.py")) {
    Fail "Khong thay code client 2.1.1 tai $ClientSrc (thieu run_client.py)."
}
if (-not (Test-Path "$ClientSrc\gui_agent.py")) {
    Fail "Khong thay code client 2.1.1 tai $ClientSrc (thieu gui_agent.py)."
}

# Server host: uu tien -ServerHost do C# truyen (ban chuan truyen host mac
# dinh, ban CustomHost truyen host nguoi cai nhap); neu khong truyen thi
# giu host trong server-client.json cu (cai de / cai lai bang tay); neu
# ca hai deu khong co thi BAO LOI RO RANG o duoi — khong fallback ve
# host mac dinh nao nua (2.1.9).
# 2.1.8 (CustomHost): neu truyen -ServerHost thi dung host/cong do
# (vd -ServerHost "192.168.1.10" -ServerPort 8443).
$ServerUrl = ""
if (-not [string]::IsNullOrWhiteSpace($ServerHost)) {
    $ServerHost = $ServerHost.Trim() -replace '^https?://', '' -replace '/.*$', ''
    if ($ServerHost -match '\s') { Fail "Dia chi Server khong hop le (co khoang trang): $ServerHost" }
    if ($ServerPort -le 0) { $ServerPort = 8443 }
    if ($ServerPort -lt 1 -or $ServerPort -gt 65535) { Fail "Cong Server khong hop le (phai la so 1..65535): $ServerPort" }
    $ServerUrl = "https://${ServerHost}:$ServerPort"
    Write-Host "Dung Server do tham so -ServerHost chi dinh: $ServerUrl"
}
else {
    # Khong truyen -ServerHost: giu host trong server-client.json cu
    # (neu co) — de cai lai bang tay tren may da cai truoc van chay duoc.
    $oldCfgPath = "$InstallDir\server-client.json"
    if (Test-Path $oldCfgPath) {
        try {
            $oldCfg = Get-Content $oldCfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($oldCfg -and $oldCfg.server_host -and ([string]$oldCfg.server_host).Trim()) {
                $oh = ([string]$oldCfg.server_host).Trim()
                $op = 8443
                if ($oldCfg.server_port) { $op = [int]$oldCfg.server_port }
                if ($op -le 0) { $op = 8443 }
                $otls = $true
                if ($null -ne $oldCfg.use_tls) { $otls = [bool]$oldCfg.use_tls }
                $oscheme = if ($otls) { "https" } else { "http" }
                $ServerUrl = "${oscheme}://${oh}:$op"
                Write-Host "Khong truyen -ServerHost: giu Server cu trong server-client.json ($ServerUrl)."
            }
        } catch { }
    }
    if ([string]::IsNullOrWhiteSpace($ServerUrl)) {
        Fail "Chua chi dinh Server host. Hay chay lai voi -ServerHost <host> -ServerPort <cong> (vd -ServerHost may-chu.example.com -ServerPort 8443), hoac cai bang MangoClient-Setup.exe."
    }
}
$MachineName = $env:COMPUTERNAME
try { $uri = [System.Uri]$ServerUrl.Trim() } catch { Fail "Dia chi Server khong hop le: $ServerUrl" }
$serverHost = $uri.Host
$useTls = ($uri.Scheme -eq "https")
if ($uri.IsDefaultPort) { $serverPort = if ($useTls) { 8443 } else { 80 } } else { $serverPort = $uri.Port }
Write-Host "Mango Client 2.1.9 - cai dat cho may '$MachineName', Server $serverHost`:$serverPort (TLS: $useTls)"
if ($GuiUser) { Write-Host "Tai khoan dieu khien giao dien se luu: $GuiUser (mat khau KHONG hien o day)" }

$clientJsonPath = "$InstallDir\server-client.json"
$pyExe = ""
$pywExe = ""

# ---------- 1. Chuan bi Python runtime ----------
Step "1/8 - Chuan bi Python runtime"
# Uu tien Python da co san cua MangoMCP (du package). Neu chua co thi lay
# thu muc python tu goi MangoMCP Full ra C:\MangoClient\python (chi lay
# runtime, KHONG cai MangoMCP).
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
# pythonw.exe (khong cua so) de chay client an. Neu khong co thi dung
# python.exe (se hien cua so console — canh bao, khong dung cai).
$pywExe = $pyExe -replace "python\.exe$", "pythonw.exe"
if (Test-Path $pywExe) {
    Ok "Dung pythonw.exe (chay an, khong cua so): $pywExe"
} else {
    Warn "Khong thay pythonw.exe - dung python.exe (client se hien cua so console)."
    $pywExe = $pyExe
}

# ---------- 2. Dung client cu + xoa Task cu (nang cap tai cho) ----------
Step "2/8 - Dung client cu (neu co) de nang cap"
# Tat client 2.0.0 dang chay (python.exe qua run_client_log.bat) va GUI
# agent 2.1.1 (pythonw.exe) neu co, de khong khoa file khi copy code moi.
$killed = 0
try {
    $procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction SilentlyContinue
    foreach ($p in $procs) {
        $cmd = [string]$p.CommandLine
        if ($cmd -and ($cmd -match "run_client\.py" -or $cmd -match "gui_agent\.py")) {
            try {
                Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
                $killed++
                Write-Host "Da tat $($p.Name) (PID $($p.ProcessId)) dang chay client."
            } catch { }
        }
    }
} catch { }
try {
    $cmds = Get-CimInstance Win32_Process -Filter "Name = 'cmd.exe'" -ErrorAction SilentlyContinue
    foreach ($p in $cmds) {
        $cmd = [string]$p.CommandLine
        if ($cmd -and $cmd -match "run_client_log\.bat") {
            try { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue; $killed++ } catch { }
        }
    }
} catch { }
try {
    $t = Get-ScheduledTask -TaskName "MangoClient" -ErrorAction SilentlyContinue
    if ($t) {
        try { Stop-ScheduledTask -TaskName "MangoClient" -ErrorAction SilentlyContinue | Out-Null } catch { }
        Start-Sleep -Seconds 2
        Unregister-ScheduledTask -TaskName "MangoClient" -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
        Ok "Da xoa Task MangoClient cu (se dang ky lai o buoc 6)."
    }
} catch { }
if ($killed -eq 0) { Ok "Khong thay client cu dang chay." } else { Ok "Da tat $killed process client cu." }
Start-Sleep -Seconds 2
# run_client_log.bat da bo o 2.1.1 (client chay truc tiep bang pythonw.exe).
if (Test-Path "$InstallDir\run_client_log.bat") {
    try { Remove-Item "$InstallDir\run_client_log.bat" -Force -ErrorAction SilentlyContinue; Ok "Da xoa run_client_log.bat cu (2.1.1 khong dung file nay)." } catch { }
}

# ---------- 3. Copy code Client 2.1.1 ----------
Step "3/8 - Copy code Client 2.1.1 vao $InstallDir"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
# /E: copy ca thu muc con; /XD __pycache__ python: bo file bien dich tam +
# thu muc python (da xu ly o buoc 1); /XF server-client.json: KHONG ghi de
# file cau hinh may (neu co trong goi).
robocopy "$ClientSrc" "$InstallDir" /E /XD __pycache__ python /XF server-client.json /NFL /NDL /NJH /NJS /R:2 /W:2 | Out-Null
if (-not (Test-Path "$InstallDir\run_client.py")) { Fail "Copy client that bai: khong thay $InstallDir\run_client.py sau khi copy." }
if (-not (Test-Path "$InstallDir\gui_agent.py")) { Fail "Copy client that bai: khong thay $InstallDir\gui_agent.py sau khi copy." }
if (-not (Test-Path "$InstallDir\mangoclient\agent.py")) { Fail "Copy client that bai: khong thay $InstallDir\mangoclient\agent.py sau khi copy." }
if (-not (Test-Path "$InstallDir\mangoengine\core.py")) { Fail "Copy client that bai: khong thay $InstallDir\mangoengine\core.py sau khi copy." }
if (-not (Test-Path "$InstallDir\mangoengine\direct_engine.py")) { Fail "Copy client that bai: khong thay $InstallDir\mangoengine\direct_engine.py sau khi copy." }
if (-not (Test-Path "$InstallDir\mangoengine\session.py")) { Fail "Copy client that bai: khong thay $InstallDir\mangoengine\session.py sau khi copy." }
if (-not (Test-Path "$InstallDir\mangoengine\gui.py")) { Fail "Copy client that bai: khong thay $InstallDir\mangoengine\gui.py sau khi copy." }
if (-not (Test-Path "$InstallDir\mangoengine\ipc.py")) { Fail "Copy client that bai: khong thay $InstallDir\mangoengine\ipc.py sau khi copy." }
Ok "Da copy Client 2.1.1 (run_client.py + gui_agent.py + mangoclient/ + mangoengine/)."

# ---------- 3b. Copy agent-desktop.exe + MangoOverlay.exe (2.1.1) ----------
Step "3b/8 - Copy agent-desktop.exe + MangoOverlay.exe (de tool desktop_* chay duoc)"
# 2.1.1: ban 2.1.0 chi lay thu muc python tu goi MangoMCP Full, khong lay
# thu muc bin -> tren may moi (khong co C:\MangoMCP) desktop_* bao
# DESKTOP_UNAVAILABLE vi C:\MangoMCP\bin\agent-desktop.exe khong ton tai.
# Lay tu goi Full ($MangoMCPDir, da giai nen san trong goi cai):
#   MangoMCP\bin\agent-desktop.exe (3.827.200 byte) + app\MangoOverlay.exe.
# Dat vao $InstallDir\bin de client tu dung du, khong phu thuoc C:\MangoMCP.
# Fallback: C:\MangoMCP neu may da co MangoMCP; roi goi client
# ($ClientSrc\bin) neu co bundle san.
$binDir = "$InstallDir\bin"
New-Item -ItemType Directory -Force -Path $binDir | Out-Null
$deskSrc = $null
foreach ($cand in @("$MangoMCPDir\bin\agent-desktop.exe", "$MangoMCPDir\MangoMCP\bin\agent-desktop.exe", "C:\MangoMCP\bin\agent-desktop.exe", "$ClientSrc\bin\agent-desktop.exe")) {
    if ($cand -and (Test-Path $cand)) { $deskSrc = $cand; break }
}
if ($deskSrc) {
    # 2.1.8: BO QUA neu nguon == dich (cai de len ban cu da co bin):
    # Copy-Item tu de len chinh no se loi TerminatingError duoi
    # $ErrorActionPreference = "Stop" -> exit 1 o buoc 3b/8 (may test, 2.1.5).
    $deskDst = "$binDir\agent-desktop.exe"
    $deskSrcFull = [System.IO.Path]::GetFullPath($deskSrc)
    $deskDstFull = [System.IO.Path]::GetFullPath($deskDst)
    if ($deskSrcFull -ieq $deskDstFull) {
        Ok "agent-desktop.exe da co san tai $deskDst (nguon trung dich) - bo qua buoc copy."
    } else {
        Copy-Item $deskSrc $deskDst -Force
        if (Test-Path $deskDst) { Ok "Da copy agent-desktop.exe tu $deskSrc (dang $([math]::Round((Get-Item $deskDst).Length / 1KB)) KB)" } else { Fail "Copy agent-desktop.exe that bai: khong thay $deskDst sau khi copy." }
    }
} else {
    Fail "Khong tim thay agent-desktop.exe (goi Full / C:\MangoMCP / goi client). Tool desktop_* se khong chay duoc. Hay copy C:\MangoMCP\bin\agent-desktop.exe vao $binDir roi chay lai installer."
}
$ovSrc = $null
foreach ($cand in @("$MangoMCPDir\app\MangoOverlay.exe", "$MangoMCPDir\MangoMCP\app\MangoOverlay.exe", "C:\MangoMCP\app\MangoOverlay.exe", "$ClientSrc\bin\MangoOverlay.exe", "$ClientSrc\MangoOverlay.exe")) {
    if ($cand -and (Test-Path $cand)) { $ovSrc = $cand; break }
}
if ($ovSrc) {
    # 2.1.8: cung mau nhu agent-desktop.exe o tren - bo qua neu trung dich.
    $ovDst = "$binDir\MangoOverlay.exe"
    $ovSrcFull = [System.IO.Path]::GetFullPath($ovSrc)
    $ovDstFull = [System.IO.Path]::GetFullPath($ovDst)
    if ($ovSrcFull -ieq $ovDstFull) {
        Ok "MangoOverlay.exe da co san tai $ovDst (nguon trung dich) - bo qua buoc copy."
    } else {
        Copy-Item $ovSrc $ovDst -Force
        if (Test-Path $ovDst) { Ok "Da copy MangoOverlay.exe tu $ovSrc" } else { Warn "Copy MangoOverlay.exe that bai - overlay se khong chay (khong anh huong dieu khien co ban)." }
    }
} else {
    Warn "Khong tim thay MangoOverlay.exe (goi Full / C:\MangoMCP / goi client) - overlay se khong chay (khong anh huong dieu khien co ban)."
}

# ---------- 4. Kiem tra thu vien websockets ----------
Step "4/8 - Kiem tra thu vien websockets (client can de noi Server)"
# $ErrorActionPreference = "Stop" o dau file bien stderr cua lenh goc
# (python in Traceback khi thieu websockets) thanh loi ket thuc. Tam ha
# xuong "Continue" trong buoc nay de kiem tra bang $LASTEXITCODE.
$oldEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    & $pyExe -c "import websockets" 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Chua co websockets - dang cai websockets 17.4..."
        & $pyExe -m pip install --no-warn-script-location "websockets==17.4"
        if ($LASTEXITCODE -ne 0) { Fail "Cai websockets that bai. Kiem tra mang tren may con roi chay lai." }
        Ok "Da cai websockets 17.4."
    } else {
        Ok "Da co websockets."
    }
} finally {
    $ErrorActionPreference = $oldEAP
}

# ---------- 4b. Sua SSL: dat SSL_CERT_FILE tro toi cacert.pem cua certifi ----------
Step "4b/8 - Sua chung chi SSL (de client noi duoc Server)"
# Bai hoc tren may test (16/11 ~00:00): Python portable tren may moi co kho chung chi
# mac dinh thieu/khong dung duoc -> enroll loi CERTIFICATE_VERIFY_FAILED
# (Server dung chung chi Let's Encrypt moi). `certifi` co san nhung urllib
# khong tu dung no. Dat SSL_CERT_FILE tro toi file cacert.pem cua certifi
# (goi nay luon co trong Python) de urllib + websockets dung.
$script:sslCertFile = ""
$oldEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    & $pyExe -m pip install --no-warn-script-location "certifi" 2>$null | Out-Null
    $cacert = & $pyExe -c "import certifi; print(certifi.where())" 2>$null
    $cacert = ($cacert | Select-Object -First 1)
    if ($cacert) { $cacert = $cacert.Trim() }
    if ($cacert -and (Test-Path $cacert)) {
        $script:sslCertFile = $cacert
        [Environment]::SetEnvironmentVariable("SSL_CERT_FILE", $cacert, "Machine")
        $env:SSL_CERT_FILE = $cacert
        Ok "Da dat SSL_CERT_FILE = $cacert"
    } else {
        Warn "Khong tim thay cacert.pem cua certifi - client co the loi SSL khi enroll. Hay cai certifi bang tay roi chay lai client."
    }
} finally {
    $ErrorActionPreference = $oldEAP
}

# ---------- 5. Tao/cap nhat server-client.json ----------
Step "5/8 - Ghi $clientJsonPath"
$cfg = $null
if (Test-Path $clientJsonPath) {
    try { $cfg = Get-Content $clientJsonPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $cfg = $null }
    if ($cfg) { Write-Host "Da co server-client.json - giu nguyen machine_id/secret/server_allowed_tools cu." }
}
if (-not $cfg) {
    if (Test-Path "$ClientSrc\server-client.example.json") {
        $cfg = Get-Content "$ClientSrc\server-client.example.json" -Raw -Encoding UTF8 | ConvertFrom-Json
    } else {
        $cfg = New-Object PSObject
    }
}
$cfg | Add-Member -NotePropertyName "server_host" -NotePropertyValue $serverHost -Force
$cfg | Add-Member -NotePropertyName "server_port" -NotePropertyValue $serverPort -Force
$cfg | Add-Member -NotePropertyName "use_tls" -NotePropertyValue $useTls -Force
$cfg | Add-Member -NotePropertyName "machine_name" -NotePropertyValue $MachineName -Force
# 2.1.1: them tool moi config_set_user_password vao scope neu chua co
# (nang cap tu 2.0.0 giu scope cu 100 tool se thieu tool nay).
$tools = @()
if ($cfg.server_allowed_tools) { $tools = @($cfg.server_allowed_tools) }
if ($tools -notcontains "config_set_user_password") { $tools += "config_set_user_password" }
$cfg | Add-Member -NotePropertyName "server_allowed_tools" -NotePropertyValue $tools -Force
# 2.1.1: luu tai khoan/mat khau dieu khien giao dien (neu co nhap luc cai).
# Chi luu khi co ca user + password (LogonUser can mat khau that). Neu
# khong nhap thi giu danh sach users cu (neu co), canh bao neu rong.
if ($GuiUser -and $GuiPassword) {
    $usersList = @()
    if ($cfg.users) { $usersList = @($cfg.users) }
    $found = $false
    foreach ($u in $usersList) {
        if ($u.username -and $u.username.ToString().ToLower() -eq $GuiUser.ToLower()) {
            $u.password = $GuiPassword
            $found = $true
        }
        $u.default = $false
    }
    if (-not $found) {
        $newUser = New-Object PSObject -Property @{ username = $GuiUser; password = $GuiPassword; default = $false }
        $usersList = @($newUser) + $usersList
    }
    # Dua user vua nhap len dau (mac dinh, index 0).
    $target = $null
    $rest = @()
    foreach ($u in $usersList) {
        if ($u.username -and $u.username.ToString().ToLower() -eq $GuiUser.ToLower() -and -not $target) { $target = $u } else { $rest += $u }
    }
    if ($target) {
        $target.default = $true
        $usersList = @($target) + $rest
    }
    $cfg | Add-Member -NotePropertyName "users" -NotePropertyValue $usersList -Force
    Ok "Da luu tai khoan dieu khien giao dien: $GuiUser (mac dinh, mat khau KHONG hien o day)."
} elseif ($GuiUser -and -not $GuiPassword) {
    Warn "Co ten tai khoan ($GuiUser) nhung khong co mat khau - khong luu tai khoan (can mat khau that de dang nhap khi can)."
} else {
    if (-not $cfg.users -or @($cfg.users).Count -eq 0) {
        Warn "Chua luu tai khoan dieu khien giao dien nao - dieu khien man hinh/chuot chi chay duoc khi da co nguoi dang nhap tai may. Co the them sau bang user_add qua MangoServer."
    } else {
        Ok "Giu danh sach tai khoan da luu truoc (khong nhap moi luc cai)."
    }
}
# 2.1.1: desktop_binary tro toi agent-desktop.exe tu dong trong
# $InstallDir\bin (khong phu thuoc C:\MangoMCP). Chi ghi khi file that su
# ton tai; neu khong thi de trong de engine dung mac dinh
# C:\MangoMCP\bin\agent-desktop.exe.
$deskBin = "$InstallDir\bin\agent-desktop.exe"
if (Test-Path $deskBin) {
    $cfg | Add-Member -NotePropertyName "desktop_binary" -NotePropertyValue $deskBin -Force
    Ok "desktop_binary = $deskBin"
} else {
    $cfg | Add-Member -NotePropertyName "desktop_binary" -NotePropertyValue "" -Force
    Warn "Chua co agent-desktop.exe trong $InstallDir\bin - desktop_binary de trong (engine se dung mac dinh C:\MangoMCP\bin\agent-desktop.exe)."
}
# KHONG ghi machine_id / machine_secret o day - client 2.1.1 tu enroll bang URL se ghi.
[System.IO.File]::WriteAllText($clientJsonPath, ($cfg | ConvertTo-Json -Depth 6), (New-Object System.Text.UTF8Encoding $false))
Ok "Da ghi server-client.json: host=$serverHost port=$serverPort use_tls=$useTls machine_name=$MachineName"

# ---------- 6. Dang ky Scheduled Task MangoClient (SYSTEM, luc khoi dong) ----------
Step "6/8 - Dang ky Scheduled Task MangoClient (SYSTEM, khoi dong)"
# 2.1.1: Task chay luc Windows khoi dong bang SYSTEM ("Run whether user is
# logged on or not") — dieu khien duoc bang lenh cmd/powershell ngay ca
# khi chua ai dang nhap. Client chay an bang pythonw.exe (khong cua so),
# tu ghi log ra client.log (khong con run_client_log.bat).
$taskArgs = "run_client.py --config `"$clientJsonPath`" --log-file `"$InstallDir\client.log`""
$action = New-ScheduledTaskAction -Execute $pywExe -Argument $taskArgs -WorkingDirectory $InstallDir
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Days 0) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "MangoClient" -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null
Ok "Da dang ky Task MangoClient (chay luc Windows khoi dong bang SYSTEM, an, pythonw.exe; tu chay lai toi da 3 lan neu crash)."

# ---------- 7. Chay client lan dau ----------
Step "7/8 - Chay client lan dau (tu enroll bang URL)"
Write-Host "Dang chay client bang Task MangoClient (ghi log vao $InstallDir\client.log)..."
Start-ScheduledTask -TaskName "MangoClient"
Start-Sleep -Seconds 12
$logPath = "$InstallDir\client.log"
if (Test-Path $logPath) {
    Write-Host "--- 20 dong cuoi client.log ---"
    Get-Content $logPath -Tail 20 | ForEach-Object { Write-Host "  $_" }
    Write-Host "--- het log ---"
    $logText = (Get-Content $logPath -Raw)
    if ($logText -match "Enroll that bai") {
        Warn "Enroll that bai - kiem tra may con co toi duoc $ServerUrl khong (mang / Cloudflare Tunnel tren Server), roi chay lai Task MangoClient."
    } else {
        Ok "Client dang chay. Vao dashboard cua Server kiem tra may '$MachineName' o trang thai cho duyet, roi nho Quan tri vien duyet."
    }
} else {
    Warn "Chua thay file client.log sau 12 giay - client co the khoi dong cham. Hay doi them roi xem $logPath; neu khong co log, chay Task MangoClient bang tay de xem loi."
}

# ---------- 8. Dang ky Uninstall (hien trong Windows Uninstall) ----------
Step "8/8 - Dang ky Mango Client trong Windows Uninstall"
$clientVersion = "2.1.9"
$initPy = "$InstallDir\mangoclient\__init__.py"
if (Test-Path $initPy) {
    $m = Select-String -Path $initPy -Pattern 'VERSION\s*=\s*"([^"]+)"' | Select-Object -First 1
    if ($m -and $m.Matches.Count -gt 0) { $clientVersion = $m.Matches[0].Groups[1].Value }
}
$uninstKey = "MangoClient"
$uninstExe = "powershell -NoProfile -ExecutionPolicy Bypass -File `"$InstallDir\uninstall_client.ps1`""
$iconPath = "$InstallDir\mango.ico"
if (-not (Test-Path $iconPath)) { $iconPath = "$InstallDir\run_client.py" }
if (-not (Test-Path "$InstallDir\uninstall_client.ps1")) {
    Warn "Khong thay $InstallDir\uninstall_client.ps1 - UninstallString se khong chay duoc. Hay build lai goi client co file nay."
}
$regOK = $false
foreach ($base in @("HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                    "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")) {
    try {
        $key = "$base\$uninstKey"
        New-Item -Path $key -Force | Out-Null
        Set-ItemProperty -Path $key -Name "DisplayName" -Value "Mango Client" -Force
        Set-ItemProperty -Path $key -Name "DisplayVersion" -Value $clientVersion -Force
        Set-ItemProperty -Path $key -Name "Publisher" -Value "Mango" -Force
        Set-ItemProperty -Path $key -Name "DisplayIcon" -Value $iconPath -Force
        Set-ItemProperty -Path $key -Name "UninstallString" -Value $uninstExe -Force
        Set-ItemProperty -Path $key -Name "InstallLocation" -Value $InstallDir -Force
        Set-ItemProperty -Path $key -Name "NoModify" -Value 1 -Type DWord -Force
        Set-ItemProperty -Path $key -Name "NoRepair" -Value 1 -Type DWord -Force
        Ok "Da dang ky Uninstall tai $key (ban $clientVersion)."
        $regOK = $true
        break
    } catch {
        Warn "Khong ghi duoc $base : $($_.Exception.Message)"
    }
}
if (-not $regOK) { Warn "Khong dang ky duoc Uninstall - app se khong hien trong Windows Uninstall." }

Write-Host ""
Write-Host "=== XONG! Mango Client 2.1.9 da cai tren may nay ==="
Write-Host "Server        : $ServerUrl"
Write-Host "Ten may       : $MachineName"
Write-Host "Client        : $InstallDir"
Write-Host "Python        : $pyExe"
Write-Host "Chay an       : $pywExe (khong cua so)"
Write-Host "Cau hinh      : $clientJsonPath"
Write-Host "Nhat ky       : $logPath"
Write-Host "Buoc tiep theo: mo dashboard cua Server, tim may '$MachineName' o muc cho duyet, bam Duyet."
Write-Host "Sau khi duyet, may tu noi (khong can dang nhap); client chay bang SYSTEM luc Windows khoi dong."

# --- Ket thuc: bao dam ma thoat 0 khi cai xong (robocopy tra 1 khi copy
# thanh cong nen $LASTEXITCODE co the con 1; installer C# doc ma thoat
# powershell nen phai reset ve 0 neu khong se bao loi gia). ---
$LASTEXITCODE = 0
exit 0

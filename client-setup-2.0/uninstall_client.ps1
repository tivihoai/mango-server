# Go bo Mango Client 2.1 khoi may Windows.
# Chay bang quyen Admin (tu xin neu chua co). Lam 4 viec:
#  1. Dung + xoa Scheduled Task MangoClient (SYSTEM, chay luc khoi dong).
#  2. Force-quit process Python dang chay run_client.py / gui_agent.py
#     (client 2.1 chay an bang pythonw.exe; ban 2.0.0 cu chay bang
#     python.exe qua run_client_log.bat — tat ca 2 dang).
#  3. Xoa C:\MangoClient\server-client.json + toan bo file client 2.1
#     (tru chinh file uninstaller nay, se tu xoa o cuoi).
#  4. Xoa khoa Uninstall trong registry (HKLM + HKCU).
# KHONG xoa C:\MangoMCP (neu co) - do la MangoMCP cu, go rieng neu muon.
# KHONG xoa Python runtime neu no nam o C:\MangoMCP\python (dung chung).
# Sau khi go xong, may se hien offline tren dashboard cua Server.
param()
$ErrorActionPreference = "Stop"

function Step($msg) { Write-Host ""; Write-Host "=== $msg ===" }
function Ok($msg) { Write-Host "[OK] $msg" }
function Warn($msg) { Write-Host "[CANH BAO] $msg" }

# --- Tu xin quyen Admin neu chua co ---
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Can quyen Admin de go bo - dang mo lai bang quyen Admin..."
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "powershell.exe"
    $psi.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    $psi.Verb = "runas"
    try {
        [System.Diagnostics.Process]::Start($psi) | Out-Null
    } catch {
        Write-Host "Bi huy hoac khong xin duoc quyen Admin - dung go bo."
    }
    exit 0
}

$clientDir = "C:\MangoClient"
$clientJsonPath = "$clientDir\server-client.json"
$taskName = "MangoClient"

Write-Host "Go bo Mango Client 2.1 khoi may nay..."

# ---------- 1. Dung + xoa Scheduled Task ----------
Step "1/4 - Dung va xoa Task $taskName"
try {
    $t = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
    try { Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue | Out-Null } catch { }
    Start-Sleep -Seconds 2
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop | Out-Null
    Ok "Da xoa Task $taskName."
} catch {
    Warn "Khong thay Task $taskName (co the da xoa truoc) - bo qua."
}

# ---------- 2. Force-quit process client ----------
Step "2/4 - Tat phan mem MangoClient dang chay (force quit)"
$killed = 0
try {
    $procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction Stop
    foreach ($p in $procs) {
        $cmd = [string]$p.CommandLine
        if ($cmd -and ($cmd -match "run_client\.py" -or $cmd -match "gui_agent\.py")) {
            try {
                Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
                $killed++
                Write-Host "Da tat $($p.Name) (PID $($p.ProcessId)) dang chay client."
            } catch {
                Warn "Khong tat duoc $($p.Name) PID $($p.ProcessId): $($_.Exception.Message)"
            }
        }
    }
} catch {
    Warn "Khong liet ke duoc process python: $($_.Exception.Message)"
}
try {
    $cmds = Get-CimInstance Win32_Process -Filter "Name = 'cmd.exe'" -ErrorAction Stop
    foreach ($p in $cmds) {
        $cmd = [string]$p.CommandLine
        if ($cmd -and $cmd -match "run_client_log\.bat") {
            try {
                Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
                $killed++
                Write-Host "Da tat cmd.exe (PID $($p.ProcessId)) dang chay run_client_log.bat (ban 2.0.0 cu)."
            } catch { }
        }
    }
} catch { }
if ($killed -eq 0) { Ok "Khong thay process MangoClient nao dang chay." } else { Ok "Da tat $killed process." }
Start-Sleep -Seconds 2

# ---------- 3. Xoa file client ----------
Step "3/4 - Xoa file Client 2.1"
if (Test-Path $clientJsonPath) {
    try { Remove-Item $clientJsonPath -Force -ErrorAction Stop; Ok "Da xoa ${clientJsonPath}." } catch { Warn "Khong xoa duoc ${clientJsonPath}: $($_.Exception.Message)" }
} else {
    Write-Host "Khong thay $clientJsonPath (co the da xoa truoc)."
}
if (Test-Path $clientDir) {
    try {
        # Xoa het file trong thu muc, tru file uninstaller nay (se tu xoa o cuoi).
        Get-ChildItem -Path $clientDir -Recurse -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -ne $PSCommandPath } |
            Remove-Item -Force -Recurse -ErrorAction SilentlyContinue
        # Thu xoa thu muc (chi duoc neu da rong).
        try { Remove-Item $clientDir -Force -ErrorAction Stop; Ok "Da xoa thu muc ${clientDir}." } catch { Warn "Thu muc ${clientDir} van con file (co the bi khoa boi process khac) - hay xoa tay sau khi khoi dong lai may." }
    } catch {
        Warn "Khong xoa duoc file trong ${clientDir}: $($_.Exception.Message)"
    }
} else {
    Write-Host "Khong thay thu muc $clientDir."
}

# ---------- 4. Xoa khoa Uninstall ----------
Step "4/4 - Xoa muc Uninstall trong registry"
foreach ($base in @("HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                    "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")) {
    $key = "$base\MangoClient"
    if (Test-Path $key) {
        try {
            Remove-Item $key -Recurse -Force -ErrorAction Stop
            Ok "Da xoa ${key}."
        } catch {
            Warn "Khong xoa duoc ${key}: $($_.Exception.Message)"
        }
    }
}

Write-Host ""
Write-Host "=== XONG! Da go bo Mango Client 2.1 ==="
Write-Host "May se hien offline tren dashboard cua Server."
Write-Host "MangoMCP cu (neu co o C:\MangoMCP) van con - go rieng neu muon."
# Tu xoa file uninstaller nay o cuoi (chay nen bang cmd de thoat truoc khi xoa).
$self = $PSCommandPath
try {
    Start-Process "cmd.exe" -ArgumentList "/c ping -n 2 127.0.0.1 >nul & del `"$self`"" -WindowStyle Hidden
} catch { }

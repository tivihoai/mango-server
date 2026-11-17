# Go bo Mango Server 1.2.1 khoi may Windows.
# Chay bang quyen Admin (tu xin neu chua co). Lam 4 viec:
#  1. Dung + xoa Scheduled Task MangoServer (SYSTEM, chay luc khoi dong).
#  2. Force-quit process Python dang chay run_server.py.
#  3. Xoa code Server (C:\MangoMCPServer\server) + Python runtime RIENG
#     (C:\MangoMCPServer\python, neu co) + start_server.bat +
#     server-config.json. MAC DINH GIU LAI thu muc data/ (registry, auth,
#     audit, packages) de cai lai khong mat may da enroll; them -RemoveData
#     moi xoa data.
#  4. Xoa khoa Uninstall trong registry (HKLM + HKCU).
# KHONG xoa C:\MangoMCP (neu co) - do la MangoMCP, go rieng neu muon.
# KHONG xoa Python runtime neu no nam o C:\MangoMCP\python (dung chung).
param(
    [switch]$RemoveData
)
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
    $extra = ""
    if ($RemoveData) { $extra = " -RemoveData" }
    $psi.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"$extra"
    $psi.Verb = "runas"
    try {
        [System.Diagnostics.Process]::Start($psi) | Out-Null
    } catch {
        Write-Host "Bi huy hoac khong xin duoc quyen Admin - dung go bo."
    }
    exit 0
}

$installDir = "C:\MangoMCPServer"
$serverDir = "$installDir\server"
$dataDir = "$installDir\data"
$taskName = "MangoServer"

Write-Host "Go bo Mango Server 1.2.1 khoi may nay..."
if (-not $RemoveData) { Write-Host "Giu lai thu muc data/ ($dataDir) - cai lai se thay lai may da enroll. Muon xoa het thi chay lai voi -RemoveData." }

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

# ---------- 2. Force-quit process Server ----------
Step "2/4 - Tat phan mem MangoServer dang chay (force quit)"
$killed = 0
try {
    $procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction Stop
    foreach ($p in $procs) {
        $cmd = [string]$p.CommandLine
        if ($cmd -and $cmd -match "run_server\.py") {
            try {
                Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
                $killed++
                Write-Host "Da tat $($p.Name) (PID $($p.ProcessId)) dang chay Server."
            } catch {
                Warn "Khong tat duoc $($p.Name) PID $($p.ProcessId): $($_.Exception.Message)"
            }
        }
    }
} catch {
    Warn "Khong liet ke duoc process python: $($_.Exception.Message)"
}
if ($killed -eq 0) { Ok "Khong thay process MangoServer nao dang chay." } else { Ok "Da tat $killed process." }
Start-Sleep -Seconds 2

# ---------- 3. Xoa file Server (giu data tru mac dinh) ----------
Step "3/4 - Xoa file Server 1.2.1"
foreach ($path in @($serverDir, "$installDir\python", "$installDir\start_server.bat", "$installDir\server-config.json", "$installDir\server.log")) {
    if (Test-Path $path) {
        try {
            if ($path -eq $PSCommandPath) { continue }
            Remove-Item $path -Force -Recurse -ErrorAction Stop
            Ok "Da xoa $path."
        } catch {
            Warn "Khong xoa duoc ${path}: $($_.Exception.Message)"
        }
    }
}
if ($RemoveData) {
    if (Test-Path $dataDir) {
        try { Remove-Item $dataDir -Force -Recurse -ErrorAction Stop; Ok "Da xoa data/ ($dataDir) theo -RemoveData." } catch { Warn "Khong xoa duoc ${dataDir}: $($_.Exception.Message)" }
    }
    Get-ChildItem -Path $installDir -Filter "data-backup-*" -Directory -ErrorAction SilentlyContinue | ForEach-Object {
        try { Remove-Item $_.FullName -Force -Recurse -ErrorAction Stop; Ok "Da xoa $($_.FullName)." } catch { Warn "Khong xoa duoc $($_.FullName)." }
    }
} else {
    if (Test-Path $dataDir) { Write-Host "Giu lai $dataDir (may da enroll + token + nhat ky van con)." }
}
try {
    if ((Test-Path $installDir) -and @(Get-ChildItem $installDir -Force).Count -eq 0) {
        Remove-Item $installDir -Force -ErrorAction Stop
        Ok "Da xoa thu muc rong $installDir."
    }
} catch { }

# ---------- 4. Xoa khoa Uninstall ----------
Step "4/4 - Xoa muc Uninstall trong registry"
foreach ($base in @("HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                    "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")) {
    $key = "$base\MangoServer"
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
Write-Host "=== XONG! Da go bo Mango Server 1.2.1 ==="
Write-Host "May con se hien offline (Server tren may nay da dung)."
# Tu xoa file uninstaller nay o cuoi (chay nen bang cmd de thoat truoc khi xoa).
$self = $PSCommandPath
try {
    Start-Process "cmd.exe" -ArgumentList "/c ping -n 2 127.0.0.1 >nul & del `"$self`"" -WindowStyle Hidden
} catch { }

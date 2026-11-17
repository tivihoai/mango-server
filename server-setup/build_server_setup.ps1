# Build MangoServer-Setup-1.2.1.exe - CHAY TREN WINDOWS (may build).
# Cach chay (mo PowerShell tai thu muc server-setup, quyen thuong la du):
#   powershell -ExecutionPolicy Bypass -File .\build_server_setup.ps1
#   powershell -ExecutionPolicy Bypass -File .\build_server_setup.ps1 -MangoMCPZip "C:\MangoMCP-Package\MangoMCP-0.14.2-win64-full.zip"
#
# Lam 3 viec:
#  1. Dong goi server 1.2.1 (thu muc server/ + install_server.ps1 +
#     uninstall_server.ps1 + set_admin.py) thanh MangoServer-1.2.1.zip
#     (loai __pycache__).
#  2. Bien dich MangoServerSetup.cs bang csc.exe (.NET Framework 4.0),
#     nhung 2 zip lam resource (MangoMCPFull.zip + MangoServer.zip). Goi
#     MangoMCP Full chi dung de lay thu muc python lam runtime (KHONG cai
#     MangoMCP).
#  3. Xuat MangoServer-Setup-1.2.1.exe + in SHA-256 de kiem chung.
#
# Gioi han (noi that): file exe CHI build duoc tren Windows - can csc.exe
# + goi MangoMCP Full (chi co tren may Windows, mac dinh tim trong
# C:\MangoMCP-Package). Tren Linux chi lam duoc code C#, script ps1, zip
# goi server; KHONG co exe.
param(
    [string]$MangoMCPZip = "",
    [string]$OutDir = "",
    [string]$Version = "1.2.1"
)
$ErrorActionPreference = "Stop"
# --- ENCODING GUARD: file .ps1 phai la UTF-8 BOM + CRLF sach, ParseFile 0 loi ---
# (Bai hoc hoi quy 2.1.5/2.1.6/2.1.7: install_client.ps1 bi gap doi CR
#  \r\r\n giua build 2.1.4 va 2.1.5, xem client-setup-2.0/INVESTIGATION-215-217.md.
#  Guard nay fail-loudly, KHONG build ra exe loi.)
function Test-PsScriptEncoding {
    param([string]$Path)
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -lt 3 -or $bytes[0] -ne 0xEF -or $bytes[1] -ne 0xBB -or $bytes[2] -ne 0xBF) {
        throw "ENCODING_GUARD FAIL: $Path thieu BOM UTF-8 (3 byte dau phai la EF BB BF). Hay luu file dang UTF-8 BOM truoc khi build."
    }
    $cr = 0; $lf = 0; $crlf = 0; $doubleCr = 0
    for ($i = 0; $i -lt $bytes.Length; $i++) {
        if ($bytes[$i] -eq 0x0D) {
            $cr++
            if ($i + 1 -lt $bytes.Length -and $bytes[$i + 1] -eq 0x0A) { $crlf++ }
            if ($i + 2 -lt $bytes.Length -and $bytes[$i + 1] -eq 0x0D -and $bytes[$i + 2] -eq 0x0A) { $doubleCr++ }
        }
        if ($bytes[$i] -eq 0x0A) { $lf++ }
    }
    if ($doubleCr -gt 0) {
        throw "ENCODING_GUARD FAIL: $Path co $doubleCr dong xuong dong bi gap doi CR (\r\r\n, CR=$cr/LF=$lf). Giong hoi quy 2.1.5/2.1.6/2.1.7 (INVESTIGATION-215-217.md). Hay sua file nguon ve CRLF sach roi build lai — KHONG build ra exe loi."
    }
    if ($cr -ne $lf -or $lf -ne $crlf) {
        throw "ENCODING_GUARD FAIL: $Path khong phai CRLF sach (CR=$cr, LF=$lf, CRLF=$crlf; co dong LF don hoac CR thua). Hay chuan hoa ve UTF-8 BOM + CRLF roi build lai."
    }
    $tokens = $null; $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors)
    if ($errors -and $errors.Count -gt 0) {
        throw "ENCODING_GUARD FAIL: $Path loi cu phap PowerShell ($($errors.Count) loi; loi dau: $($errors[0].Message)). Hay sua truoc khi build."
    }
    Write-Host "Encoding OK: $Path (BOM, CRLF sach $crlf dong, ParseFile 0 loi)."
}


# --- GUARD BIEN TU DONG PowerShell: $Host (va cac bien chi doc khac) KHONG
# duoc dung lam ten param/bien trong script cai dat ---
# (Bai hoc 17/11/2026: install_server.ps1 khai param [string]$Host lam ca
# script chet ngay khi chay - "Cannot overwrite variable Host because it
# is read-only or constant", thoat ma 1, KHONG co log cai dat vi
# Start-Transcript nam SAU khoi param. ParseFile van bao 0 loi vi day la
# loi runtime luc bind param, khong phai loi cu phap.)
function Test-NoReservedVariableNames {
    param([string]$Path)
    $text = Get-Content $Path -Raw
    $bad = @()
    if ($text -match '\$\{?Host\}?\b') { $bad += '$Host' }
    if (($text -replace '\$ErrorActionPreference','') -match '\$Error\b') { $bad += '$Error' }
    if ($text -match '\$PID\b') { $bad += '$PID' }
    if ($text -match '\$\{?PSVersionTable\}?\b') { $bad += '$PSVersionTable' }
    if ($text -match '\$\{?ExecutionContext\}?\b') { $bad += '$ExecutionContext' }
    if ($text -match '\$Input\b') { $bad += '$Input' }
    if ($text -match '\$Args\b') { $bad += '$Args' }
    if ($bad.Count -gt 0) {
        throw "RESERVED_VAR_GUARD FAIL: $Path dung bien tu dong chi doc cua PowerShell ($($bad -join ', ')) - script se chet ma 1 ngay khi chay ('Cannot overwrite variable ... because it is read-only or constant') ma ParseFile khong phat hien. Doi ten bien (vd `$Host -> `$BindHost) roi build lai."
    }
    Write-Host "Reserved-var OK: $Path (khong dung bien tu dong chi doc)."
}


$setupDir = $PSScriptRoot
$root = Split-Path -Parent $setupDir   # thu muc mango-server/
$serverDir = "$root\server"
if ([string]::IsNullOrWhiteSpace($OutDir)) { $OutDir = $setupDir }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

if (-not (Test-Path "$serverDir\run_server.py")) {
    throw "Khong thay code server 1.2.1 tai $serverDir (thieu run_server.py). Hay chay script nay tu thu muc server-setup cua mango-server."
}
if (-not (Test-Path "$serverDir\mangoserver\app.py")) {
    throw "Khong thay code server 1.2.1 tai $serverDir (thieu mangoserver\app.py)."
}
if (-not (Test-Path "$serverDir\mangoserver\dashboard.py")) {
    throw "Khong thay code server 1.2.1 tai $serverDir (thieu mangoserver\dashboard.py)."
}
if (-not (Test-Path "$serverDir\mangoserver\auth.py")) {
    throw "Khong thay code server 1.2.1 tai $serverDir (thieu mangoserver\auth.py)."
}
$verText = Get-Content "$serverDir\mangoserver\__init__.py" -Raw
if ($verText -notmatch 'VERSION\s*=\s*"1\.2\.1"') {
    throw "VERSION trong mangoserver\__init__.py khong phai 1.2.1 - hay kiem tra lai truoc khi build."
}
if (-not (Test-Path "$setupDir\MangoServerSetup.cs")) { throw "Thieu $setupDir\MangoServerSetup.cs" }
if (-not (Test-Path "$setupDir\install_server.ps1")) { throw "Thieu $setupDir\install_server.ps1" }
if (-not (Test-Path "$setupDir\uninstall_server.ps1")) { throw "Thieu $setupDir\uninstall_server.ps1 (can cho chuc nang go bo trong Windows Uninstall)" }
if (-not (Test-Path "$setupDir\set_admin.py")) { throw "Thieu $setupDir\set_admin.py (can de dat mat khau quan tri khong tuong tac)" }
# Guard encoding file nguon truoc khi dong goi (fail-loudly neu sai).
Test-PsScriptEncoding "$setupDir\build_server_setup.ps1"
Test-PsScriptEncoding "$setupDir\install_server.ps1"
Test-PsScriptEncoding "$setupDir\uninstall_server.ps1"
Test-NoReservedVariableNames "$setupDir\install_server.ps1"
Test-NoReservedVariableNames "$setupDir\uninstall_server.ps1"
# Kiem tra install_server.ps1 co du cac buoc bat buoc (de khong build ra
# exe thieu sua): Task MangoServer SYSTEM AtStartup, set_admin.py, kiem
# tra /health, Uninstall.
$installText = Get-Content "$setupDir\install_server.ps1" -Raw
if ($installText -notmatch "MangoServer") { throw "install_server.ps1 thieu Task MangoServer - hay kiem tra lai truoc khi build." }
if ($installText -notmatch "AtStartup") { throw "install_server.ps1 thieu trigger AtStartup - Server se khong tu chay lai sau khi khoi dong." }
if ($installText -notmatch "SYSTEM") { throw "install_server.ps1 thieu user SYSTEM - Server se khong chay duoc khi chua ai dang nhap." }
if ($installText -notmatch "set_admin\.py") { throw "install_server.ps1 thieu buoc set_admin.py - hay kiem tra lai truoc khi build." }
if ($installText -notmatch "/health") { throw "install_server.ps1 thieu kiem tra /health - hay kiem tra lai truoc khi build." }
if ((Get-Content "$setupDir\MangoServerSetup.cs" -Raw) -notmatch "SILENT") { throw "MangoServerSetup.cs thieu che do silent - hay kiem tra lai truoc khi build." }
if (-not (Test-Path "$setupDir\mango.ico")) { Write-Host "CANH BAO: khong thay $setupDir\mango.ico - exe se khong co icon qua xoai." }

# --- Tim goi MangoMCP Full (can de lay thu muc python lam runtime) ---
if ([string]::IsNullOrWhiteSpace($MangoMCPZip)) {
    $found = Get-ChildItem "C:\MangoMCP-Package\MangoMCP-*-win64-full.zip" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($found) { $MangoMCPZip = $found.FullName }
}
if ([string]::IsNullOrWhiteSpace($MangoMCPZip) -or -not (Test-Path $MangoMCPZip)) {
    throw "Khong tim thay goi MangoMCP Full (.zip). Build exe can goi nay de lay Python runtime cho may trang. Hay chi duong dan bang -MangoMCPZip (vi du: -MangoMCPZip 'C:\MangoMCP-Package\MangoMCP-0.14.2-win64-full.zip'), hoac dat file zip vao C:\MangoMCP-Package roi chay lai."
}
Write-Host "Goi MangoMCP Full (lay python): $MangoMCPZip ($( '{0:N1} MB' -f ((Get-Item $MangoMCPZip).Length / 1MB) ))"

# --- 1. Dong goi server 1.2.1 ---
$stage = Join-Path $env:TEMP "MangoServer-Stage-$Version"
Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $stage | Out-Null
robocopy "$serverDir" "$stage" /E /XD __pycache__ /NFL /NDL /NJH /NJS /R:1 /W:1 | Out-Null
Copy-Item "$setupDir\install_server.ps1", "$setupDir\uninstall_server.ps1", "$setupDir\set_admin.py" -Destination $stage -Force
if (Test-Path "$setupDir\mango.ico") { Copy-Item "$setupDir\mango.ico" -Destination $stage -Force }
if (-not (Test-Path "$stage\run_server.py")) { throw "Dong goi server that bai: thieu run_server.py trong $stage" }
if (-not (Test-Path "$stage\mangoserver\app.py")) { throw "Dong goi server that bai: thieu mangoserver\app.py trong $stage" }
if (-not (Test-Path "$stage\mangoserver\dashboard.py")) { throw "Dong goi server that bai: thieu mangoserver\dashboard.py trong $stage" }
if (-not (Test-Path "$stage\install_server.ps1")) { throw "Dong goi server that bai: thieu install_server.ps1 trong $stage" }
if (-not (Test-Path "$stage\uninstall_server.ps1")) { throw "Dong goi server that bai: thieu uninstall_server.ps1 trong $stage" }
if (-not (Test-Path "$stage\set_admin.py")) { throw "Dong goi server that bai: thieu set_admin.py trong $stage" }
# Guard lai file trong stage (chong file bi ghi lai sai encoding o buoc copy).
Test-PsScriptEncoding "$stage\install_server.ps1"
Test-PsScriptEncoding "$stage\uninstall_server.ps1"
Test-NoReservedVariableNames "$stage\install_server.ps1"
Test-NoReservedVariableNames "$stage\uninstall_server.ps1"
# Kiem tra nhanh: code server dong goi phai bien dich duoc (python -m py_compile).
$pyCheck = "C:\MangoMCP\python\python.exe"
if (Test-Path $pyCheck) {
    & $pyCheck -m py_compile "$stage\run_server.py" "$stage\set_admin.py" "$stage\mangoserver\app.py" "$stage\mangoserver\auth.py" "$stage\mangoserver\dashboard.py" "$stage\mangoserver\hub.py" "$stage\mangoserver\monitor.py" "$stage\mangoserver\registry.py"
    if ($LASTEXITCODE -ne 0) { throw "Code server dong goi loi cu phap (py_compile that bai) - hay sua truoc khi build." }
    Write-Host "Code server dong goi bien dich duoc (py_compile OK)."
} else {
    Write-Host "CANH BAO: khong thay $pyCheck - bo qua kiem tra py_compile."
}
$serverZip = "$OutDir\MangoServer-$Version.zip"
if (Test-Path $serverZip) { Remove-Item $serverZip -Force }
Compress-Archive -Path "$stage\*" -DestinationPath $serverZip -Force
Write-Host "Goi server: $serverZip ($( '{0:N1} KB' -f ((Get-Item $serverZip).Length / 1KB) ))"

# --- 2. Bien dich Setup.exe bang csc.exe (.NET Framework 4.0) ---
$csc = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $csc)) {
    throw "Khong thay csc.exe tai $csc. May build can .NET Framework 4.0+ (co san tren Windows 10)."
}
$exeOut = "$OutDir\MangoServer-Setup-$Version.exe"
$iconArg = @()
if (Test-Path "$setupDir\mango.ico") { $iconArg = @("/win32icon:$setupDir\mango.ico") }
$manifestArg = @()
if (Test-Path "$setupDir\app.manifest") { $manifestArg = @("/win32manifest:$setupDir\app.manifest") }
& $csc /nologo /target:winexe `
    /reference:System.Windows.Forms.dll /reference:System.Drawing.dll `
    /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll `
    @iconArg @manifestArg `
    /resource:$MangoMCPZip,MangoMCPFull.zip `
    /resource:$serverZip,MangoServer.zip `
    /out:$exeOut "$setupDir\MangoServerSetup.cs"
if ($LASTEXITCODE -ne 0) { throw "Bien dich MangoServer-Setup.exe that bai (csc.exe ma loi $LASTEXITCODE)." }
if (-not (Test-Path $exeOut)) { throw "Bien dich xong nhung khong thay $exeOut" }

# --- 3. Kiem chung: SHA-256 + kich thuoc ---
$hash = (Get-FileHash $exeOut -Algorithm SHA256).Hash
$sizeMB = (Get-Item $exeOut).Length / 1MB
Write-Host ""
Write-Host "BUILD_DONE"
Write-Host "Exe : $exeOut ($( '{0:N1} MB' -f $sizeMB ))"
Write-Host "SHA-256: $hash"
Write-Host "Goi server zip giu lai tai: $serverZip"
Write-Host "Gui file exe nay cho may moi, nhap cong + thu muc data + mat khau quan tri roi bam Cai dat - Server tu chay lai sau khi khoi dong may."
Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue

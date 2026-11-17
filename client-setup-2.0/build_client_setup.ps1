# Build MangoClient-Setup-2.1.9.exe - CHAY TREN WINDOWS (PC1 hoac may build).
# Cach chay (mo PowerShell tai thu muc client-setup-2.0, quyen thuong la du):
#   powershell -ExecutionPolicy Bypass -File .\build_client_setup.ps1
#   powershell -ExecutionPolicy Bypass -File .\build_client_setup.ps1 -CustomHost
#   powershell -ExecutionPolicy Bypass -File .\build_client_setup.ps1 -MangoMCPZip "C:\MangoMCP-Package\MangoMCP-0.14.2-win64-full.zip"
#
# Lam 3 viec:
#  1. Dong goi client 2.1.9 (thu muc client-2.0/client/ + install_client.ps1 +
#     uninstall_client.ps1) thanh MangoClient-2.1.9.zip (loai __pycache__).
#  2. Bien dich MangoClientSetup.cs bang csc.exe (.NET Framework 4.0), nhung 2 zip
#     lam resource (MangoMCPFull.zip + MangoClient.zip). Goi MangoMCP Full chi
#     dung de lay thu muc python lam runtime + bin/agent-desktop.exe va
#     app/MangoOverlay.exe (KHONG cai MangoMCP).
#  3. Xuat MangoClient-Setup-2.1.9.exe + in SHA-256 de kiem chung.
#
# Ban CustomHost (-CustomHost): cung code client 2.1.9, chi khac C# duoc
# bien dich voi /define:CUSTOM_HOST de hien them o nhap Server host/cong;
# exe ra la MangoClient-Setup-2.1.9-CustomHost.exe. Ban chuan khong co 2 o
# nay, C# truyen -ServerHost mac dinh de cai zero-input.
#
# ENCODING GUARD (2.1.8, sau dieu tra INVESTIGATION-215-217.md): file
# install_client.ps1 nhung trong exe 2.1.5/2.1.6/2.1.7 bi gap doi CR
# (\r\r\n, CR=940/LF=470) so voi 2.1.4 CRLF sach, do file nguon tren PC1
# bi ghi lai sai giua 2 build. Build script nay KIEM TRA TRUOC KHI BUILD
# (va kiem tra lai file trong zip + resource trong exe): .ps1 cai/go phai
# la UTF-8 BOM + CRLF sach (khong \r\r\n, khong dong LF don) va
# Parser::ParseFile() = 0 loi. Khong dat thi build DUNG NGAY (throw),
# khong build ra exe loi.
#
# VERSION GUARD (2.1.8, cung sau dieu tra tren): exe 2.1.5 o build-dir
# that ra nhung script 2.1.6 (build nham nhan). Build script nay kiem tra
# version yeu cau ($Version) khop o moi cho — VERSION trong
# mangoclient/__init__.py + mangoengine/server_tools.py, chuoi version
# trong MangoClientSetup.cs + install_client.ps1 — roi kiem tra file
# install_client.ps1 trong zip giong byte-exact file nguon (SHA-256) va
# resource MangoClient.zip trong exe giong byte-exact file zip vua dong
# goi. Khong khop thi build DUNG NGAY.
#
# Gioi han (noi that): file exe CHI build duoc tren Windows - can csc.exe + goi
# MangoMCP Full (chi co tren may Windows, mac dinh tim trong C:\MangoMCP-Package).
# Tren Linux chi lam duoc code C#, script ps1, zip goi client; KHONG co exe.
param(
    [string]$MangoMCPZip = "",
    [string]$OutDir = "",
    [string]$Version = "2.1.9",
    [switch]$CustomHost
)
$ErrorActionPreference = "Stop"
$setupDir = $PSScriptRoot
$root = Split-Path -Parent $setupDir   # thu muc mango-server/
$clientDir = "$root\client-2.0\client"
if ([string]::IsNullOrWhiteSpace($OutDir)) { $OutDir = $setupDir }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

# --- ENCODING GUARD: 1 file .ps1 phai la UTF-8 BOM + CRLF sach + parse 0 loi ---
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

# --- VERSION GUARD: version yeu cau phai khop o moi cho mang so version ---
function Assert-VersionMatch {
    $initPy = "$clientDir\mangoclient\__init__.py"
    $verText = Get-Content $initPy -Raw
    if ($verText -notmatch [regex]::Escape("VERSION = `"$Version`"")) {
        throw "VERSION_GUARD FAIL: VERSION trong mangoclient\__init__.py khong phai $Version (tham so -Version). Hay tang version o dung cho hoac truyen -Version dung roi build lai."
    }
    $toolsPy = "$clientDir\mangoengine\server_tools.py"
    if ((Get-Content $toolsPy -Raw) -notmatch [regex]::Escape("VERSION = `"$Version`"")) {
        throw "VERSION_GUARD FAIL: VERSION trong mangoengine\server_tools.py khong phai $Version (control_status bao core_version/client_version tu day). Hay dong bo version roi build lai."
    }
    $csText = Get-Content "$setupDir\MangoClientSetup.cs" -Raw
    if ($csText -notmatch [regex]::Escape("Mango Client $Version")) {
        throw "VERSION_GUARD FAIL: MangoClientSetup.cs khong chua chuoi 'Mango Client $Version'. Hay tang version trong C# roi build lai."
    }
    $installText = Get-Content "$setupDir\install_client.ps1" -Raw
    if ($installText -notmatch [regex]::Escape("Mango Client $Version")) {
        throw "VERSION_GUARD FAIL: install_client.ps1 khong chua chuoi 'Mango Client $Version' (header). Hay tang version trong script cai roi build lai."
    }
    if ($installText -notmatch [regex]::Escape("`$clientVersion = `"$Version`"")) {
        throw "VERSION_GUARD FAIL: install_client.ps1 co `$clientVersion fallback khac $Version. Hay dong bo roi build lai."
    }
    if ($CustomHost) {
        if ($csText -notmatch "#if CUSTOM_HOST" -or $csText -notmatch "_hostBox") {
            throw "VERSION_GUARD FAIL: build -CustomHost nhung MangoClientSetup.cs thieu khoi #if CUSTOM_HOST / _hostBox. Hay kiem tra lai C# roi build lai."
        }
    }
    Write-Host "Version OK: moi cho deu la $Version."
}

if (-not (Test-Path "$clientDir\run_client.py")) {
    throw "Khong thay code client 2.1 tai $clientDir (thieu run_client.py). Hay chay script nay tu thu muc client-setup-2.0 cua mango-server."
}
if (-not (Test-Path "$clientDir\gui_agent.py")) {
    throw "Khong thay code client 2.1 tai $clientDir (thieu gui_agent.py)."
}
if (-not (Test-Path "$clientDir\mangoengine\direct_engine.py")) {
    throw "Khong thay engine 2.1 tai $clientDir\mangoengine (thieu direct_engine.py)."
}
if (-not (Test-Path "$clientDir\mangoengine\session.py")) {
    throw "Khong thay engine 2.1 tai $clientDir\mangoengine (thieu session.py)."
}
if (-not (Test-Path "$clientDir\mangoengine\gui.py")) {
    throw "Khong thay engine 2.1 tai $clientDir\mangoengine (thieu gui.py)."
}
if (-not (Test-Path "$clientDir\mangoengine\ipc.py")) {
    throw "Khong thay engine 2.1 tai $clientDir\mangoengine (thieu ipc.py)."
}
if (-not (Test-Path "$setupDir\MangoClientSetup.cs")) { throw "Thieu $setupDir\MangoClientSetup.cs" }
if (-not (Test-Path "$setupDir\install_client.ps1")) { throw "Thieu $setupDir\install_client.ps1" }
# 2.1.1: kiem tra install_client.ps1 co buoc copy agent-desktop.exe (BUG 3)
# va cat dau nhay o $GuiUser (BUG 1) — de khong build ra exe cu thieu sua.
$installText = Get-Content "$setupDir\install_client.ps1" -Raw
if ($installText -notmatch "agent-desktop\.exe") { throw "install_client.ps1 thieu buoc copy agent-desktop.exe (BUG 3) - hay kiem tra lai truoc khi build." }
if ($installText -notmatch "desktop_binary") { throw "install_client.ps1 thieu ghi desktop_binary (BUG 3) - hay kiem tra lai truoc khi build." }
if ($installText -notmatch 'Substring\(1, \$GuiUser\.Length - 2\)') { throw "install_client.ps1 thieu cat dau nhay o GuiUser (BUG 1) - hay kiem tra lai truoc khi build." }
if ((Get-Content "$setupDir\MangoClientSetup.cs" -Raw) -notmatch "_closeTimer") { throw "MangoClientSetup.cs thieu tu dong dong cua so (BUG 2) - hay kiem tra lai truoc khi build." }
if (-not (Test-Path "$setupDir\uninstall_client.ps1")) { throw "Thieu $setupDir\uninstall_client.ps1 (can cho chuc nang go bo trong Windows Uninstall)" }
if (-not (Test-Path "$setupDir\mango.ico")) { Write-Host "CANH BAO: khong thay $setupDir\mango.ico - exe se khong co icon qua xoai." }

# --- 0. Guard: encoding + version (FAIL LOUDLY truoc khi dong goi) ---
Test-PsScriptEncoding "$setupDir\install_client.ps1"
Test-PsScriptEncoding "$setupDir\uninstall_client.ps1"
Assert-VersionMatch
if ($CustomHost) { Write-Host "Ban build: CustomHost (exe rieng, co o nhap Server host/cong; khong chua host mac dinh)." } else { Write-Host "Ban build: chuan (C# truyen Server host mac dinh de cai zero-input)." }

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

# --- 1. Dong goi client 2.0 ---
$stage = Join-Path $env:TEMP "MangoClient2-Stage-$Version"
Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $stage | Out-Null
robocopy "$clientDir" "$stage" /E /XD __pycache__ /NFL /NDL /NJH /NJS /R:1 /W:1 | Out-Null
Copy-Item "$setupDir\install_client.ps1", "$setupDir\uninstall_client.ps1" -Destination $stage -Force
if (Test-Path "$setupDir\mango.ico") { Copy-Item "$setupDir\mango.ico" -Destination $stage -Force }
if (-not (Test-Path "$stage\run_client.py")) { throw "Dong goi client that bai: thieu run_client.py trong $stage" }
if (-not (Test-Path "$stage\gui_agent.py")) { throw "Dong goi client that bai: thieu gui_agent.py trong $stage" }
if (-not (Test-Path "$stage\mangoclient\agent.py")) { throw "Dong goi client that bai: thieu mangoclient\agent.py trong $stage" }
if (-not (Test-Path "$stage\mangoengine\direct_engine.py")) { throw "Dong goi client that bai: thieu mangoengine\direct_engine.py trong $stage" }
if (-not (Test-Path "$stage\mangoengine\session.py")) { throw "Dong goi client that bai: thieu mangoengine\session.py trong $stage" }
if (-not (Test-Path "$stage\mangoengine\gui.py")) { throw "Dong goi client that bai: thieu mangoengine\gui.py trong $stage" }
if (-not (Test-Path "$stage\mangoengine\ipc.py")) { throw "Dong goi client that bai: thieu mangoengine\ipc.py trong $stage" }
if (-not (Test-Path "$stage\uninstall_client.ps1")) { throw "Dong goi client that bai: thieu uninstall_client.ps1 trong $stage" }
# Guard lai file trong stage (chong file bi ghi lai sai encoding o buoc
# copy/stage nhu hoi quy 2.1.5): phai giong byte-exact file nguon.
Test-PsScriptEncoding "$stage\install_client.ps1"
Test-PsScriptEncoding "$stage\uninstall_client.ps1"
foreach ($f in @("install_client.ps1", "uninstall_client.ps1")) {
    $a = (Get-FileHash "$setupDir\$f" -Algorithm SHA256).Hash
    $b = (Get-FileHash "$stage\$f" -Algorithm SHA256).Hash
    if ($a -ne $b) { throw "VERSION_GUARD FAIL: $f trong stage khac file nguon (SHA-256 khac: nguon $a, stage $b). Dung build, kiem tra lai buoc copy." }
}
$clientZip = "$OutDir\MangoClient-$Version.zip"
if (Test-Path $clientZip) { Remove-Item $clientZip -Force }
Compress-Archive -Path "$stage\*" -DestinationPath $clientZip -Force
Write-Host "Goi client: $clientZip ($( '{0:N1} KB' -f ((Get-Item $clientZip).Length / 1KB) ))"

# --- 1b. Kiem tra goi zip vua dong: script nhung trong zip phai dung version + dung encoding ---
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead($clientZip)
try {
    $entry = $zip.Entries | Where-Object { $_.FullName -eq "install_client.ps1" } | Select-Object -First 1
    if (-not $entry) { throw "VERSION_GUARD FAIL: khong thay install_client.ps1 trong $clientZip." }
    $ms = New-Object System.IO.MemoryStream
    $entry.Open().CopyTo($ms)
    $zipBytes = $ms.ToArray()
    $zipHash = ([System.Security.Cryptography.SHA256]::Create().ComputeHash($zipBytes) | ForEach-Object { $_.ToString("x2") }) -join ""
    $srcHash = (Get-FileHash "$setupDir\install_client.ps1" -Algorithm SHA256).Hash.ToLower()
    if ($zipHash -ne $srcHash) { throw "VERSION_GUARD FAIL: install_client.ps1 trong zip khac file nguon (SHA-256 khac). Day chinh la loi build nham nhan 2.1.5 (zip nhung nham script ban khac). Dung build." }
    if ($zipBytes.Length -lt 3 -or $zipBytes[0] -ne 0xEF -or $zipBytes[1] -ne 0xBB -or $zipBytes[2] -ne 0xBF) { throw "ENCODING_GUARD FAIL: install_client.ps1 trong zip thieu BOM UTF-8." }
    $zipText = [System.Text.Encoding]::UTF8.GetString($zipBytes)
    if ($zipText -notmatch [regex]::Escape("Mango Client $Version")) { throw "VERSION_GUARD FAIL: install_client.ps1 trong zip khong chua chuoi 'Mango Client $Version' (nhung nham script ban khac). Dung build." }
    $initEntry = $zip.Entries | Where-Object { ($_.FullName -replace '\\', '/') -eq "mangoclient/__init__.py" } | Select-Object -First 1
    if ($initEntry) {
        $ms2 = New-Object System.IO.MemoryStream
        $initEntry.Open().CopyTo($ms2)
        $initText = [System.Text.Encoding]::UTF8.GetString($ms2.ToArray())
        if ($initText -notmatch [regex]::Escape("VERSION = `"$Version`"")) { throw "VERSION_GUARD FAIL: mangoclient/__init__.py trong zip co VERSION khac $Version (nhung nham code ban khac). Dung build." }
    } else {
        throw "VERSION_GUARD FAIL: khong thay mangoclient/__init__.py trong $clientZip."
    }
    Write-Host "Zip OK: script nhung trong zip giong byte-exact file nguon $Version."
} finally {
    $zip.Dispose()
}

# --- 2. Bien dich Setup.exe bang csc.exe (.NET Framework 4.0) ---
$csc = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $csc)) {
    throw "Khong thay csc.exe tai $csc. May build can .NET Framework 4.0+ (co san tren Windows 10)."
}
if ($CustomHost) { $exeOut = "$OutDir\MangoClient-Setup-$Version-CustomHost.exe" } else { $exeOut = "$OutDir\MangoClient-Setup-$Version.exe" }
$iconArg = @()
if (Test-Path "$setupDir\mango.ico") { $iconArg = @("/win32icon:$setupDir\mango.ico") }
$manifestArg = @()
if (Test-Path "$setupDir\app.manifest") { $manifestArg = @("/win32manifest:$setupDir\app.manifest") }
$defineArg = @()
if ($CustomHost) { $defineArg = @("/define:CUSTOM_HOST") }
& $csc /nologo /target:winexe `
    /reference:System.Windows.Forms.dll /reference:System.Drawing.dll `
    /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll `
    @iconArg @manifestArg @defineArg `
    /resource:$MangoMCPZip,MangoMCPFull.zip `
    /resource:$clientZip,MangoClient.zip `
    /out:$exeOut "$setupDir\MangoClientSetup.cs"
if ($LASTEXITCODE -ne 0) { throw "Bien dich MangoClient-Setup.exe that bai (csc.exe ma loi $LASTEXITCODE)." }
if (-not (Test-Path $exeOut)) { throw "Bien dich xong nhung khong thay $exeOut" }

# --- 2b. Kiem tra exe vua bien dich: resource MangoClient.zip trong exe phai giong file zip vua dong ---
try {
    $asm = [System.Reflection.Assembly]::LoadFrom($exeOut)
    $rs = $asm.GetManifestResourceStream("MangoClient.zip")
    if (-not $rs) { throw "VERSION_GUARD FAIL: khong doc duoc resource MangoClient.zip trong $exeOut." }
    $ms3 = New-Object System.IO.MemoryStream
    $rs.CopyTo($ms3)
    $exeZipHash = ([System.Security.Cryptography.SHA256]::Create().ComputeHash($ms3.ToArray()) | ForEach-Object { $_.ToString("x2") }) -join ""
    $zipHash2 = (Get-FileHash $clientZip -Algorithm SHA256).Hash.ToLower()
    if ($exeZipHash -ne $zipHash2) { throw "VERSION_GUARD FAIL: resource MangoClient.zip trong exe khac file $clientZip (SHA-256 khac). Exe dang nhung goi cu/khac version. Dung build, khong phat hanh exe nay." }
    $rs2 = $asm.GetManifestResourceStream("MangoMCPFull.zip")
    if (-not $rs2) { throw "VERSION_GUARD FAIL: khong doc duoc resource MangoMCPFull.zip trong $exeOut." }
    Write-Host "Exe OK: resource MangoClient.zip trong exe giong byte-exact goi $Version."
} catch {
    if ($_.Exception.Message -match "VERSION_GUARD FAIL") { throw $_ }
    throw "VERSION_GUARD FAIL: khong kiem tra duoc resource trong exe ($($_.Exception.Message)). Dung build thay vi phat hanh exe chua kiem chung."
}

# --- 2c. Kiem tra exe CustomHost khong chua thong tin ca nhan (2.1.9) ---
# Ban CustomHost xuat ban KHONG duoc chua host mac dinh / ten rieng /
# cach xung ho ca nhan. Quet ca chuoi ASCII va UTF-16LE (chuoi .NET
# trong exe luu dang UTF-16LE). Chi kiem tra ban CustomHost; ban chuan
# (noi bo) co chua host mac dinh do C# truyen -ServerHost.
if ($CustomHost) {
    $exeBytes = [System.IO.File]::ReadAllBytes($exeOut)
    $exeAscii = [System.Text.Encoding]::ASCII.GetString($exeBytes)
    $exeUtf16 = [System.Text.Encoding]::Unicode.GetString($exeBytes)
    foreach ($bad in @("your-server.example.com")) {
        if ($exeAscii.Contains($bad) -or $exeUtf16.Contains($bad)) {
            throw "CUSTOMHOST_GUARD FAIL: exe CustomHost con chua chuoi ca nhan '$bad'. Hay don sach ban CustomHost (C# nhanh CUSTOM_HOST + goi client) roi build lai — KHONG phat hanh exe nay."
        }
    }
    # The public default-host placeholder must not leak into the CustomHost
    # exe either. If you configure your own default host in
    # MangoClientSetup.cs (standard branch), add it to the list above so
    # this guard catches it too.
    Write-Host "CustomHost OK: exe khong chua host/ten rieng ca nhan."
}

# --- 3. Kiem chung: SHA-256 + kich thuoc ---
$hash = (Get-FileHash $exeOut -Algorithm SHA256).Hash
$sizeMB = (Get-Item $exeOut).Length / 1MB
Write-Host ""
Write-Host "BUILD_DONE"
Write-Host "Exe : $exeOut ($( '{0:N1} MB' -f $sizeMB ))"
Write-Host "SHA-256: $hash"
Write-Host "Goi client zip giu lai tai: $clientZip"
if ($CustomHost) {
    Write-Host "Ban CustomHost: gui file exe nay cho may con, nhap Server host/cong + tai khoan + mat khau roi bam Cai dat - may se enroll vao dung Server da nhap."
} else {
    Write-Host "Gui file exe nay cho may con, nhap tai khoan + mat khau roi bam Cai dat - may se hien pending tren dashboard."
}
Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue

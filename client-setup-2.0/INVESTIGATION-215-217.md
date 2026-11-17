# Dieu tra goc loi cai Mango Client 2.1.5 / 2.1.6 / 2.1.7 (bao ma loi 1)
Ngay: 17/11/2026 ~15:30-16:00 +07. Dieu tra vien (subagent). KHONG sua/build gi.

## KET LUAN DUT DIEM — NGUYEN NHAN MA LOI 1 (17/11/2026, tu log PC2)
- Log: `C:\Windows\Temp\MangoClient-install.log` + `C:\Temp\test215\stdout.log` /
  `stderr.log` / `exitcode.txt`, ghi 15:39:43-44 +07. PC2 da online lai, log da doc.
- Exit code: **1**.
- Tien trinh: buoc 1/8 (Python OK), 2/8 (tat 2 process client, xoa Task MangoClient),
  3/8 (copy code OK), CHET o buoc **3b/8**.
- Loi nguyen van: `Copy-Item : Cannot overwrite the item C:\MangoClient\bin\agent-desktop.exe with itself.`
  (install_client.ps1:473). Do `$ErrorActionPreference = "Stop"` nen thanh
  TerminatingError, script dung, exit 1.
- Lenh chay: `powershell -NoProfile -ExecutionPolicy Bypass -File C:\Temp\test215\ClientSrc\install_client.ps1 -MangoMCPDir C:\MangoClient -ClientSrc C:\Temp\test215\ClientSrc -GuiUser admin`,
  chay bang SYSTEM, PowerShell 5.1.
- Nguyen nhan that: buoc 3b copy agent-desktop.exe bi **TU DE LEN CHINH NO** khi
  `-MangoMCPDir` tro vao `C:\MangoClient` ma `C:\MangoClient\bin\agent-desktop.exe`
  da co san tu ban cai truoc (cai de len 2.1.4 tro len). Giai thich duoc vi sao 2.1.4
  cai duoc (cai de len cac ban chua co thu muc bin) con 2.1.5/2.1.6/2.1.7 cai loi
  (cai de len 2.1.4 da co bin). Cung bay tu copy nhu install.ps1 cua MangoMCP
  tren may WIN-DUIEFS1F4BG.
- **`\r\r\n` KHONG phai nguyen nhan gay ma loi 1**: script parse va chay tot qua het
  buoc 1-3, Parser bao 0 loi. Hoi quy gap doi CR van co that trong exe 2.1.5-2.1.7,
  nhung no khong gay loi nay — guard encoding trong build script van giu nguyen
  gia tri phong ngua.
- FIX (2.1.8, install_client.ps1 buoc 3b): truoc moi Copy-Item cua agent-desktop.exe
  va MangoOverlay.exe, resolve nguon + dich ve duong dan tuyet doi
  (`[System.IO.Path]::GetFullPath`) va so sanh khong phan biet hoa/thuong (`-ieq`);
  neu TRUNG thi BO QUA kem thong bao da co san; neu KHAC ma copy loi thi van fail
  ro rang. Khong dung `-ErrorAction SilentlyContinue` mu.

## Ket luan tom tat
- CO HOI QUY (regression) DUOC CHUNG MINH: `install_client.ps1` nhung trong exe 2.1.5/2.1.6/2.1.7
  co xuong dong `\r\r\n` (CR gap doi: CR=940, LF=470) trong khi ban 2.1.4 la CRLF sach
  (CR=470, LF=470). Day la thay doi duy nhat o tang script cai dat (ngoai 3 dong so version).
- CHUA CHUNG MINH DUOC `\r\r\n` la nguyen nhan gay ma loi 1: Parser::ParseFile() bao 0 loi
  o ca 4 ban; PowerShell chiu duoc `\r\r\n` khi tokenize. Can log cai dat that de ket luan.
- THU CAI THAT TREN PC2 (2.1.5, script byte-exact, dung tham so launcher): TAI HIEN DUOC LOI —
  installer tat client 2.1.7 dang chay + xoa Task MangoClient (buoc 2) roi KHONG BAO GIO
  xong trong 20+ phut; PC2 offline tu 15:39:33 +07, khong khoi phuc duoc tu xa.
  Loi chinh xac (nguyen van) CHUA DOC DUOC — nam trong log tren dia PC2.

## Bang bang chung (trich tu exe tren Desktop/build-dir PC1)

| Ban | Exe SHA-256 (dau) | install_client.ps1 nhung | BOM | CR | LF | Parse errors |
|---|---|---|---|---|---|---|
| 2.1.4 | 535A0FAB… (Desktop = build-dir) | len 26390, SHA FC5EE4A9… | Co | 470 | 470 | 0 |
| 2.1.5 Desktop (04:32) | 5927208A… | len 26860, SHA 15C3E859… | Co | 940 | 470 | 0 |
| 2.1.5 build-dir (04:39) | B55D6ABA… | len 26860, SHA 238C2530… | Co | 940 | 470 | 0 |
| 2.1.6 | 57680327… (Desktop = build-dir) | len 26860, SHA 238C2530… | Co | 940 | 470 | 0 |
| 2.1.7 | E54558AA… (Desktop = build-dir) | len 26860, SHA 06973F0A… | Co | 940 | 470 | 0 |

- 26860 - 26390 = 470 = dung so CR thua. File repo hien tai (26390 byte, CRLF sach,
  SHA 66193DA7…) = noi dung script 2.1.7 TRU 470 CR thua (da kiem chung: tai tao 2.1.5
  tu ban sach bang replace version + gap doi CR cho ra dung SHA 15C3E859…).
- Diff script giua cac ban: 2.1.5-Desktop vs 2.1.5-build = chi 3 dong so version
  (2.1.5->2.1.6); 2.1.5-build vs 2.1.7 = chi 3 dong so version (2.1.6->2.1.7)
  (dong 1, `$clientVersion`, dong Write-Host XONG). Noi dung logic giong nhau.
- Zip MangoClient nhung: 2.1.6 byte-identical voi 2.1.5 build-dir (SHA 052E1170…);
  exe 2.1.5 build-dir that ra nhung script 2.1.6 (build nham nhan); co 2 exe 2.1.5 khac
  nhau (Desktop 04:32 vs build-dir 04:39).
- Zip MangoClient 2.1.5-Desktop vs 2.1.7: chi 5/30 file khac (gui_agent.py,
  install_client.ps1, mangoclient/__init__.py, mangoengine/core.py +4239 byte,
  mangoengine/server_tools.py).
- Goi MangoMCPFull.zip nhung: byte-identical o 2.1.4 va 2.1.7 (SHA BFFDE753…, 2546
  entries; python.exe/pythonw.exe, bin/agent-desktop.exe, app/MangoOverlay.exe deu co).
- build_client_setup.ps1 va MangoClientSetup.cs tren PC1 giong het repo (sau khi chuan
  hoa CR) — khau build KHONG tu xu ly lai encoding; file .ps1 da bi gap doi CR tu
  TRUOC khi build, giua build 2.1.4 (03:39) va build 2.1.5 (04:32) ngay 16/11.
  Co che dung nhu loi cu: thay `\n` -> `\r\n` tren file von da CRLF (vd write/sync
  khong giu BOM/CRLF).

## Thu cai tren may test
- Chuan bi: backup C:\MangoClient -> C:\Temp\backup217 (tren PC2), backup
  server-client.json -> C:\Temp\test215\server-client.json.bak.
  ClientSrc = code 2.1.7 cua PC2 + script 2.1.5 byte-exact (SHA 15C3E859… da verify).
- Lenh chay (SYSTEM, qua machine_call, giong launcher C#):
  `powershell -NoProfile -ExecutionPolicy Bypass -File C:\Temp\test215\ClientSrc\install_client.ps1 -MangoMCPDir C:\MangoClient -ClientSrc C:\Temp\test215\ClientSrc -GuiUser admin`
  (khong truyen mat khau — nhanh password cua script CHUA duoc thu).
- Ket qua: client chet o buoc 2 (last heartbeat 15:39:33 +07). Installer CHET o buoc
  3b/8 luc 15:39:43-44 voi exit code 1 — xem muc KET LUAN DUT DIEM o dau file
  (loi Copy-Item tu de agent-desktop.exe). PC2 da online lai sau do, log da doc.
- DA KET LUAN DUT DIEM (17/11, tu log): xem muc KET LUAN DUT DIEM o dau file.
  Nguyen nhan la Copy-Item tu de o buoc 3b/8, KHONG phai `\r\r\n`, KHONG phai treo
  o buoc 4b `pip install certifi`. Doan mo cu ben duoi chi con gia tri lich su.
- Do lech so voi chay Setup.exe that: chay bang SYSTEM (khong phai admin dang nhap);
  -MangoMCPDir tro toi C:\MangoClient thay vi goi Full giai nen (tuong duong tren PC2
  vi da co python san; may moi tinh khong co python se di nhanh khac); khong co mat
  khau; ClientSrc dung code 2.1.7 (4 file code khac 2.1.5 nhung khong anh huong flow cai).

## Trang thai ban giao — PC2 DA ONLINE LAI, LOG DA DOC, FIX DA VAO 2.1.8 (17/11)
- PC2 online lai (theo coordinator 17/11 ~17:31); log loi 2.1.5 da doc xong
  (xem muc KET LUAN DUT DIEM o dau file). Khong can doc lai log PC2 nua.
- Fix 3b (skip khi nguon trung dich) da vao install_client.ps1 ban 2.1.8.
  Test cai de len client dang chay se lam o vong sau tren PC3 — KHONG thu o day.
- Khoi phuc PC2 (neu can): chay lai install_client.ps1 ban 2.1.7 sach tu
  C:\Temp\backup217 (ban sach CRLF, SHA 66193DA7…) hoac cai lai 2.1.7; kiem tra
  `Get-ScheduledTask -TaskName MangoClient`, neu mat thi dang ky lai.
- Luu y: C:\Temp\test215\server-client.json.bak va C:\Temp\backup217 nam tren PC2,
  chua secret — khong copy ra ngoai.

## Blocker phu phat sinh trong luc dieu tra
- Duong MangoMCP toi may test CHET tu ~15:50 +07 (curl HTTP 000; moi goi MangoMCP
  client.py deu timeout "MCP request did not complete"). Trong khi tunnel-pc1 tra 200
  va client 1.1.5 cua PC1 van heartbeat binh thuong len Server — loi o endpoint/tunnel
  MangoMCP 8766 tren PC1, can kiem tra cloudflared tren PC1. Vi vay 2 muc phu chua xong:
  diff noi dung gui_agent.py / __init__.py / server_tools.py (2.1.5 vs 2.1.7) va SHA
  cua cac zip MangoClient-2.1.5/2.1.6.zip trong build-dir. machine_call toi PC1 (1.1.5)
  treo >4 phut, da kill.
- Khong co buoc nao bi chan an toan (safety block). Khong ghi secret/token/mat khau nao
  vao bao cao nay.

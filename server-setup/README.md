# Mango Server 1.2.1 — Setup.exe

File cai dat duy nhat cho may Windows moi: copy 1 file
`MangoServer-Setup-1.2.1.exe` sang may do, nhap cong + thu muc data +
mat khau quan tri, bam **Cai dat**. Server tu chay lai sau khi may khoi
dong (Scheduled Task `MangoServer`, SYSTEM, luc khoi dong) ma **khong
can ai dang nhap** — khong dung shortcut Startup.

## File trong thu muc nay

| File | De lam gi |
|---|---|
| `MangoServerSetup.cs` | GUI cai dat + che do silent (`/SILENT /PORT:.. /DATADIR:.. /ADMINPASSWORD:..`) |
| `build_server_setup.ps1` | Build exe tren Windows (can csc.exe + goi MangoMCP Full) |
| `install_server.ps1` | Script cai that (chay trong exe): runtime, code, mat khau, Task, Uninstall |
| `uninstall_server.ps1` | Go bo (giu data mac dinh, them `-RemoveData` moi xoa data) |
| `set_admin.py` | Dat mat khau quan tri + tao token Agent (khong tuong tac) |
| `app.manifest` | Yeu cau quyen Admin cho exe |

## Build (tren máy client)

Mo PowerShell tai thu muc `server-setup` cua repo:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_server_setup.ps1
```

Ket qua: `MangoServer-Setup-1.2.1.exe` (+ SHA-256 in ra) va
`MangoServer-1.2.1.zip` (goi server giu lai). Copy exe len Desktop máy client.

## Chế độ silent + debug (1.2.1)

```powershell
MangoServer-Setup-1.2.1.exe /SILENT /PORT:8443 /DATADIR:C:\MangoMCPServer\data /ADMINPASSWORD:<mat-khau>
```

Thiếu `/ADMINPASSWORD` thì sinh mật khẩu ngẫu nhiên và ghi vào
`%TEMP%\MangoServer-install-creds.txt` (cùng token Agent nếu có).

### Gỡ lỗi chế độ silent

Lỗi silent thoát mã 1 ở bản 1.2.0 đã được sửa ở bản 1.2.1 (nguyên nhân: tên
biến trong script cài đặt trùng với biến hệ thống của PowerShell). Nếu chế
độ silent vẫn lỗi ở bản mới, `MangoServerSetup.cs` ghi **log debug từng bước**
ra `%TEMP%\MangoServer-silent-debug.txt`:
tham số đã parse (chỉ ghi "đã nhập / sinh ngẫu nhiên", **không ghi giá
trị mật khẩu**), thư mục tạm, từng lần giải nén resource (tên resource +
số entries), đường dẫn `install_server.ps1` + có tồn tại không, mã thoát
của ps1, log tail khi lỗi, và `ex.ToString()` đầy đủ nếu có exception.
`InstallerCore.ExtractResource` còn ghi luôn danh sách resource thật có
trong exe khi `GetManifestResourceStream` trả null. Log này cũng được ghi
khi chạy GUI (dùng chung `InstallerCore`), cùng 1 file.

**Khi silent lỗi: gửi về cả 3 file** — `MangoServer-silent-debug.txt`,
`MangoServer-install-error.txt` (nếu có), `MangoServer-install.log`
(transcript của ps1, nếu có). Dòng cuối của debug log cho biết dừng ở
bước nào.

Ghi chú kỹ thuật: mật khẩu truyền qua biến môi trường
`MANGO_ADMIN_PASSWORD` của tiến trình con, không nằm trên dòng lệnh;
file creds (chứa token Agent nếu có) chỉ ghi khi mã thoát = 0.

## Cai tren may moi (quan tri vien / nguoi cai)

1. Copy `MangoServer-Setup-1.2.1.exe` sang may moi, nhap dup (bam Yes
   neu hoi quyen Admin).
2. Nhap **Cong** (mac dinh 8443), **Thu muc data** (mac dinh
   `C:\MangoMCPServer\data`), **Mat khau quan tri** (2 lan; de trong
   thi tu sinh ngau nhien va hien 1 lan — nho luu lai).
3. Bam **Cai dat**, doi chay xong. Ghi lai **mat khau quan tri** va
   **token Agent** (hien 1 lan duy nhat sau khi cai xong).
4. Mo `http://127.0.0.1:8443/dashboard` tren may do, dang nhap, vao tab
   **Ma dang ky** de lay ma cho may con.

## De may con o xa noi duoc (can lam them sau khi cai)

- **Cloudflare Tunnel** (cach khuyen nghi): tro tunnel ve
  `http://127.0.0.1:8443` tren may Server moi, lay hostname https
  (vd `https://your-server.example.com`). May con dung hostname nay.
- Hoac **mo cong** 8443 tren router/tuong lua cua may Server va cho may
  con dia chi `http://<IP-may-Server>:8443` (khong co TLS).
- **Khong** mo cong 8443 ra internet tran ma khong co tunnel/xac thuc —
  dashboard co mat khau quan tri nhung MCP/WebSocket can token rieng.

## Cai lai / nang cap tai cho

Chay lai Setup.exe tren may da cai: code moi se de len
`C:\MangoMCPServer\server\`, **giu nguyen** thu muc data (may da enroll,
token, nhat ky van con), backup data 1 ban truoc khi thay code. Mat khau
quan tri cu duoc giu (mat khau nhap luc cai lai khong ghi de).

## Go bo

Windows Uninstall (Cai dat > Ung dung) > **Mango Server** > Go cai dat,
hoac chay `C:\MangoMCPServer\server\uninstall_server.ps1` bang quyen
Admin. Mac dinh giu lai `C:\MangoMCPServer\data\`.

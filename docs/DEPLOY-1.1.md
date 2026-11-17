# Deploy Mango Server 1.1 — hướng dẫn từng bước (làm trong live chat)

Tài liệu này để **người khác làm trong live chat** — mỗi bước có lệnh cụ thể,
điểm kiểm chứng, và cách quay lại nếu sai. Đọc hết 1 lượt trước khi làm.

Quy ước đường dẫn:

| Nơi | Đường dẫn |
|---|---|
| Máy ảo (Server) | `C:\MangoMCPServer\` — code `server\`, dữ liệu `data\`, Python `C:\MangoMCP\python\python.exe` |
| máy client | `C:\MangoMCP\server-client\` — cấu hình `C:\MangoMCP\server-client.json` |
| Máy build (Linux, repo này) | `~/workspace/mango-server/` |
| Backup 1.0 | `~/workspace/mango-server-1.0-backup/` (code 1.0 nguyên vẹn: `server/`, `client/`, `tests/`) |

Server public: `https://your-server.example.com` (tunnel trỏ về
`http://localhost:8443` trên máy chủ).
Dashboard: `https://your-server.example.com/dashboard`.

## 0. Thứ tự chung (đừng làm ngược)

1. **Server 1.1 lên máy ảo trước** (mục a).
2. **Client 1.1 lên máy client sau** (mục b) — client 1.1 không hiểu Server 1.0
   (Server 1.0 không hiểu message mới của client 1.1), nhưng client 1.0 vẫn
   nối được Server 1.1, nên nâng Server trước là an toàn.
3. Máy mới bằng exe (mục c) và nâng cấp từ xa (mục d) chỉ làm **sau khi**
   2 bước trên đã kiểm chứng xong.

Làm lúc máy chủ đang chạy để kiểm chứng ngay — Server 1.0
hiện chạy foreground detached, **không có Scheduled Task tự chạy lại**,
máy ảo khởi động lại là Server chết (xem mục e).

Chuẩn bị trước: trên máy build, chạy test 1.1 cho pass hết
(`.venv/bin/python tests/run_tests.py`) rồi mới mang code đi deploy.

---

## (a) Server 1.1 lên máy ảo

### a.1 Backup dữ liệu trên máy ảo

Trên máy ảo, mở PowerShell (quyền thường là đủ — chỉ copy file):

```powershell
# Backup data (registry/auth/audit) — dat ten theo ngay, vi du 2026-01-15
Copy-Item -Recurse "C:\MangoMCPServer\data" "C:\MangoMCPServer\data-backup-2026-01-15"
# Backup code Server 1.0 dang chay (de rollback nhanh, xem muc e)
Copy-Item -Recurse "C:\MangoMCPServer\server" "C:\MangoMCPServer\server-1.0-backup"
Get-ChildItem "C:\MangoMCPServer\data-backup-2026-01-15" | Select-Object Name
```

Kiểm chứng: thư mục backup có `registry.json`, `auth.json`, `audit.jsonl`.
**Không có backup thì dừng lại, đừng làm tiếp.**

### a.2 Dừng Server 1.0

Server đang chạy foreground detached — tìm tiến trình Python đang chạy
`run_server.py` rồi dừng (đừng tắt cả MangoMCP trên máy ảo):

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match "run_server.py" } |
  Select-Object ProcessId, CommandLine
# Dung dung ProcessId vua thay (thay <PID> bang so that):
Stop-Process -Id <PID>
Start-Sleep -Seconds 3
```

Kiểm chứng: `https://your-server.example.com/health` không trả lời nữa
(trình duyệt báo không nối được — đúng, Server đã dừng).

### a.3 Thay thư mục `server/` bằng code 1.1, giữ nguyên `data/`

Copy thư mục `server/` trong repo này (đã có code 1.1) lên máy ảo, đè lên
`C:\MangoMCPServer\server\`. Dùng cách nào tiện (Shell Tunnel / SFTP qua
`tunnel của máy client`... — trên máy ảo dùng cách đã dùng khi deploy 1.0; đừng xóa
thư mục `data\`).

```powershell
# Sau khi copy xong, tren may ao kiem tra:
Get-ChildItem "C:\MangoMCPServer\server" | Select-Object Name
Get-ChildItem "C:\MangoMCPServer\data"   | Select-Object Name
# Phai thay: server\mangoserver\dashboard.py (co tab Cau hinh),
# server\mangoserver\packages.py, server\run_server.py (ban 1.1).
# Phai con nguyen: data\registry.json, data\auth.json, data\audit.jsonl.
```

Tương thích dữ liệu: `data/` cũ dùng được luôn — field mới của máy
(`client_version`, `reported_tools`, `desired_scope`, `target_version`,
`upgrade_status`) mặc định rỗng/null; `auth.json` tự thêm `settings`
(`enrollment_ttl_seconds`) khi lưu lần đầu. **Không sửa tay file trong
`data\`.**

### a.4 Khởi động lại Server 1.1

```bat
cd C:\MangoMCPServer\server
C:\MangoMCP\python\python.exe run_server.py start --data-dir C:\MangoMCPServer\data --host 127.0.0.1 --port 8443
```

Để cửa sổ đó chạy (foreground) — đừng đóng. Nếu cần chạy nền thì dùng
`Start-Process` detached như cách đang chạy 1.0 trên máy ảo.

### a.5 Kiểm chứng Server 1.1

Làm theo thứ tự, thiếu 1 điểm thì dừng lại sửa rồi kiểm chứng lại:

1. **Health:** mở `https://your-server.example.com/health` — phải trả:
   `{"status": "ok", "version": "1.1.0", "server": "Mango Server"}`.
   Nếu `version` vẫn `1.0.0` là code chưa được thay — quay lại a.3.
2. **Dashboard 200:** mở `https://your-server.example.com/dashboard` —
   phải hiện trang đăng nhập (200, không phải 502/404).
3. **Tab Cấu hình:** đăng nhập bằng mật khẩu quản trị Server → phải thấy
   tab thứ 6 **Cấu hình** (sau tab Trạng thái): hiện version 1.1.0, cổng
   8443, thư mục data, uptime, số máy, hạn mã đăng ký, form đổi mật khẩu.
4. **MCP không token trả 401:** (xem `docs/CONNECT-AGENTS.md` mục 6)
   `POST /mcp` không kèm token phải trả `401` — nếu trả khác thì dừng lại.
5. **Máy cũ còn nguyên:** tab Máy vẫn thấy máy client (approved; có thể offline
   trong lúc client 1.0 chưa lên lại — bình thường, sẽ online sau mục b).

Xong mục (a) mới làm mục (b).

---

## (b) Client 1.1 lên máy client

máy client hiện tại: đã enroll (`machine_id` `<machine-id>`), approved,
online; client 1.0 chạy bằng Scheduled Task `MangoServerClient`
(`run_client_log.bat`); Python portable đã có `websockets` 17.4.

### b.1 Dừng client 1.0 trên máy client

```powershell
Stop-ScheduledTask -TaskName "MangoServerClient" -ErrorAction SilentlyContinue
# Dung tien trinh client dang chay (neu co) — chi dung python chay run_client.py,
# dung tat ca python.exe tren may:
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match "run_client.py" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId }
```

### b.2 Thay code client, giữ nguyên `server-client.json`

```powershell
# Backup client 1.0 cu truoc khi thay (de rollback)
Copy-Item -Recurse "C:\MangoMCP\server-client" "C:\MangoMCP\server-client-1.0-backup"
# Copy code client 1.1 (thu muc client/ trong repo) de len:
#   C:\MangoMCP\server-client\
# GIU NGUYEN file C:\MangoMCP\server-client.json — KHONG copy de, KHONG sua tay.
# (File nay da co machine_id/secret + server_host dung your-server.example.com.)
Get-ChildItem "C:\MangoMCP\server-client" | Select-Object Name
Get-Content "C:\MangoMCP\server-client.json" | Select-String "server_host|machine_id"
```

Kiểm chứng: `server_host` trong `server-client.json` phải là
`your-server.example.com` (không phải host cũ của MangoMCP local — bẫy cũ trong
code 1.0). Nếu sai thì sửa **chỉ** `server_host` trong file đó, giữ nguyên
`machine_id` / `machine_secret` / `server_allowed_tools`.

### b.3 Khởi động lại Task `MangoServerClient`

```powershell
Start-ScheduledTask -TaskName "MangoServerClient"
Start-Sleep -Seconds 15
Get-Content "C:\MangoMCP\server-client\client.log" -Tail 30
```

### b.4 Kiểm chứng client 1.1

1. **`client.log` không lỗi:** thấy dòng client khởi động, nối Server,
   heartbeat chạy; không thấy `Enroll that bai`, `THIEU Bearer`, traceback.
2. **Dashboard thấy máy client báo `client_version 1.1.0`:** tab Máy → bấm vào máy client
   → hiện 2 cột version (Client `1.1.0` / MangoMCP local `0.14.2`) và
   `reported_tools` (34 tool mặc định).
3. **`machine_call` vẫn chạy:** từ dashboard (gửi 1 lệnh thử, vd
   `mango_status`) hoặc qua MCP `machine_call` — phải trả đúng kết quả máy client.
   Nếu `machine_call` lỗi `MACHINE_OFFLINE` thì xem lại `client.log` trên máy client.
4. **Task tự chạy lại:** đăng xuất rồi đăng nhập lại máy client (hoặc khởi động
   lại máy client) → Task `MangoServerClient` tự chạy, máy client lại online
   trên dashboard mà không cần làm gì thêm.

Xong mục (b) mới làm mục (c) và (d).

---

## (c) Máy mới bằng MangoClient-Setup exe

Dùng khi thêm máy con mới (chưa có MangoMCP hoặc đã có — exe lo cả 2).

1. Trên máy build (Windows), build exe theo `client-setup/README.md` mục 1:
   `build_client_setup.ps1` → lấy `MangoClient-Setup-1.1.0.exe` + SHA-256.
2. Copy exe sang máy con, nhấp đúp (bấm Yes nếu hỏi quyền Admin).
3. Nhập **Địa chỉ Server** (mặc định `https://your-server.example.com`) và
   **Tên máy** (mặc định tên Windows — đặt sao cho Quản trị viên nhận ra máy nào),
   bấm **Cài đặt**.
4. Đợi script chạy xong (in rõ từng bước trong cửa sổ PowerShell).
   Lỗi thường gặp xem `client-setup/README.md` mục 5.
5. Vào dashboard (tab **Máy**): máy mới hiện ở trạng thái **chờ duyệt
   (pending)**. Quản trị viên bấm **Duyệt** → máy online, điều khiển được ngay.
6. Kiểm chứng: `machine_list` qua MCP thấy máy mới; `machine_status` trả
   `client_version 1.1.0`.

Máy lạ xin enroll cũng chỉ ở pending — thấy máy lạ thì bấm Từ chối / Xóa,
không duyệt.

---

## (d) Nâng cấp từ xa (đẩy client mới xuống máy đã nối)

Chỉ làm sau khi Server 1.1 + client 1.1 đã chạy ổn (mục a, b).

### d.1 Đăng gói client mới lên Server

1. Trên máy build, đóng gói client mới thành zip (vd `MangoClient-1.2.0.zip`
   — build bằng `build_client_setup.ps1` rồi lấy file zip nó xuất ra, hoặc
   zip tay thư mục `client/` + `install_client.ps1` + `portable_client.ps1`,
   loại `__pycache__`).
2. Dashboard → tab **Cấu hình** → mục **Gói Client** → form upload:
   chọn file zip, nhập `version` (vd `1.2.0`), `requires_restart`
   (`true` chỉ khi bản đó bắt buộc khởi động lại máy), ghi chú → Upload.
   (Hoặc gọi API `POST /api/packages` multipart với session quản trị.)
3. Kiểm chứng: danh sách gói hiện bản mới kèm SHA-256 + dung lượng.
   Giới hạn file ≤ 200MB; tên file không chứa `..` / `/` / `\`.

### d.2 Chọn máy, bấm Nâng cấp, theo dõi

1. Dashboard → tab **Máy** → bấm vào máy cần nâng cấp → nút **Nâng cấp** →
   chọn bản đích (mặc định bản mới nhất) → xác nhận.
2. Server lưu `target_version` cho máy, gửi lệnh qua WebSocket ngay nếu máy
   online; máy offline thì nhận lệnh lúc nối lại (qua `heartbeat_ack`).
3. Theo dõi trong chi tiết máy: `upgrade_status` chạy
   `downloading` → `applying` → `done`; heartbeat sau đó báo
   `client_version` mới, Server tự xóa `target_version`.
4. Nếu `upgrade_status` = `failed`: xem `client.log` trên máy con (thường
   do tải lỗi hoặc SHA-256 không khớp — máy giữ nguyên bản cũ, an toàn).
   Sửa nguyên nhân rồi bấm Nâng cấp lại.
5. Nếu gói có `requires_restart=true`: máy tự khởi động lại sau khi áp
   dụng xong (Windows: `shutdown /r /t 60`) — báo trước cho người ngồi
   trước máy đó.

Lưu ý: **chưa có nút "nâng cấp tất cả"** — nâng cấp từng máy một.
Không xóa gói đang là `target_version` của máy nào (Server trả `409`).

---

## (e) Thứ tự khởi động lại và rollback về 1.0

### Thứ tự khởi động lại (khi cần restart)

1. **Server trước, client sau.** Server 1.1 chạy rồi mới nâng client 1.1.
2. Khởi động lại Server: dừng tiến trình cũ (a.2) → chạy lại lệnh ở a.4.
   Client đang nối sẽ tự nối lại (backoff 5/10/30/60s) — không cần đụng máy client.
3. Khởi động lại client trên 1 máy: `Restart-ScheduledTask -TaskName
   "MangoServerClient"` (hoặc chạy lại `C:\MangoMCP\server-client\run_client_log.bat`).
4. Khởi động lại cả máy con từ dashboard: tab Máy → máy đó →
   **Khởi động lại máy** (hoặc MCP tool `machine_restart`) — máy tự
   `shutdown /r /t 60`, không hỏi người ngồi trước máy.
5. **Rào cản đã biết, chưa sửa trong 1.1:** Server trên máy ảo vẫn chạy
   foreground, không có Scheduled Task; máy ảo **không tự đăng nhập**
   (`AutoAdminLogon = 0`) nên VM restart là Server chết. Sau mỗi lần VM
   restart phải chạy lại Server tay (lệnh a.4) rồi kiểm chứng a.5. Muốn sửa
   hẳn thì Quản trị viên cần 1 việc tay: tự tạo Task trong Task Scheduler GUI (trigger
   At startup, action `C:\MangoMCPServer\start_server.bat`, "Run whether
   user is logged on or not", quyền cao nhất) hoặc bật auto-logon cho user
   `mcpserver` — rồi kiểm chứng bằng 1 lần VM restart thật.

### Rollback về 1.0 (khi 1.1 lỗi nặng)

**Rollback Server trên máy ảo:**

```powershell
# 1. Dung Server 1.1 (lay PID nhu muc a.2)
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match "run_server.py" } |
  Select-Object ProcessId, CommandLine
Stop-Process -Id <PID>

# 2. Tra lai code 1.0 (lay tu backup tren may ao, hoac copy tu
#    ~/workspace/mango-server-1.0-backup/server/ tren may build)
Remove-Item -Recurse -Force "C:\MangoMCPServer\server"
Copy-Item -Recurse "C:\MangoMCPServer\server-1.0-backup" "C:\MangoMCPServer\server"
# GIU NGUYEN C:\MangoMCPServer\data\ — data 1.1 tuong thich nguoc (field moi
# chi la them, Server 1.0 bo qua; khong can phuc hoi data cu tru khi data hong).

# 3. Chay lai Server 1.0
cd C:\MangoMCPServer\server
C:\MangoMCP\python\python.exe run_server.py start --data-dir C:\MangoMCPServer\data --host 127.0.0.1 --port 8443

# 4. Kiem chung: /health tra version 1.0.0, dashboard 200, máy client online lai.
```

**Rollback client trên máy client:**

```powershell
Stop-ScheduledTask -TaskName "MangoServerClient" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "C:\MangoMCP\server-client"
Copy-Item -Recurse "C:\MangoMCP\server-client-1.0-backup" "C:\MangoMCP\server-client"
# server-client.json GIU NGUYEN (khong nam trong thu muc client) — may van enroll cu.
Start-ScheduledTask -TaskName "MangoServerClient"
# Kiem chung: client.log khong loi, dashboard thay máy client online (client_version trong lai).
```

**Rollback máy mới đã cài bằng exe:** gỡ theo `client-setup/README.md`
mục 3 (xóa Task + thư mục client + `server-client.json`), rồi xóa máy khỏi
dashboard. MangoMCP trên máy đó **giữ nguyên** nếu máy đã có sẵn từ trước.

Sau rollback, báo lại quản trị viên: đã về 1.0, lỗi 1.1 gặp là gì, log nào giữ lại
để sửa (giữ `data-backup-2026-01-15` và `server-1.0-backup` đừng xóa vội).

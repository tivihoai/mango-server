# Mango Client 2.0 — Thiết kế gộp sâu (Deep Merge)

> **Trạng thái:** Quản trị viên đã chốt 6 quyết định. Tài liệu này là thiết kế để triển khai.
> **Bản đồ code gốc:** `MERGE-MAP-2.0.md` (lập bản đồ MangoMCP 0.14.2, đủ 100 tool).
> **Mục tiêu:** MỘT chương trình duy nhất — Mango Client 2.0 — chạy ngầm, chứa toàn bộ engine MangoMCP bên trong, không còn MangoMCP Core/Agent/Config GUI riêng, không còn gọi HTTP qua `localhost:8766`. Mọi tính năng cập nhật + điều khiển bởi MangoServer.

---

## 1. Sáu quyết định đã chốt

| # | Quyết định | Nội dung chốt |
|---|---|---|
| 1 | MCP local 8766 | **Bỏ.** Mango Server là đường duy nhất cho AI vào máy. Hệ quả: nếu Server chết thì không còn đường MCP dự phòng; chỉ còn SSH tunnel (giữ lại). |
| 2 | Mật khẩu chủ | **Bỏ.** Không còn MCP local / GUI để xác thực. Chỉ giữ **mật khẩu khóa máy** (riêng biệt, để mở khóa tại máy). |
| 3 | Auto-logon | **Bắt buộc bật.** Sau khi gộp, máy chỉ online sau khi có người đăng nhập. Cần mật khẩu thật cho tài khoản Windows (mật khẩu trống đã chứng minh không chạy, 8/11). |
| 4 | Nơi đặt code + Python | Code mới ở **`C:\MangoClient\`**. Dùng chung Python portable đã có sẵn ở `C:\MangoMCP\python` (đủ package). Không copy Python riêng. |
| 5 | Kênh quản trị cấu hình từ Server | **Tool mới** gọi qua `machine_call` như tool thường (tạo/xoay/xóa client tunnel, đặt cổng quyền, allowlist, lock, tunnel). Không làm API dashboard riêng. |
| 6 | Tên + phiên bản | **Mango Client 2.0**. Bỏ tên "MangoMCP" khỏi giao diện người dùng (chỉ còn trong log/code nội bộ nếu cần). |

**Hai yêu cầu bổ sung — đã đưa vào thiết kế:**
- **Cài đặt không nhập gì cả:** chỉ bấm Cài đặt là xong. Server URL mặc định có sẵn trong file cài; tên máy tự lấy từ tên máy Windows; chứng chỉ tự sinh lúc enroll; client tự nối Server. Bước duy nhất còn lại là Quản trị viên duyệt máy mới trên dashboard.
- **Có phần gỡ bỏ trong máy:** đăng ký Windows Uninstall + script gỡ (force-quit client, xóa Task, xóa file/config, xóa registry).

---

## 2. Kiến trúc tổng thể Client 2.0

```
  Mango Server (https://your-server.example.com, cổng 8443)
        │  WebSocket (wss) — heartbeat 30s, machine_call, admin, upgrade
        ▼
  ┌─────────────────────────────────────────────────────────┐
  │  Mango Client 2.0 — MỘT process Python duy nhất         │
  │  Chạy bằng Scheduled Task lúc user logon, highest priv.  │
  │                                                         │
  │  ServerLink (giữ nguyên từ 1.1.5)                        │
  │   - WebSocket, heartbeat, enroll, upgrade, restart      │
  │   - execute_call(tool, args): kiểm tra allowed_tools    │
  │     rồi gọi DirectEngine.call_tool(tool, args)          │
  │                                                         │
  │  DirectEngine (MỚI — thay LocalMcpClient)                │
  │   - Cùng phương thức call_tool(name, args)               │
  │   - Tra bảng dispatch (tái dùng agent.build_dispatch_table,│
  │     mở rộng cho cả 100 tool) → gọi thẳng hàm core/desktop│
  │   - Giữ kiểm tra core.require() (cổng quyền) + chặn khi  │
  │     khóa tạm ngưng (_check_lock_pause/_check_lock_capture)│
  │   - Lock tuần tự quanh execute_call (nhóm control)       │
  │                                                         │
  │  Engine (gộp từ mangomcp/*, giữ nguyên code)             │
  │   - backend.py, core.py (100 tool), desktop.py, uia.py  │
  │   - lock.py (luồng riêng + message pump), overlay.py    │
  │   - tunnel.py (Shell Tunnel SSH/SFTP, luồng + loop riêng)│
  │   - config.py (rút gọn), audit.py, errors.py, users.py  │
  │   - autologon.py                                        │
  │                                                         │
  │  BỎ: server.py (FastMCP/uvicorn), agent.py, ipc.py,     │
  │       session.launch_agent, MangoMCPConfig.cs (GUI),    │
  │       mango_mcp_server.py, mango_mcp_agent.py           │
  └─────────────────────────────────────────────────────────┘
        │  Shell Tunnel SSH/SFTP 127.0.0.1:8768 (giữ lại)
        │  — đường dự phòng trực tiếp cho Mango (khi Server chết)
        ▼
  Mango (truy cập trực tiếp qua Cloudflare tunnel)
```

**Điểm nối duy nhất thay đổi:** `ServerLink.__init__(config, local)` nhận `local` là đối tượng có `call_tool(name, args)`. Client 1.1.5 truyền `LocalMcpClient` (HTTP tới 127.0.0.1:8766). Client 2.0 truyền `DirectEngine` (gọi hàm trong process). Phần WebSocket / heartbeat / enroll / upgrade / restart của `ServerLink` **giữ nguyên**.

**Chạy ở user session, không cần SYSTEM:** toàn bộ tool (kể cả `run_command`, `powershell`, `registry_set`, lock, tunnel) chạy bằng user đang đăng nhập (admin, Task highest privileges). Chỉ mất duy nhất `session.launch_agent` (mở Agent vào session user khác — cần `SE_TCB_NAME`, không còn Agent để mở nên bỏ).

---

## 3. Cấu hình — một file duy nhất

**File:** `C:\MangoClient\server-client.json` (mở rộng từ bản 1.1.5).

Giữ từ `server-client.json` (1.1.5): `server_host`, `server_port`, `machine_id`, `secret`, `server_allowed_tools`, `heartbeat_seconds`, `call_timeout_seconds`.

Giữ từ `config.json` (MangoMCP): `permissions` (input/files_read/files_write/clipboard/admin), `launch_allowlist`, `lock` (enabled, screen_mode, pause_minutes, password_sha256), `tunnel` (enabled, port), `users[]`, `desktop_binary`, `clients[]` (cho xác thực SSH tunnel), `audit_log`.

Bỏ: `control` (IPC), `master_password_sha256`, `token_sha256` (không còn MCP local), `install_id` (trùng `machine_id`), `local_mcp_url`, `local_bearer_env`, `MANGO_LOCAL_BEARER` (không còn MCP local để xác thực).

**Không ghi mật khẩu Windows / mật khẩu khóa máy dạng plaintext** trong file này (trừ `users[].password` là tradeoff đã biết của auto-logon, và `DefaultPassword` trong registry theo thiết kế Windows — giữ nguyên như 0.14.2).

**Quản trị cấu hình từ Server (quyết định 5):** thêm nhóm tool quản trị mới, gọi qua `machine_call`:
- `config_client_create` / `config_client_rotate` / `config_client_delete` / `config_client_toggle` (quản lý `clients[]` cho tunnel SSH; secret trả về 1 lần trong kết quả tool, không ghi log — audit đã che key `secret`).
- `config_set_permissions` (đặt cổng quyền input/files_read/files_write/clipboard/admin).
- `config_set_allowlist` (đặt allowlist mở app).
- `config_set_lock` (đặt mật khẩu khóa / screen_mode / pause_minutes / enabled).
- `config_set_tunnel` (bật/tắt tunnel, đổi cổng).
- Các thao tác user/auto-logon đã có sẵn (`user_add/remove/set_default/list`, `auto_logon_enable/disable/status`) — không cần thêm.

---

## 4. Thành phần gộp (theo MERGE-MAP §2, §4)

| Thành phần | Quyết định | Ghi chú |
|---|---|---|
| `errors.py`, `audit.py`, `users.py`, `autologon.py` | Giữ nguyên | Stdlib / thuần Python, không Win32 phức tạp. |
| `config.py` | Giữ, rút gọn | Bỏ `control`, bỏ mật khẩu chủ / `token_sha256`. Giữ `watch_config` (2s), `authenticate`/`authenticate_tunnel`, `create_client`/`rotate`/`delete`, lock/tunnel/users. |
| `backend.py` | Giữ nguyên | Win32 qua `ctypes`, screenshot (Pillow), registry, PowerShell. Chạy tốt ở user session. |
| `core.py` | Giữ nguyên (engine) | Logic 100 tool + `require()` + `_check_lock_*` + workflow. Dọn: `list_processes` định nghĩa 2 lần, `tunnel_status` chết. |
| `desktop.py` | Giữ nguyên | 21 tool `desktop_*` qua `agent-desktop.exe` (subprocess argv). **Bắt buộc ship kèm binary.** |
| `uia.py` | Giữ nguyên | Cần package `uiautomation` + `comtypes`. |
| `lock.py` | Giữ nguyên | `LockController` + adapter Win32. **Bắt buộc chạy luồng riêng có message pump.** |
| `overlay.py` | Giữ nguyên | Khởi động `MangoOverlay.exe` + ghi `overlay_state.json`. **Bắt buộc ship kèm binary.** |
| `tunnel.py` | Giữ nguyên | `TunnelController` (asyncssh), luồng + event loop riêng, theo dõi config 2s. Shell chạy bằng user đăng nhập (không còn SYSTEM). |
| `server.py` | Bỏ phần lớn | Bỏ FastMCP/uvicorn/`tool()`/forwarder/middleware/`main()`. Chuyển `auto_logon_*`, `user_*`, `switch_user` thành hàm gọi trực tiếp. `control_login/logout/status` bỏ (client chính là phiên điều khiển). |
| `agent.py` | Bỏ | Tái dùng `build_dispatch_table()` làm bộ dispatch trực tiếp; tái dùng `start_lock()` để khởi động lock. |
| `session.py` | Bỏ `launch_agent` | Giữ `list_sessions`/`find_console_session` để báo trạng thái (chỉ đọc). |
| `ipc.py` | Bỏ toàn bộ | 1 process = gọi hàm trực tiếp. Giữ lock tuần tự quanh `execute_call` thay cho `_call_lock` của IPC. |
| `MangoMCPConfig.cs` (GUI) | Bỏ toàn bộ | Thay bằng tool quản trị cấu hình từ Server (§3). |

**Package Python (sửa `requirements.txt` cho đủ):** giữ `websockets` 17.4, `asyncssh` 2.24.1, `uiautomation` 2.0.29, `comtypes` 1.4.17, `Pillow` 13.0.0, `psutil` 7.2.2, `pywin32` 312. Bỏ `mcp`, `uvicorn`. Tất cả đều đã có trong `C:\MangoMCP\python` (Python 3.12.10) — Client 2.0 dùng chung Python này, không cài thêm.

**Binary ngoài bắt buộc ship kèm:** `agent-desktop.exe` (21 tool `desktop_*`) và `MangoOverlay.exe` (lớp phủ). Không phải code Python, phải đóng gói kèm trong bộ cài.

---

## 5. Bộ cài đặt — không nhập gì cả (zero-input)

**File cài:** `MangoClient-Setup-2.0.exe` (C# WinForms, như 1.1.5 nhưng bỏ mọi ô nhập).

**Giao diện:** 1 cửa sổ duy nhất — tiêu đề "Mango Client 2.0", logo xoài, 1 nút **Cài đặt** lớn, vùng hiển thị tiến trình/log. **Không có ô Server URL, không có ô tên máy, không có ô nhập mật khẩu/khóa.** Bấm Cài đặt là chạy hết, xong hiện "Cài đặt xong".

**Các bước cài (tự động hoàn toàn):**
0. Tự xin quyền Admin (manifest `requireAdministrator` — đã có từ 1.1.5).
1. Copy code Client 2.0 vào `C:\MangoClient\` (gồm engine + `agent-desktop.exe` + `MangoOverlay.exe` + `mango.ico` + `uninstall_client.ps1`). Không cài MangoMCP riêng nữa.
2. Ghi `C:\MangoClient\server-client.json` với: `server_host` = `your-server.example.com` (mặc định có sẵn trong file cài), `server_port` = 8443, `machine_name` = tên máy Windows tự lấy (`$env:COMPUTERNAME`), `server_allowed_tools` = đủ 100 tool. Giữ nguyên `machine_id`/`secret` nếu đã có (cài lại).
3. Tạo Scheduled Task duy nhất **`MangoClient`** (trigger: At logon, **Run with highest privileges**, action: `C:\MangoMCP\python\python.exe C:\MangoClient\run_client.py`, log ra `client.log`). Không còn Task Core/Agent riêng.
4. Đăng ký Windows Uninstall: `HKLM\...\Uninstall\MangoClient` (DisplayName "Mango Client", DisplayVersion "2.0.x", DisplayIcon `mango.ico`, UninstallString chạy `uninstall_client.ps1`, InstallLocation `C:\MangoClient`).
5. Khởi động client 1 lần → tự enroll lên Server (tên máy = tên Windows), hiện **pending** trên dashboard → Quản trị viên duyệt → online, 100 tool.

**Không tạo khóa / nhập / kết nối gì thêm:** không mật khẩu chủ, không tạo client MCP local, không biến môi trường Bearer, không app cấu hình để đăng nhập. Chứng chỉ máy tự sinh lúc enroll (Server cấp `machine_id` + secret, client lưu vào `server-client.json`).

**Gỡ bỏ (uninstaller):** `uninstall_client.ps1` — tự xin Admin; dừng + xóa Task `MangoClient`; **force-quit** process python đang chạy `run_client.py`; xóa `C:\MangoClient\` (code + config + log); xóa registry Uninstall. Không xóa `C:\MangoMCP` (MangoMCP cũ có thể vẫn còn cho tới khi cắt sang xong — xem §7).

---

## 6. Thứ tự triển khai (7 giai đoạn — theo MERGE-MAP §7)

Nguyên tắc: gộp từ dễ tới khó; mỗi giai đoạn chạy được + kiểm chứng độc lập; **không đụng hệ đang chạy** (`C:\MangoMCP` + Client 1.1.5) cho tới ngày cutover.

| GĐ | Nội dung | Kiểm chứng |
|---|---|---|
| 0 | Đóng băng baseline máy client (0.14.2 + 1.1.5, `<machine-id>`, 100 tool). Dựng `C:\MangoClient2\` riêng. Đăng ký máy test `máy-client-2.0` trên Server. Viết test hồi quy 100 tool. | Baseline ghi lại; máy test hiện riêng trên dashboard. |
| 1 | Module thuần Python: `errors`, `audit`, `users`, `config` (rút gọn), `autologon`. | Import được; gọi thử `users`, `autologon.get_status`, `Config.create_client` (config test), `audit` (che secret). |
| 2 | Engine đọc/file/admin trong process + `DirectEngine` thay `LocalMcpClient`. | Gọi qua Server `machine_call` lên `máy-client-2.0` các tool đọc/file/admin, kết quả **giống hệt** máy client (1.1.5). Đây là bước chứng minh "bỏ HTTP local mà kết quả không đổi". |
| 3 | Tool điều khiển trong process (bỏ IPC). Lock tuần tự quanh `execute_call`. | Parity test điều khiển: `desktop_snapshot`, `mouse_click`, `keyboard_type` (tiếng Việt), `screenshot`, `input_sequence`, `ui_find/click`, `launch_application`, clipboard. |
| 4 | Khóa máy + overlay trong process (luồng riêng). | Bắt đầu ở `visible` (an toàn). Sau đó test `black_window`/`monitor_off` khi quản trị viên ngồi trước máy (cần người thật nhập pass). |
| 5 | Shell Tunnel trong process (luồng + loop riêng). | SSH qua tunnel bằng AppID.Secret, chạy lệnh, SFTP; `LOCK_PAUSED` khi khóa tạm ngưng. |
| 6 | Dọn Core-only + 1 file config + tool quản trị cấu hình mới (§3). Sửa `requirements.txt`. Dọn code trùng. | Tool quản trị mới gọi được qua `machine_call`; config 1 file; không còn `MANGO_LOCAL_BEARER`. |
| 7 | Đóng gói + cutover máy client rồi máy client thứ hai. | Bộ cài 2.0 → cài → 100 tool + tunnel + lock qua Server → mới gỡ MangoMCP cũ (zip lại theo quy tắc). Rollback: dừng 2.0, chạy lại 1.1.5 + Core/Agent. |

**Kiểm chứng song song an toàn:** máy test `máy-client-2.0` dùng cổng tunnel khác (18768), **tắt lock** khi chạy song song (2 LockController cùng hook sẽ đánh nhau), overlay chỉ chạy 1 bản (của hệ cũ). Cùng 1 lệnh gọi lên cả 2 máy, kết quả phải giống nhau (trừ chỗ đã biết khác: lệnh chạy bằng user thay vì SYSTEM).

---

## 7. Rủi ro lớn nhất + cách giảm

| Rủi ro | Giảm nhẹ |
|---|---|
| **Máy offline cho tới khi đăng nhập** (mất khả năng điều khiển máy ở màn hình đăng nhập). | Bắt buộc auto-logon (quyết định 3). Cần mật khẩu thật cho admin. Vẫn có khoảng trống boot → logon → client khởi động. |
| **Một process = một điểm hỏng duy nhất** (trước đây Core sống sót khi Agent crash). | Task đặt "restart on failure"; lock failsafe tự mở máy khi process chết; tunnel + WS tự nối lại (`run_forever`). |
| **Hai event loop asyncio** (WS + tunnel) trong 1 process. | Giữ nguyên tổ chức: tunnel loop riêng trong luồng riêng; không gộp vào loop WS chính. |
| **Lock bắt buộc luồng riêng + message pump.** | Khởi động lock trên luồng riêng, không gọi `tick()`/hook từ luồng WS. |
| **Tool điều khiển phải tuần tự** (tránh 2 lệnh chuột/phím chồng chéo). | Lock quanh `execute_call` (nhóm `control`). |
| **Task phải chạy elevated** (ghi HKLM auto-logon, `registry_set`). | Installer tạo Task "highest privileges"; kiểm chứng trên máy bật UAC (bài học máy client thứ hai). |
| **Mất đường dự phòng trực tiếp** (không còn MCP local). | Giữ Shell Tunnel làm đường dự phòng sống còn. Nếu Server chết, vẫn SSH được vào máy qua tunnel. |
| **Shell tunnel chạy bằng user, không còn SYSTEM.** | Ghi nhận thay đổi hành vi; test lại các lệnh trước đây dựa vào SYSTEM. |

---

## 8. Tên file / vị trí

- Thiết kế này: `~/workspace/mango-server/docs/DESIGN-CLIENT-2.0.md`
- Bản đồ code: `~/workspace/mango-server/docs/MERGE-MAP-2.0.md`
- Code Client 2.0 (khi triển khai): `~/workspace/mango-server/client-2.0/` (tách khỏi `client/` 1.1.5 để không làm hỏng bản đang chạy)
- Thư mục làm việc trên máy client: `C:\MangoClient2\` (test) → `C:\MangoClient\` (chính thức khi cutover)
- Bộ cài: `MangoClient-Setup-2.0.exe` trên Desktop máy client

---

## 9. Client 2.1 — chay SYSTEM luc khoi dong, khong can dang nhap

Ly do: client 2.0.0 chay bang cua so cmd nen co the bi dong nham lam client chet, mat ket noi. Yeu cau: (1) client tu chay luc
Windows khoi dong, dieu khien duoc bang lenh cmd/powershell NGAY CA KHI
CHUA AI DANG NHAP (khong phai auto-logon); (2) luc cai luu tai khoan/mat khau de dung khi can dieu khien giao
dien/manhinh/chuot, doi mat khau duoc tu xa; (3) chay an, khong cua so
cmd/powershell nao de tat nham.

### 9.1 Kien truc 2.1: client SYSTEM + GUI agent

- **Client chinh chay bang SYSTEM o session 0**, Task "MangoClient" chay
  luc Windows khoi dong (trigger At startup, SYSTEM, "Run whether user
  is logged on or not", RunLevel Highest), bang pythonw.exe (khong cua
  so), tu ghi log ra client.log (khong con run_client_log.bat).
  - Tool KHONG can desktop (run_command, powershell, file, doc, admin,
    cau hinh...) chay ngay trong tien trinh SYSTEM — khong can dang nhap.
  - Day la mo hinh Core (SYSTEM, session 0) cua MangoMCP 0.14.2, ap dung
    lai cho Client 2.1 (2.0 chay trong user session nen yeu cau dang nhap).
- **Tool dieu khien (67 CONTROL_TOOLS: chuot/phim/manhinh/desktop_*/...)
  chuyen sang GUI agent** — tien trinh thuong tru chay trong session
  nguoi dung — qua IPC localhost 127.0.0.1:18767 (khac 8767 cua MangoMCP
  0.14.2 de khong dung do khi ca 2 cung chay). DirectEngine tu dinh
  tuyen khi phat hien tien trinh dang o session 0; o session nguoi dung
  thi chay truc tiep nhu 2.0 (giu hanh vi cu + test cu).
  - Co console session dang Active: mo GUI agent vao do bang
    WTSQueryUserToken (khong can mat khau) — duong chinh, da kiem chung
    tu 0.14.2 (session.py).
  - Chua ai dang nhap: dung tai khoan/mat khau DA LUU (users[0]) de dang
    nhap bang LogonUser roi mo GUI agent vao winsta0\default
    (session.launch_as_user) — duong du phong. Luu y that: muc do tuong
    tac day du voi desktop phu thuoc trang thai session cua Windows;
    duong console session luon chac chan nhat.
  - GUI agent chay thuong tru nen thao tac lien tiep (vd ve tranh bang
    chuot) nhanh; lock state (neu bat) song trong agent.
- **Tai khoan da luu**: installer GUI co o Ten tai khoan (mac dinh = user
  hien tai) + Mat khau; luu vao `users` trong server-client.json (index 0
  = mac dinh). Tool moi `config_set_user_password` (101 tool, nhom admin
  mac dinh tren Server — token quan tri vien co du quyen) doi mat khau user da luu
  tu xa, dong bo DefaultPassword neu user do dang bat auto-logon.
  Mat khau KHONG BAO GIO tra ve qua tool hay ghi log.
- **Khong dung auto-logon** (quyet dinh da sua cua quan tri vien): man hinh
  dang nhap van hien, khong ai ngoi truoc may dung duoc desktop khi chua
  dang nhap; chi client SYSTEM + lenh khong-can-desktop moi chay duoc.

### 9.2 File moi / doi o 2.1

- Moi: `mangoengine/session.py` (port tu MangoMCP + launch_as_user +
  is_system_session), `mangoengine/ipc.py` (port tu MangoMCP, cong
  18767), `mangoengine/gui.py` (GuiRouter singleton + dinh tuyen),
  `gui_agent.py` (tien trinh GUI agent thuong tru).
- Doi: `direct_engine.py` (dinh tuyen CONTROL_TOOLS khi session 0),
  `server_tools.py` (them config_set_user_password; control_login/
  logout/status dung GuiRouter o session 0; VERSION 2.1.0),
  `users.py` (them set_password), `mangoclient/__init__.py` (2.1.0),
  `mangoclient/config.py` (DEFAULT_ALLOWED_TOOLS 101 tool),
  `server-client.example.json` (101 tool), `run_client.py` (--log-file).
- Cai dat: `MangoClientSetup.cs` (o tai khoan/mat khau), `install_client.ps1`
  (tham so -GuiUser/-GuiPassword; dung client cu truoc khi copy; Task
  SYSTEM At startup + pythonw.exe; bo run_client_log.bat; them
  config_set_user_password vao scope khi nang cap), `uninstall_client.ps1`
  (tat ca pythonw.exe + gui_agent.py), `build_client_setup.ps1` (2.1.0).
- Test: `tests/test_client21.py` (22 test moi) + sua test 2.0 (ban 2.1.0).
  Tong 163 test pass. IPC da smoke-test vong tron tren Linux.

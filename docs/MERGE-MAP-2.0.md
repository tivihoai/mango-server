# Mango Client 2.0 — Bản đồ mã nguồn MangoMCP 0.14.2 (chuẩn bị gộp sâu)

> **Mục đích:** lập bản đồ toàn bộ mã nguồn MangoMCP 0.14.2 trên máy client để gộp nó vào Mango Client (Python) thành **MỘT chương trình duy nhất** — không còn Core (SYSTEM) / Agent / Config GUI riêng, không còn gọi HTTP qua `localhost:8766`.
> **Máy đọc:** máy client `DESKTOP-XXXXXXX` (Windows 10, Python portable `C:\MangoMCP\python`, Python **3.12.10**). **Phiên bản đọc:** MangoMCP **0.14.2** (`core.VERSION = "0.14.2"`, `__init__.__version__ = "0.14.2"`).
> **Phạm vi:** chỉ đọc + phân tích, KHÔNG sửa/xóa file nào trên máy client. Đã đọc: `README.md`, `RULES.md`, `requirements.txt`, `config.json` (chỉ cấu trúc key, không ghi giá trị bí mật), toàn bộ `mangomcp/*.py` (qua `read_text_file` và trích `def`/grep), `MangoMCPConfig.cs` (cấu trúc class/method), `C:\MangoMCP\bin\`, và repo client 1.1.5 local (`~/workspace/mango-server/client/`).
> **Quy ước trong báo cáo:** "Core" = tiến trình `mango_mcp_server.py` (SYSTEM, session 0). "Agent" = tiến trình `mango_mcp_agent.py` (user session). "Client 1.1.5" = Mango Client hiện tại (`run_client.py` + `mangoclient/`).

---

## 1. Kiến trúc tổng thể 0.14.2 — vì sao tách Core / Agent

```
                 ┌─────────────────────────────┐
                 │  AI client (Muse/Gemini/..) │
                 └──────────────┬──────────────┘
                    MCP Bearer (AppID.Secret)
                                │  https://…:8766/mcp
              ┌─────────────────┴──────────────────┐
              │  CORE (mango_mcp_server.py)         │
              │  SYSTEM, session 0, chạy lúc boot   │
              │  - MCP HTTP 8766 (FastMCP/uvicorn)  │
              │  - Shell Tunnel SSH/SFTP 8768       │
              │  - IPC router 127.0.0.1:8767        │
              │  - tool CHỈ ĐỌC / file / admin      │
              │  - control_login/logout, auto-logon │
              │  - KHÔNG có desktop, KHÔNG lock    │
              └─────────────────┬──────────────────┘
                   IPC JSON-lines (TCP localhost:8767)
                                │
              ┌─────────────────┴──────────────────┐
              │  AGENT (mango_mcp_agent.py)         │
              │  user session (console, winsta0)    │
              │  - 67 tool ĐIỀU KHIỂN (CONTROL_TOOLS)│
              │  - LockController + overlay         │
              │  - KHÔNG mở cổng MCP/SSH            │
              └────────────────────────────────────┘
```

**Vì sao phải tách (lý do gốc, ghi trong `server.py` + `session.py`):**

- **Core chạy lúc boot bằng SYSTEM (session 0)** nên luôn kết nối được ngay cả khi **chưa ai đăng nhập Windows**. Session 0 **không có desktop** (`winsta0\default` không tồn tại ở đó) nên không thể `SendInput`, chụp màn hình, hay dùng UI Automation.
- **Tool điều khiển cần desktop thật** (chuột/phím/screenshot/UIA/clipboard/mở app) nên phải chạy trong **console session của người dùng**. Core mở Agent vào session đó bằng `WTSQueryUserToken` + `CreateProcessAsUser` (`session.py`) — cơ chế này **bắt buộc quyền SYSTEM** (`SE_TCB_NAME`), tiến trình user thường không làm được.
- **IPC chỉ là đường chuyển tiếp nội bộ** (JSON-lines qua TCP `127.0.0.1:8767`, tối đa 64 MB/dòng, đủ cho screenshot base64). Một Agent nối cùng lúc, một request xử lý cùng lúc (`_call_lock`). Ranh giới xác thực thật sự là MCP ở Core (AppID.Secret), không phải IPC.
- **Lock + overlay chỉ chạy trong Agent** (cần desktop). Core chỉ hỏi trạng thái khóa live qua IPC (`__lock_state`).

**Hệ quả trực tiếp cho việc gộp (xem §7):** khi gộp thành 1 process chạy ở **user session**, toàn bộ phần "chạy được khi chưa đăng nhập" của Core sẽ mất, và phần "mở Agent vào session khác" (`session.py`) trở nên vô nghĩa (client đã ở trong session cần điều khiển).

---

## 2. Bản đồ module — giữ / bỏ / sửa khi gộp

| Module | Kích thước | Vai trò | Quyết định gộp |
|---|---|---|---|
| `errors.py` | 1,4 KB | `MangoError(code, message, detail, retryable)` + helper `permission_denied`, `platform_unsupported`, `invalid_args` | **Giữ nguyên** (stdlib thuần) |
| `audit.py` | 1,6 KB | Ghi audit JSONL, thread-safe, che key `password/secret/token`, `summarize_args` (200 ký tự), không bao giờ làm hỏng thao tác chính | **Giữ nguyên** |
| `users.py` | 6,2 KB | Thao tác list user thuần túy: `add/remove/set_default/find/get_default/list_public` | **Giữ nguyên** |
| `autologon.py` | 6,6 KB | Ghi/đọc registry Winlogon (`AutoAdminLogon`, `DefaultUserName`, `DefaultPassword` plaintext, `DefaultDomainName`) | **Giữ**, cần chạy elevated (ghi HKLM) |
| `config.py` | 20 KB | `Config` (load/save atomic, `reload_if_changed`, `watch_config` 2s), cổng quyền, `authenticate` (3 dạng), tạo/xoay/bật/tắt client, mật khẩu chủ, lock, tunnel, users | **Giữ phần lớn**, bỏ `control` (IPC), bỏ mật khẩu chủ / `token_sha256` nếu bỏ MCP local |
| `backend.py` | 29 KB | Lớp thao tác OS: Win32 qua `ctypes` (`SendInput`, `EnumWindows`, clipboard), screenshot (Pillow), OCR Windows, registry (`winreg`), PowerShell (`subprocess`); bản non-Windows trả `PLATFORM_UNSUPPORTED` | **Giữ nguyên** (chạy tốt ở user session) |
| `core.py` | 50 KB | Logic 100 tool + cổng quyền `require()` + kiểm tra khóa + workflow engine | **Giữ nguyên** (đây là "engine") |
| `desktop.py` | 29 KB | 21 tool `desktop_*`: gọi `agent-desktop.exe` qua `subprocess` (argv, không qua PowerShell), envelope JSON, `--stdin`, `--headed` | **Giữ nguyên** (cần ship kèm `agent-desktop.exe`) |
| `uia.py` | 11 KB | UI Automation qua package `uiautomation` (+ `ctypes`): `find/click/set_text/get_text/tree/interactives/window_text` | **Giữ nguyên** (cần package `uiautomation`) |
| `lock.py` | 58 KB | `LockController` (state machine khóa máy) + adapter Win32 (`ctypes`: hook, cửa sổ khóa, tắt màn hình) | **Giữ nguyên**, chạy trên **luồng riêng** có message pump (bắt buộc) |
| `overlay.py` | 5,7 KB | Khởi động `MangoOverlay.exe` (tiến trình .NET riêng) + ghi `overlay_state.json` (exe đọc mỗi 200 ms) | **Giữ nguyên** (cần ship kèm `MangoOverlay.exe`) |
| `tunnel.py` | 16 KB | `TunnelController`: SSH/SFTP server (`asyncssh`), luồng riêng + event loop riêng, theo dõi config mỗi 2s | **Giữ nguyên** (chạy tốt ở user session; cần package `asyncssh`) |
| `server.py` | 29 KB | FastMCP + `tool()` decorator + forwarder IPC + `control_login/logout/status` + `auto_logon_*` + `user_*` + `switch_user` + `BearerAuthMiddleware` + `main()` (uvicorn) | **Bỏ phần lớn**: bỏ FastMCP/uvicorn/`tool()`/forwarder/middleware/`main()`; **giữ** `control_*`→ (xem §7), `auto_logon_*`, `user_*`, `switch_user` (chuyển thành hàm gọi trực tiếp) |
| `agent.py` | 7,9 KB | `build_dispatch_table()` (CONTROL_TOOLS → hàm), class `Agent` (khởi động lock/overlay, xử lý request IPC, áp scope client) | **Bỏ** (không còn IPC/Agent); logic `build_dispatch_table` được **tái dùng** làm bộ dispatch trực tiếp cho Client 2.0 |
| `session.py` | 7,6 KB | `pywin32`: liệt kê session, `find_console_session`, `launch_agent` (`WTSQueryUserToken` + `CreateProcessAsUser`) | **Bỏ** `launch_agent` (cần SYSTEM, không còn Agent để mở); có thể giữ `find_console_session`/`list_sessions` cho trạng thái |
| `ipc.py` | 14 KB | IPC JSON-lines TCP `127.0.0.1:8767`: `ControlRouter` (Core) + `AgentConnection` (Agent), `__ping/__lock_state/__shutdown` | **Bỏ toàn bộ** (1 process = gọi hàm trực tiếp) |
| `MangoMCPConfig.cs` | 84 KB | GUI WinForms cấu hình (xem §6.4) | **Bỏ toàn bộ**; logic thay thế bằng thao tác cấu hình do Server điều khiển (xem §7.4) |
| `mango_mcp_server.py` | 291 B | Entry Core → `mangomcp.server.main()` | **Bỏ** |
| `mango_mcp_agent.py` | 556 B | Entry Agent → `mangomcp.agent.main()` | **Bỏ** |
| `overlay/MangoOverlay.cs` | — | Source WinForms của `MangoOverlay.exe` | **Giữ binary** (không cần build lại trừ khi đổi giao diện) |
| `bin/agent-desktop.exe` | — | CLI agent-desktop v1.2.0 (Vercel Labs), binary ngoài | **Giữ binary, bắt buộc ship kèm** |

**File cấu hình:**
- `config.json` (MangoMCP): `permissions`, `launch_allowlist`, `audit_log`, `clients[]`, `master_password_sha256`, `lock{}`, `tunnel{}`, `desktop_binary`, `control{}` (IPC — bỏ), `users[]`, `token_sha256`, `install_id`. **Lưu ý:** chỉ lưu hash SHA-256, **trừ** `users[].password` (plaintext — tradeoff đã biết của auto-logon) và `DefaultPassword` trong registry (plaintext theo thiết kế Windows).
- `server-client.json` (Client 1.1.5): `server_host/port`, `machine_id/secret`, `server_allowed_tools`, `local_mcp_url`, `local_bearer_env`, `heartbeat_seconds`, `call_timeout_seconds`. **Không** ghi mật khẩu Windows / mật khẩu chủ; Bearer local đọc từ biến môi trường.
- **Gộp thành 1 file duy nhất** (đề xuất: `server-client.json` mở rộng, xem §8): giữ `permissions`, `launch_allowlist`, `lock`, `tunnel`, `users`, `desktop_binary`, `clients[]` (cần cho xác thực SSH tunnel), `audit_log`; bỏ `control` (IPC), `master_password_sha256`/`token_sha256` (nếu bỏ MCP local), `install_id` (trùng `machine_id`).

---

## 3. Bảng 100 tool → hàm thực thi → nhóm quyền → nơi chạy

**Cách đọc bảng:**
- **Nhóm Server** = nhóm trong `toolgroups.py` của Mango Server (`read` 35 / `control` 51 / `files` 4 / `admin` 10). Token Agent chỉ được gọi tool thuộc nhóm nó có; tool lạ mặc định về `admin` (fail-closed).
- **Cổng MangoMCP** = nhóm trong `require(config, group)` của `core.py`/`desktop.py` (`input`, `files_read`, `files_write`, `clipboard`, `admin`, hoặc `—` = không gọi `require()`, tức không bị cổng quyền chặn). `PERMISSION_GROUPS = [input, files_read, files_write, clipboard, admin]`. Mặc định: `input=True, files_read=True, files_write=True, clipboard=False, admin=False`.
- **Chạy ở đâu (0.14.2)** = `Core trực tiếp` (chạy trong Core, session 0) hoặc `Agent qua IPC` (thuộc `CONTROL_TOOLS`, Core forward sang Agent). Trong Client 2.0, **cả 100 tool đều chạy trong cùng 1 process** (user session).
- **Đăng ký tool** (`server.py`): 22 tool chỉ đọc/file/admin đăng ký trực tiếp từ `core` (`tool(core.<tên>)`); 67 tool điều khiển đăng ký qua forwarder (`tool(_control_forwarder(_control_fn(tên)))` với `tên ∈ sorted(core.CONTROL_TOOLS)`); 3 tool `control_*`, 3 tool `auto_logon_*`, 5 tool `user_*/switch_user` đăng ký trực tiếp từ `server.py`. Tổng **22 + 67 + 3 + 3 + 5 = 100**.
- **Decorator `tool(fn)`** (`server.py:60`): bỏ tham số `config` đầu tiên, suy luận kiểu từ annotation/default, bọc bằng audit + lỗi có cấu trúc (`MangoError` → `RuntimeError(json)`).

### 3.1 Nhóm `read` (35 tool — chỉ đọc)

| # | Tool | Hàm thực thi | File | Cổng MangoMCP | Chạy ở đâu (0.14.2) |
|---|---|---|---|---|---|
| 1 | `mango_status` | `core.mango_status` | core.py | — | Core trực tiếp |
| 2 | `system_info` | `core.system_info` | core.py | — | Core trực tiếp |
| 3 | `list_processes` | `core.list_processes` (def dòng 1043, **ghi đè** def dòng 223) | core.py | `input` ⚠️ | Core trực tiếp |
| 4 | `display_inventory` | `core.display_inventory` | core.py | — | Agent qua IPC |
| 5 | `list_windows` | `core.list_windows` | core.py | — | Agent qua IPC |
| 6 | `screenshot` | `core.screenshot` | core.py | — | Agent qua IPC |
| 7 | `screen_preview` | `core.screen_preview` | core.py | — | Agent qua IPC |
| 8 | `get_pixel_color` | `core.get_pixel_color` | core.py | — | Agent qua IPC |
| 9 | `clipboard_get_text` | `core.clipboard_get_text` | core.py | `clipboard` | Agent qua IPC |
| 10 | `list_directory` | `core.list_directory` | core.py | `files_read` | Core trực tiếp |
| 11 | `read_text_file` | `core.read_text_file` | core.py | `files_read` | Core trực tiếp |
| 12 | `search_files` | `core.search_files` | core.py | `files_read` | Core trực tiếp |
| 13 | `stat_file` | `core.stat_file` | core.py | `files_read` | Core trực tiếp |
| 14 | `lock_status` | `core.lock_status` | core.py | — | Core trực tiếp (hỏi Agent qua IPC `__lock_state` nếu có) |
| 15 | `tunnel_info` | `core.tunnel_info` | core.py | — | Core trực tiếp |
| 16 | `control_status` | `server.control_status` | server.py | — | Core trực tiếp |
| 17 | `user_list` | `server.user_list` | server.py | — | Core trực tiếp |
| 18 | `auto_logon_status` | `server.auto_logon_status` | server.py | — | Core trực tiếp |
| 19 | `ui_tree` | `core.ui_tree` | core.py | `input` | Agent qua IPC |
| 20 | `ui_find` | `core.ui_find` | core.py | `input` | Agent qua IPC |
| 21 | `ui_get_text` | `core.ui_get_text` | core.py | `input` | Agent qua IPC |
| 22 | `find_controls` | `core.find_controls` | core.py | `input` | Agent qua IPC |
| 23 | `get_control_text` | `core.get_control_text` | core.py | `input` | Agent qua IPC |
| 24 | `desktop_status` | `desktop.desktop_status` | desktop.py | — | Agent qua IPC |
| 25 | `desktop_snapshot` | `desktop.desktop_snapshot` | desktop.py | — (nhưng `_check_lock_capture`) | Agent qua IPC |
| 26 | `desktop_find` | `desktop.desktop_find` | desktop.py | — (nhưng `_check_lock_capture`) | Agent qua IPC |
| 27 | `desktop_get` | `desktop.desktop_get` | desktop.py | — (nhưng `_check_lock_capture`) | Agent qua IPC |
| 28 | `desktop_list_apps` | `desktop.desktop_list_apps` | desktop.py | — | Agent qua IPC |
| 29 | `desktop_list_windows` | `desktop.desktop_list_windows` | desktop.py | — | Agent qua IPC |
| 30 | `desktop_clipboard_get` | `desktop.desktop_clipboard_get` | desktop.py | `clipboard` | Agent qua IPC |
| 31 | `find_text_on_screen` | `core.find_text_on_screen` | core.py | `input` | Agent qua IPC |
| 32 | `read_window_text` | `core.read_window_text` | core.py | `input` | Agent qua IPC |
| 33 | `find_color_on_screen` | `core.find_color_on_screen` | core.py | — | Agent qua IPC |
| 34 | `count_color_on_screen` | `core.count_color_on_screen` | core.py | — | Agent qua IPC |
| 35 | `list_workflows` | `core.list_workflows` | core.py | `input` ⚠️ | Core trực tiếp |

### 3.2 Nhóm `control` (51 tool — điều khiển)

| # | Tool | Hàm thực thi | File | Cổng MangoMCP | Chạy ở đâu (0.14.2) |
|---|---|---|---|---|---|
| 1 | `mouse_move` | `core.mouse_move` | core.py | `input` | Agent qua IPC |
| 2 | `mouse_click` | `core.mouse_click` | core.py | `input` | Agent qua IPC |
| 3 | `mouse_drag` | `core.mouse_drag` | core.py | `input` | Agent qua IPC |
| 4 | `mouse_path` | `core.mouse_path` | core.py | `input` | Agent qua IPC |
| 5 | `mouse_scroll` | `core.mouse_scroll` | core.py | `input` | Agent qua IPC |
| 6 | `keyboard_type` | `core.keyboard_type` | core.py | `input` | Agent qua IPC |
| 7 | `keyboard_hotkey` | `core.keyboard_hotkey` | core.py | `input` | Agent qua IPC |
| 8 | `focus_window` | `core.focus_window` | core.py | `input` | Agent qua IPC |
| 9 | `wait_for_window` | `core.wait_for_window` | core.py | `input` | Agent qua IPC |
| 10 | `input_sequence` | `core.input_sequence` | core.py | `input` | Agent qua IPC |
| 11 | `clipboard_set_text` | `core.clipboard_set_text` | core.py | `clipboard` | Agent qua IPC |
| 12 | `ui_click` | `core.ui_click` | core.py | `input` | Agent qua IPC |
| 13 | `ui_set_text` | `core.ui_set_text` | core.py | `input` | Agent qua IPC |
| 14 | `set_control_text` | `core.set_control_text` | core.py | `input` | Agent qua IPC |
| 15 | `click_control` | `core.click_control` | core.py | `input` | Agent qua IPC |
| 16 | `desktop_click` | `desktop.desktop_click` | desktop.py | `input` | Agent qua IPC |
| 17 | `desktop_double_click` | `desktop.desktop_double_click` | desktop.py | `input` | Agent qua IPC |
| 18 | `desktop_right_click` | `desktop.desktop_right_click` | desktop.py | `input` | Agent qua IPC |
| 19 | `desktop_type` | `desktop.desktop_type` | desktop.py | `input` | Agent qua IPC |
| 20 | `desktop_set_value` | `desktop.desktop_set_value` | desktop.py | `input` | Agent qua IPC |
| 21 | `desktop_clear` | `desktop.desktop_clear` | desktop.py | `input` | Agent qua IPC |
| 22 | `desktop_select` | `desktop.desktop_select` | desktop.py | `input` | Agent qua IPC |
| 23 | `desktop_toggle` | `desktop.desktop_toggle` | desktop.py | `input` | Agent qua IPC |
| 24 | `desktop_scroll` | `desktop.desktop_scroll` | desktop.py | `input` | Agent qua IPC |
| 25 | `desktop_press` | `desktop.desktop_press` | desktop.py | `input` | Agent qua IPC |
| 26 | `desktop_launch` | `desktop.desktop_launch` | desktop.py | `input` + `admin` | Agent qua IPC |
| 27 | `desktop_focus_window` | `desktop.desktop_focus_window` | desktop.py | `input` | Agent qua IPC |
| 28 | `desktop_wait` | `desktop.desktop_wait` | desktop.py | `input` | Agent qua IPC |
| 29 | `desktop_clipboard_set` | `desktop.desktop_clipboard_set` | desktop.py | `clipboard` | Agent qua IPC |
| 30 | `set_display_resolution` | `core.set_display_resolution` | core.py | `input` | Agent qua IPC |
| 31 | `activate_or_launch` | `core.activate_or_launch` | core.py | `input` | Agent qua IPC |
| 32 | `snapshot` | `core.snapshot` | core.py | `input` | Agent qua IPC |
| 33 | `click_label` | `core.click_label` | core.py | `input` | Agent qua IPC |
| 34 | `multi_click` | `core.multi_click` | core.py | `input` | Agent qua IPC |
| 35 | `run_workflow` | `core.run_workflow` | core.py | `input` | Agent qua IPC |
| 36 | `save_workflow` | `core.save_workflow` | core.py | `files_write` | Core trực tiếp |
| 37 | `run_saved_workflow` | `core.run_saved_workflow` | core.py | `input` | Agent qua IPC |
| 38 | `delete_workflow` | `core.delete_workflow` | core.py | `files_write` | Core trực tiếp |
| 39 | `set_busy_overlay` | `core.set_busy_overlay` | core.py | `input` | Agent qua IPC |
| 40 | `notify_on_screen` | `core.notify_on_screen` | core.py | `input` | Agent qua IPC |
| 41 | `wait_for_pixel` | `core.wait_for_pixel` | core.py | `input` | Agent qua IPC |
| 42 | `send_keys` | `core.send_keys` | core.py | `input` | Agent qua IPC |
| 43 | `scroll_at` | `core.scroll_at` | core.py | `input` | Agent qua IPC |
| 44 | `close_window` | `core.close_window` | core.py | `input` | Agent qua IPC |
| 45 | `set_window_state` | `core.set_window_state` | core.py | `input` | Agent qua IPC |
| 46 | `open_path` | `core.open_path` | core.py | `input` | Agent qua IPC |
| 47 | `launch_application` | `core.launch_application` | core.py | `input` (+ `admin` nếu ngoài allowlist) | Agent qua IPC |
| 48 | `run_command` | `core.run_command` | core.py | `admin` | Core trực tiếp |
| 49 | `powershell` | `core.powershell` | core.py | `admin` | Core trực tiếp |
| 50 | `kill_process` | `core.kill_process` | core.py | `admin` | Core trực tiếp |
| 51 | `terminate_process` | `core.terminate_process` | core.py | `admin` | Core trực tiếp |

### 3.3 Nhóm `files` (4 tool — ghi file)

| # | Tool | Hàm thực thi | File | Cổng MangoMCP | Chạy ở đâu (0.14.2) |
|---|---|---|---|---|---|
| 1 | `write_text_file` | `core.write_text_file` | core.py | `files_write` | Core trực tiếp |
| 2 | `copy_file` | `core.copy_file` | core.py | `files_write` | Core trực tiếp |
| 3 | `move_file` | `core.move_file` | core.py | `files_write` | Core trực tiếp |
| 4 | `delete_file` | `core.delete_file` | core.py | `files_write` | Core trực tiếp |

### 3.4 Nhóm `admin` (10 tool — quản trị)

| # | Tool | Hàm thực thi | File | Cổng MangoMCP | Chạy ở đâu (0.14.2) |
|---|---|---|---|---|---|
| 1 | `registry_get` | `core.registry_get` | core.py | `input` ⚠️ | Core trực tiếp |
| 2 | `registry_set` | `core.registry_set` | core.py | `admin` | Core trực tiếp |
| 3 | `control_login` | `server.control_login` | server.py | — | Core trực tiếp (mở Agent vào console session) |
| 4 | `control_logout` | `server.control_logout` | server.py | — | Core trực tiếp (dừng Agent) |
| 5 | `user_add` | `server.user_add` | server.py | — | Core trực tiếp |
| 6 | `user_remove` | `server.user_remove` | server.py | — | Core trực tiếp |
| 7 | `user_set_default` | `server.user_set_default` | server.py | — | Core trực tiếp |
| 8 | `switch_user` | `server.switch_user` | server.py | — | Core trực tiếp (đặt auto-logon + `shutdown /r /t 5 /f`) |
| 9 | `auto_logon_enable` | `server.auto_logon_enable` | server.py | — | Core trực tiếp |
| 10 | `auto_logon_disable` | `server.auto_logon_disable` | server.py | — | Core trực tiếp |

### 3.5 Lưu ý / quirk phát hiện khi đọc code

- **Tổng kiểm đếm:** `read` 35 + `control` 51 + `files` 4 + `admin` 10 = **100**, khớp đúng 100 tool `server.py` đăng ký. Mọi tool trong `toolgroups.py` đều có trong 100 tool đã đăng ký và ngược lại.
- **`CONTROL_TOOLS` = 67 tool** (màn hình/capture 11, chuột/phím 12, clipboard 2, UIA/Win32 11, cửa sổ/overlay 7, `launch_application` 1, workflow 2, `desktop_*` 21). Đây là tập Agent phụ trách; `agent.build_dispatch_table()` tra `getattr(core, tên) or getattr(desktop, tên)` và **báo lỗi nếu thiếu hàm**.
- **Tool đọc nhưng bị cổng `input` (quirk):** `list_processes` (bản có hiệu lực), `registry_get`, `list_workflows` gọi `require(config, "input")` dù là tool đọc. Nếu cổng `input` tắt ở máy đích, 3 tool đọc này bị chặn với `PERMISSION_DISABLED` dù Server xếp chúng vào nhóm `read`. (Client local "MangoServer" có đủ 5 scope nên trên máy client không thấy lỗi này.)
- **Tool đọc clipboard nhưng cổng `clipboard` (mặc định TẮT):** `clipboard_get_text`, `desktop_clipboard_get` xếp nhóm Server `read` nhưng cần cổng MangoMCP `clipboard` (mặc định `False`). Tương tự, `clipboard_set_text` / `desktop_clipboard_set` cần `clipboard`.
- **Tool chụp/đọc màn hình KHÔNG bị cổng quyền:** `screenshot`, `screen_preview`, `get_pixel_color`, `display_inventory`, `list_windows`, `find_color_on_screen`, `count_color_on_screen`, `desktop_status`, `desktop_list_apps`, `desktop_list_windows`, `desktop_snapshot`, `desktop_find`, `desktop_get` không gọi `require()` — chỉ cần client xác thực hợp lệ là gọi được (dù cổng `input` tắt). Riêng `desktop_snapshot`/`desktop_find`/`desktop_get` vẫn bị chặn khi khóa đang tạm ngưng (`_check_lock_capture`).
- **`list_processes` bị định nghĩa 2 lần** trong `core.py` (dòng 223 và dòng 1043, bản sau có thêm `name_filter`); Python dùng bản sau (dòng 1043, có `require(input)`). Đây là code trùng cần dọn khi gộp.
- **`tunnel_status` (core.py:134) được định nghĩa nhưng KHÔNG đăng ký** thành tool trong `server.py` (chỉ `tunnel_info` được đăng ký) — code chết, bỏ được khi gộp.
- **Chặn khi khóa tạm ngưng:** `_check_lock_pause()` / `_check_lock_capture()` trong `core.py` chặn tool input/capture khi `LockController.state == "paused"` (người ngồi máy vừa mở khóa). Cơ chế này sống trong `core` nhưng đọc trạng thái từ `LOCK_CONTROLLER` (Agent) hoặc `LOCK_STATE_PROVIDER` (Core hỏi Agent qua IPC). Trong Client 2.0, `LOCK_CONTROLLER` là biến module duy nhất, đọc trực tiếp — đơn giản hơn.
- **`launch_application` có 2 cổng:** `require(input)` rồi, nếu exe ngoài allowlist (`mspaint/notepad/calc/explorer`) thì thêm `require(admin)`.
- **`desktop_launch` có 2 cổng:** `require(input)` + `require(admin)`.

---

## 4. Chi tiết từng module quan trọng

### 4.1 `backend.py` — lớp thao tác hệ điều hành (29 KB)

- **Win32 qua `ctypes` (lazy import trong từng hàm):** `SendInput` (chuột/phím, `KEYEVENTF_UNICODE` để gõ tiếng Việt), `EnumWindows`/`EnumChildWindows`, `ImageGrab` (screenshot qua Pillow), clipboard, `focus_window` (có mẹo `AttachThreadInput` vượt khóa foreground), `set_window_state`, `set_display_resolution`, `click_control` (`BM_CLICK`), `set_control_text` (`WM_SETTEXT`), `get_control_text`.
- **OCR Windows:** `ocr_image()` (dùng OCR có sẵn của Windows) phục vụ `find_text_on_screen`.
- **Tiến trình / lệnh / registry:** `list_processes` / `kill_process` (psutil), `run_powershell` (subprocess), `registry_get` / `registry_set` (`winreg`).
- **Non-Windows:** các hàm chuột/phím/chụp ảnh có bản stub trả `PLATFORM_UNSUPPORTED` thay vì sập — giữ nguyên cơ chế này để code vẫn import/test được trên Linux.
- **Gộp:** giữ nguyên. Mọi hàm này chạy tốt trong user session (không cần SYSTEM). Đây là lớp thấp nhất, không phụ thuộc Core/Agent/IPC.

### 4.2 `core.py` — logic tool + cổng quyền + workflow (50 KB)

- Mọi tool nhận `config` làm tham số đầu tiên, trả dict JSON-serializable, ném `MangoError` khi lỗi.
- `require(config, group)`: kiểm tra cổng quyền toàn cục (`config.permission(group)`) **và** scope của client đang gọi (`CURRENT_AUTH` — master thì không giới hạn, client thì phải có group trong `scopes` của nó). Thiếu quyền → `PERMISSION_DISABLED`.
- `mango_status` / `system_info`: trạng thái máy + phiên bản.
- `input_sequence`: chạy chùm hành động trong 1 lần gọi, có `dry_run`, `stop_on_error`, kết quả từng bước (`_validate_action`, `_run_action`).
- `snapshot` / `click_label` / `multi_click`: chụp ảnh + gán nhãn số cho phần tử (`_revalidate` kiểm tra phần tử còn tồn tại, tránh bấm vào frame cũ).
- **Workflow engine:** `save_workflow` / `list_workflows` / `run_workflow` / `run_saved_workflow` / `delete_workflow`; step có `retries`/`on_error`, truyền kết quả bằng `{{prev}}` (`_substitute_prev`); file workflow lưu ở thư mục app (`_workflow_path`).
- **Khóa:** `_check_lock_pause()` / `_check_lock_capture()` đọc `LOCK_CONTROLLER` (hoặc `LOCK_STATE_PROVIDER` khi ở Core) để chặn tool khi đang tạm ngưng.
- **Gộp:** giữ nguyên toàn bộ. Đây là "engine" mà Client 2.0 gọi trực tiếp. Cần dọn: `list_processes` trùng, `tunnel_status` chết.

### 4.3 `server.py` — tầng giao vận MCP + tool cấu hình (29 KB)

- `mcp = FastMCP("MangoMCP", instructions=INSTRUCTIONS, host=127.0.0.1, port=8765-mặc-định)` (thực tế chạy 8766 qua biến môi trường / cấu hình triển khai).
- `BearerAuthMiddleware` (ASGI): đọc header `Authorization: Bearer …` (+ `X-Client-Id`), gọi `Config.authenticate()`, 401 nếu sai; đặt danh tính vào `CURRENT_AUTH` cho tầng core áp scope.
- `_control_forwarder(fn)`: tạo hàm giữ nguyên chữ ký tool nhưng chuyển tiếp qua `CONTROL_ROUTER.call(tên_tool, kwargs, client={name, scopes})`.
- `control_login(config, username=None)`: tìm console session active (`session.find_console_session()`); sai user → `WRONG_USER`; chưa ai đăng nhập → `NO_SESSION`; đúng thì `session.launch_agent(session_id)` rồi `CONTROL_ROUTER.wait_for_agent(30s)`.
- `control_logout` / `control_status`: dừng Agent / xem trạng thái Core-session-Agent.
- `auto_logon_*` / `user_*` / `switch_user`: tool **cấu hình** chạy tại Core (dùng được ngay cả khi chưa có console session). `switch_user` đặt auto-logon rồi `shutdown /r /t 5 /f` (chỉ khi `confirm_reboot=true`, không thì chỉ trả kế hoạch).
- `main()`: `watch_config` (2s) → `CONTROL_ROUTER.start()` (IPC 8767) → `TunnelController.start()` (luồng nền) → `uvicorn.run(...)`; `finally` dừng tunnel + router.
- **Gộp:** bỏ FastMCP/uvicorn/`tool()`/forwarder/middleware/`main()`; chuyển `auto_logon_*`, `user_*`, `switch_user` thành hàm gọi trực tiếp trong Client 2.0; `control_login`/`control_logout`/`control_status` trở nên vô nghĩa (xem §7.2) — bỏ hoặc biến thành no-op/trạng thái nội bộ.

### 4.4 `agent.py` — tiến trình Agent (7,9 KB)

- `build_dispatch_table()`: với mỗi tên trong `sorted(core.CONTROL_TOOLS)`, tra `getattr(core, tên) or getattr(desktop, tên)`; thiếu hàm → `RuntimeError` ngay lúc khởi động (fail-fast tốt — giữ cơ chế này cho Client 2.0).
- Class `Agent`: `start_lock()` (gọi `overlay.start()` rồi tạo `LockController(adapter=lock.make_adapter())`, gán `core.LOCK_CONTROLLER`, `ctrl.start(lambda: config)`); `handle(request)` xử lý 1 request IPC (`__ping`, `__lock_state`, `__shutdown`, hoặc dispatch tool + áp scope client qua `CURRENT_AUTH`); `run()` (gọi `watch_config`, `start_lock`, gửi `hello` `{pid, session_id, username, version}` qua `ipc.AgentConnection`, tự nối lại IPC nếu rớt).
- **Gộp:** bỏ toàn bộ file (không còn IPC/Agent). Nhưng **tái dùng 2 ý**: (1) `build_dispatch_table()` → bộ dispatch trực tiếp cho Client 2.0 (mở rộng cho cả 100 tool, không chỉ CONTROL_TOOLS); (2) `start_lock()` → cách Client 2.0 khởi động lock + overlay khi chạy.

### 4.5 `desktop.py` — 21 tool `desktop_*` qua agent-desktop CLI (29 KB)

- Gọi `C:\MangoMCP\bin\agent-desktop.exe` (Vercel Labs v1.2.0) bằng `subprocess.run(argv_list)` — **không qua PowerShell** (PowerShell đọc `@token` thành toán tử splatting và nuốt mất ref `@<snapshot_id>:e<N>`).
- Envelope JSON `{version, ok, command, data/error}`; exit 0 = ok, 1 = lỗi có cấu trúc, 2 = lỗi parse đối số. Lỗi CLI giữ nguyên mã (`STALE_REF`, `AMBIGUOUS_TARGET`, `POLICY_DENIED`…), `retryable` theo `disposition.retry == "safe"`.
- Text dài (>200 ký tự) qua `--stdin` (giới hạn: `type` 10.000 byte, `set-value`/`clipboard-set` 128 KiB). Snapshot thô >~200 KB thì cắt ngắn cây (`_prune_tree`, `_truncate_snapshot`, đánh dấu `truncated`).
- `--headed` (input vật lý, có thể cướp foreground) bắt buộc với `type`/`right-click`/`double-click`/`focus` trên Windows (headless trả `POLICY_DENIED`); các tool tương ứng mặc định `headed=True`.
- Mọi tool `desktop_*` (trừ tool đọc) gọi `require(config, "input")`; `desktop_launch` thêm `require(admin)`; `desktop_clipboard_*` gọi `require(clipboard)`; `desktop_snapshot`/`find`/`get` gọi `_check_lock_capture`.
- **Gộp:** giữ nguyên. **Bắt buộc ship kèm `agent-desktop.exe`** (binary ngoài, không phải code Python). Timeout mặc định 30s + 15s ân hạn.

### 4.6 `uia.py` — UI Automation (11 KB)

- Dùng package **`uiautomation`** (PyPI, đã cài 2.0.29) + `ctypes`: `find` / `click` (Invoke Pattern) / `set_text` (Value Pattern) / `get_text` / `tree` (duyệt cây, `max_depth`/`max_items`) / `interactives` / `focused_info` / `window_text` (đọc chữ trong cửa sổ, rẻ hơn chụp ảnh).
- **Gộp:** giữ nguyên. Cần package `uiautomation` + `comtypes` (xem §7.3).

### 4.7 `lock.py` — khóa máy (58 KB, module phức tạp nhất)

- `LockController`: state machine `off` / `locked` / `paused` / `visible`; `screen_mode` ∈ (`black_window`, `monitor_off`, `visible`); `pause_minutes` mặc định 15, `IDLE_RESUME_SECONDS = 60`, `UNLOCK_WINDOW_SECONDS = 60`.
- **Adapter pattern:** `_NullAdapter` (non-Windows/test) và adapter Win32 thật (`make_adapter()`, dùng `ctypes`). Cơ chế chặn (ghi trong docstring + code):
  1. Hook mức thấp `WH_KEYBOARD_LL` / `WH_MOUSE_LL` nuốt phím/chuột vật lý nhưng cho input do `SendInput` của Agent qua (cờ `INJECTED`). Đây là lớp chính, chạy được cả khi không elevated (`BlockInput` chỉ thử thêm, hỏng cũng không sao).
  2. Tắt nguồn màn hình (`SC_MONITORPOWER`) khi khóa; framebuffer vẫn chạy nên screenshot của Agent vẫn thấy màn hình thật. Phím/chuột vật lý đầu tiên "đánh thức": hiện cửa sổ đen + ô nhập pass trong 60 giây, không nhập thì tắt màn lại.
  3. Cửa sổ khóa Win32 thuần (`ctypes`, topmost, phủ toàn màn hình ảo, `WS_EX_TRANSPARENT|LAYERED|NOACTIVATE`, opacity 0,97–0,99 để bấm xuyên qua khi cần); chặn Alt+Tab, phím Win, Alt+F4. **Ctrl+Alt+Del không chặn được** (thiết kế Windows — đường thoát cuối).
- **Luồng riêng bắt buộc:** hook + cửa sổ khóa phải sống cùng một luồng với message pump. `LockController.start()` tạo luồng lock riêng (`_loop` → `tick()` + `pump_messages()`); `sync_from_config()` chỉ cập nhật trạng thái, `tick()` ở luồng lock mới bật/tắt theo cấu hình (chậm nhất 0,5s). Bật trực tiếp ở luồng chính làm cửa sổ tạo ở luồng chính nhưng pump ở luồng khác → nút bấm/chữ không hiện, không mở khóa được.
- **Tạm ngưng (pause):** người ngồi máy nhập đúng pass (chỉ lưu hash SHA-256) → Agent tạm ngưng; hết giờ + nghỉ tay ≥60s thì khóa lại; hết giờ mà vẫn đang thao tác thì hiện "Hết giờ — khóa lại khi bạn nghỉ tay" (không đếm âm). Cửa sổ đếm lùi (0.10.1) bấm xuyên qua, không cướp focus.
- **Chế độ `visible` (0.12.0, máy client đang dùng):** bật "cho phép bot điều khiển" nhưng KHÔNG che màn hình, KHÔNG nuốt chuột/phím, KHÔNG hiện ô nhập pass, không có tạm ngưng. Đổi chế độ có hiệu lực trong vài giây, không cần restart.
- **Failsafe:** server tắt/crash → hook + cửa sổ khóa chết theo tiến trình, `BlockInput` tự nhả; mặc định TẮT, muốn bật phải đặt mật khẩu trước.
- **Gộp:** giữ nguyên. LockController đã được thiết kế chạy trên luồng riêng → Client 2.0 chỉ cần gọi `start_lock()` kiểu `agent.py` (khởi động trong `run_client` thay vì trong Agent). Không cần SYSTEM.

### 4.8 `overlay.py` — lớp phủ trạng thái (5,7 KB)

- Hiển thị do **tiến trình .NET riêng `MangoOverlay.exe`** (WinForms, source `overlay/MangoOverlay.cs`) đảm nhiệm. Module Python chỉ: khởi động exe bằng `subprocess.Popen` (nếu chưa chạy, kiểm tra bằng `psutil`), ghi trạng thái ra `overlay_state.json` (exe đọc mỗi 200 ms), nhận "nhịp hoạt động" (`pulse()` 3s) từ các tool thao tác để tự bật/tắt trạng thái bận.
- `set_busy(active, message)` / `notify(text, seconds)` / `status()`; cờ `_suppressed` khi khóa máy (không vẽ đè lên giao diện nhập pass); tắt bằng biến môi trường `MANGO_MCP_OVERLAY=0`. **Mọi lỗi đều bị nuốt** — lớp hiển thị không bao giờ được làm hỏng tool chính.
- **Gộp:** giữ nguyên. Cần ship kèm `MangoOverlay.exe`.

### 4.9 `tunnel.py` — Shell Tunnel SSH/SFTP (16 KB)

- `TunnelController(config_getter, lock_getter, audit_fn)`: chạy SSH server trong **luồng daemon riêng** (`_manager`) với **event loop `asyncio` riêng** (`asyncio.new_event_loop()`); theo dõi config mỗi 2s, tự bật/tắt theo `tunnel.enabled` (mặc định TẮT).
- `asyncssh` (đã cài 2.24.1; import tùy chọn — thiếu thì tunnel chỉ báo lỗi, không làm sập server). Xác thực **chỉ password** (`AppID.Secret` qua `config.authenticate_tunnel()`; không pubkey/kbdint). Host key `ssh_host_key` (ed25519) trong thư mục app, tự tạo nếu chưa có.
- Shell tương tác (`cmd.exe` qua `asyncio.create_subprocess_exec`) hoặc lệnh exec một lần; SFTP có `AuditedSFTP` (ghi log open/remove/rename/mkdir/rmdir) và `_PausedSFTP` (từ chối mọi thao tác khi khóa tạm ngưng). Khi `LOCK_PAUSED`, shell/SFTP bị từ chối với `LOCK_PAUSED`.
- **Cố tình vượt qua scopes/allowlist** của MCP (Quản trị viên chọn toàn quyền); mọi kết nối/lệnh/SFTP đều ghi audit (không ghi mật khẩu/nội dung file). Có `run_standalone()` để test độc lập.
- **Gộp:** giữ nguyên. **Chạy tốt trong user session** (chỉ bind `127.0.0.1:8768`, không cần SYSTEM). Shell nó mở sẽ chạy bằng **user đang đăng nhập** (thay vì SYSTEM như ở Core) — đúng hơn cho công cụ user-session, nhưng là thay đổi hành vi cần ghi nhận (xem §7.2).

### 4.10 `config.py` — cấu hình + xác thực (20 KB, đã đọc toàn bộ)

- `Config.load()` (từ biến môi trường `MANGO_MCP_CONFIG` hoặc mặc định), `save()` (ghi atomic qua file `.tmp` + replace), `reload_if_changed()` (theo `mtime`), `watch_config()` (luồng nền, kiểm tra mỗi 2s — nhờ đó app cấu hình ghi file là server áp dụng ngay, không cần restart).
- `authenticate(bearer, client_id_header)`: 3 dạng — (1) Bearer = mật khẩu chủ → `{kind: master}`; (2) Bearer = `<client_id>.<secret>` (tách ở dấu `.` đầu tiên) → `{kind: client, ...}`; (3) header `X-Client-Id` + Bearer = secret thô. So sánh bằng `hmac.compare_digest` với hash SHA-256 đã lưu. `last_used_at` cập nhật tối đa mỗi 60s.
- `create_client(name, scopes)` trả `(record, "<client_id>.<secret>")` — secret thô chỉ xuất hiện đúng một lần ở đây; server chỉ lưu hash. `rotate_client_secret`, `set_client_enabled`, `delete_client`, `client_public` (không bao giờ lộ secret).
- `token_sha256()`: ưu tiên mật khẩu chủ (đã đặt thì token chủ cũ hết hiệu lực), rồi env `MANGO_MCP_TOKEN_SHA256` / `MANGO_MCP_TOKEN`, rồi `data["token_sha256"]`.
- Lock: `lock_settings` / `set_bot_control` (bật mà chưa đặt pass khóa thì trả `False`) / `set_lock_screen_mode` / `set_lock_password` (chỉ lưu hash) / `set_lock_enabled` / `set_lock_pause_minutes`.
- Tunnel: `tunnel_settings` / `set_tunnel` / `authenticate_tunnel` (chỉ client AppID.Secret, không dùng mật khẩu chủ, không cập nhật `last_used_at`).
- `control_settings()` → `{ipc_host, ipc_port, login_timeout_seconds}` (bỏ khi gộp). `desktop_binary()` (mặc định `C:\MangoMCP\bin\agent-desktop.exe`).
- **Gộp:** giữ class `Config` + `watch_config` + `authenticate`/`authenticate_tunnel` + `create_client`/`rotate`/`delete` + lock/tunnel/users methods; bỏ `control_settings()`, bỏ mật khẩu chủ/`token_sha256()` nếu bỏ MCP local (xem §8).

### 4.11 `session.py` — quản lý session Windows (7,6 KB)

- Dùng `pywin32` (`win32ts`, `win32process`, `win32profile`, `win32security`): `list_sessions()` (`WTSEnumerateSessions`), `find_console_session()` (WinStation `console` + state `active`), `get_session_info()`, `launch_agent(session_id, command, extra_env, cwd)`.
- `launch_agent`: `WTSQueryUserToken(session_id)` → `CreateEnvironmentBlock` → `CreateProcessAsUser(token, 'winsta0\default', agent…)` với `CREATE_UNICODE_ENVIRONMENT | CREATE_NO_WINDOW`, `STARTUPINFO.lpDesktop = 'winsta0\default'`. **Bắt buộc quyền SYSTEM (`SE_TCB_NAME`)** — lỗi ghi rõ "cần quyền SYSTEM/SE_TCB_NAME". Không cần mật khẩu Windows (token lấy từ session đang active).
- **Gộp:** **bỏ** `launch_agent` (không còn Agent để mở, và user session không có quyền này). Có thể giữ `list_sessions`/`find_console_session` để báo trạng thái (chỉ đọc, không cần SYSTEM).

### 4.12 `ipc.py` — IPC Core↔Agent (14 KB)

- JSON-lines qua TCP `127.0.0.1:8767`, tối đa 64 MB/dòng. Agent nối vào Core, gửi `hello` `{type, pid, session_id, username, version}`. Core gửi request `{id, tool, args, client}` (`client` = danh tính MCP của người gọi để Agent áp scope; `None` = master/không giới hạn scope). Agent trả `{id, ok, result}` hoặc `{id, ok:false, error:{code,message,detail,retryable}}`.
- Tool nội bộ (không phải MCP tool): `__ping`, `__lock_state`, `__shutdown` (Agent tự thoát, không nối lại — dùng ở `control_logout`).
- `ControlRouter`: một Agent nối cùng lúc (Agent mới thay Agent cũ), một request xử lý cùng lúc (`_call_lock`; `call()` timeout 300s, chờ lock tối đa 60s → `IPC_BUSY`); chưa có Agent → `CONTROL_NOT_ACTIVE`.
- **Gộp:** **bỏ toàn bộ**. Thay bằng gọi hàm trực tiếp trong cùng process. Lưu ý: tính chất "một lệnh điều khiển chạy cùng lúc" của IPC cần được giữ lại bằng một lock quanh `execute_call` ở Client 2.0 (xem §7.5).

### 4.13 `audit.py` / `errors.py` / `users.py` / `autologon.py`

- **`audit.py`**: `write_audit(config, tool, args_summary, ok, error_code)` — JSONL, thread-safe (`threading.Lock`), che key nhạy cảm (`password/passwd/secret/token` → `***`), `summarize_args(args, limit=200)`. Không bao giờ ném lỗi ra ngoài. **Giữ nguyên.**
- **`errors.py`**: `MangoError(code, message, detail, retryable)` + `to_dict()`/`to_json_text()`; helper `permission_denied(group)`, `platform_unsupported(feature, detail)`, `invalid_args(detail)`. **Giữ nguyên.**
- **`users.py`**: thuần thao tác list (`_norm`, `_find`, `find`, `get_default` = entry đầu tiên, `list_public` = chỉ `username` + `is_default`, `add`/`remove`/`set_default` + `_sync_default_flags` — chỉ entry index 0 có `default=True`). Từ chối mật khẩu trống; không cho xóa khi chỉ còn 1 user. **Giữ nguyên.**
- **`autologon.py`**: `winreg` (stdlib Windows), khóa `HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon`. `get_status()` (không bao giờ trả mật khẩu), `enable(username, password, domain)` (ghi 4 giá trị, từ chối mật khẩu trống — đã kiểm chứng 8/11: auto-logon mật khẩu trống không chạy), `disable()` (đặt `AutoAdminLogon="0"` + **xóa** `DefaultPassword`). Cần quyền ghi HKLM. **Giữ nguyên** (xem §7.1 về quyền elevated).

### 4.14 Config GUI C# — `MangoMCPConfig.cs` (84 KB, WinForms)

- **Không chứa logic engine.** Chỉ là trình soạn thảo `config.json` + điều khiển task: `ConfigStore` (`Load`/`Save`/`GetString`/`GetPerm`/`SetPerm`/`SetClients`/`SetAllowlist`/`SetUsers`), `Crypto` (`Sha256Hex`, `NewClientId`, `NewSecret`), `LoginForm.TryLogin` (mật khẩu chủ), `CredentialForm` (hiện secret 1 lần khi tạo client), `CreateClientForm`.
- `MainForm` có các trang: **Clients** (`RefreshClients`, `CreateClient`, `ToggleClient`, `RotateClient`, `DeleteClient`, `PersistClients`), **Users** (`BuildUsersPage`, `RefreshUsers`, `AddUser`, `RemoveUser`, `SetDefaultUser`, `SyncDefaultFlags`), **AutoLogon** (`RefreshAutoLogonState`, `ApplyAutoLogon`), **Perms** (`BuildPermsPage`, `RefreshPerms`), **Lock** (`BuildLockPage`, `RefreshLock`, `SaveLock`, `ToggleBotControl`, `LockDict`), **Master** (`RefreshMaster`, `SaveMasterPassword`), **Tunnel** (`BuildTunnelPage`, `RefreshTunnel`, `SaveTunnel`, `TunnelDict`), **Guide** (`BuildGuidePage`); cộng `RunTask` (chạy/dừng task MangoMCP), `UpdateServerState`, `HideToTray`/`ShowFromTray`, `ShowPage`/`LayoutMain`.
- **Gộp:** bỏ toàn bộ GUI. Mọi thao tác trên đều phải có đường thay thế do **Server điều khiển** (xem §7.4) — hiện tại **chưa có** tool Server nào cho: tạo/xoay/xóa client MCP, đặt mật khẩu chủ, đặt cổng quyền, đặt allowlist, đặt mật khẩu/chế độ khóa, bật/tắt tunnel. Đây là khoảng trống lớn nhất về mặt quản trị sau khi bỏ GUI.

---

## 5. Client 1.1.5 hiện tại — cái mà việc gộp sẽ thay thế

(Đọc từ `~/workspace/mango-server/client/` — để biết chính xác "đầu nối" cần thay.)

- **`run_client.py`**: đọc `ClientConfig(server-client.json)` → lấy Bearer local từ biến môi trường `MANGO_LOCAL_BEARER` → tạo `LocalMcpClient(local_mcp_url, bearer)` → `local.initialize()` (bắt tay MCP, có tự thử lại — sửa ở 1.1.2) → enroll nếu chưa có `machine_id` (`enroll`/`enroll_by_url`) → tạo `ServerLink(cfg, local)` → `asyncio.run(link.run_forever())`.
- **`mangoclient/local_mcp.py`**: `LocalMcpClient` — chỉ dùng `urllib` (stdlib), POST JSON-RPC Streamable HTTP tới `127.0.0.1:8766`, header `Authorization: Bearer <secret>`, quản lý `Mcp-Session-Id`, timeout 45s. **Đây là khối bị thay thế hoàn toàn** bằng bộ dispatch trực tiếp trong process.
- **`mangoclient/agent.py` (`ServerLink`)**: `refresh_local_status()` (gọi `mango_status` + `control_status` qua local MCP), `build_heartbeat()` (`allowed_tools`), `apply_desired_scope()` (ghi `server_allowed_tools` + cập nhật bộ nhớ, không cần restart), `send_upgrade_status()`, `_handle_upgrade()` (tải package, kiểm tra SHA-256, giải nén vào staging, áp dụng), `_apply_heartbeat_ack()` (nhận `desired_scope` + `upgrade`), `restart_command()`/`restart_machine()` (`shutdown /r`, bypass scope tool), `execute_call(tool, args)` (**kiểm tra `tool ∈ allowed_tools` rồi `asyncio.to_thread(local.call_tool, tool, args)`**), `_heartbeat_loop()` (30s), `_run_once()` (vòng WebSocket: `machine_call`, `admin/restart_machine`, `upgrade_available`), `run_forever()`.
- **`mangoclient/config.py`**: `ClientConfig` + `DEFAULT_ALLOWED_TOOLS` (đủ 100 tool từ 1.1.3). **`mangoclient/updater.py`**: logic tải/áp dụng package nâng cấp.
- **Điểm nối cho việc gộp:** `ServerLink.__init__(config, local, …)` nhận `local` là đối tượng có phương thức `call_tool(name, args)`. Client 2.0 chỉ cần thay `LocalMcpClient` bằng một **`DirectEngine`** có cùng phương thức `call_tool(name, args)` nhưng gọi thẳng hàm `core`/`desktop`/`server` trong process (kèm kiểm tra `allowed_tools` + cổng quyền + chặn khi khóa tạm ngưng — tức tái dùng `core.require()` và `_check_lock_*`). Phần WebSocket/heartbeat/upgrade/restart của `ServerLink` **giữ nguyên**.

---

## 6. Điểm KHÓ / RỦI RO khi gộp thành 1 process user-session

### 6.1 (a) Tool nào hiện cần quyền SYSTEM mà user-session (admin) không làm được

| Khả năng | Hiện chạy ở | Cần SYSTEM? | Kết luận cho Client 2.0 |
|---|---|---|---|
| `WTSQueryUserToken` + `CreateProcessAsUser` vào session khác (`session.launch_agent`) | Core | **Có** (`SE_TCB_NAME`) | **Bỏ.** Không còn Agent để mở. Hệ quả: client chỉ điều khiển đúng session nó đang chạy; không mở được Agent vào session của user khác (trước đây Core làm được). |
| Ghi HKLM khóa Winlogon (`autologon.enable/disable`) | Core | Không bắt buộc SYSTEM — cần **ghi HKLM** (admin elevated) | **Giữ được**, với điều kiện Task chạy client phải đặt **"Run with highest privileges"**. Trên máy client (UAC tắt) không thành vấn đề; trên máy mới bật UAC thì bắt buộc kiểm tra điểm này khi cài đặt. |
| Tạo/xóa Scheduled Task, ghi `HKLM\...\Uninstall` | Installer (admin) | Cần admin (không cần SYSTEM) | **Giữ được** — installer đã chạy `requireAdministrator`. |
| `BlockInput` (trong lock) | Agent | Không chắc (chỉ thử thêm, hỏng cũng không sao) | Không phụ thuộc — lớp chặn chính là hook mức thấp, chạy được khi không elevated. |
| Hook `WH_KEYBOARD_LL`/`WH_MOUSE_LL`, `SC_MONITORPOWER`, cửa sổ khóa Win32 | Agent | **Không** | **Giữ được** nguyên vẹn ở user session. |
| `shutdown /r` (restart/switch_user) | Core (`run_command`) / Client (`restart_machine`) | Cần quyền shutdown (admin có) | **Giữ được.** Client 1.1.5 đã tự làm `shutdown /r` trực tiếp (không qua MangoMCP) và đã kiểm chứng đạt 2 lần trên máy client. |
| Đọc/ghi file hệ thống, registry HKLM (đọc) | Core | Admin đọc được HKLM; ghi HKLM cần elevated | **Giữ được** với Task elevated. |
| **MCP server local cổng 8766 (FastMCP/uvicorn)** | Core | Không cần SYSTEM, nhưng là **một server HTTP riêng** | **Bỏ theo yêu cầu gộp.** Hệ quả: AI khác (Gemini/Claude/ChatGPT) **mất đường nối trực tiếp** vào máy qua MCP local; từ nay chỉ còn đường duy nhất qua **Mango Server MCP** (`https://your-server.example.com/mcp`). Nếu Quản trị viên muốn giữ đường trực tiếp cho AI khác, phải giữ lại MCP local như một "chế độ tương thích" — cần chốt (xem §8). |
| Shell Tunnel chạy bằng SYSTEM | Core | Không cần SYSTEM để bind `127.0.0.1:8768` | **Giữ được**, nhưng shell nó mở sẽ chạy bằng **user đang đăng nhập** thay vì SYSTEM (xem §6.2). |

### 6.2 (b) Tool nào cần chạy khi chưa có user đăng nhập — mất tính năng gì

Đây là **hồi quy chức năng lớn nhất** của việc gộp.

- **Hiện tại (Core SYSTEM, chạy lúc boot):** các tool chỉ đọc/file/admin (`mango_status`, `system_info`, `list_directory`, `read/write_text_file`, `run_command`, `powershell`, `registry_*`, `tunnel_info`…) **chạy được ngay cả khi chưa ai đăng nhập Windows**. Shell Tunnel cũng chạy được (shell mở ra chạy bằng SYSTEM). Server thấy máy "online" ngay sau khi boot, không cần chờ đăng nhập.
- **Sau khi gộp (Client 2.0 = Scheduled Task lúc user logon):** nếu **không ai đăng nhập**, client **không chạy** → **không tool nào chạy được**, Server thấy máy **offline**. Mất hoàn toàn khả năng "điều khiển máy đang ở màn hình đăng nhập" và "SSH vào máy chưa đăng nhập".
- **Cách giảm thiệt hại duy nhất: auto-logon.** Bật auto-logon (đã có tool `auto_logon_enable`, cần mật khẩu thật) thì: boot → Windows tự đăng nhập → Task logon chạy Client 2.0 → máy online. Nhưng vẫn có **khoảng trống boot → logon → client khởi động** (máy offline trong lúc đó), và nếu auto-logon hỏng (đổi mật khẩu, xóa user, tắt tính năng) thì máy nằm offline cho tới khi có người đăng nhập tay.
- **Thay đổi ý nghĩa các tool:**
  - `control_login` / `control_logout` / `control_status`: trở nên vô nghĩa (client **chính là** phiên điều khiển; không còn Agent để mở/dừng). Đề xuất: bỏ 3 tool này, hoặc biến `control_status` thành trạng thái nội bộ của Client 2.0 (phiên bản, user đang chạy, lock, tunnel).
  - `switch_user`: vẫn làm được (đặt auto-logon + reboot) — giữ nguyên.
  - `auto_logon_enable` / `auto_logon_disable` / `auto_logon_status`: càng trở nên **quan trọng** (quyết định máy có tự online sau reboot hay không) — giữ nguyên, cần elevated.
  - Shell Tunnel: shell mở ra chạy bằng user đang đăng nhập (đúng hơn cho công cụ user-session), nhưng **không còn shell SYSTEM** — lệnh nào trước đây dựa vào quyền SYSTEM (vd đọc file của user khác, ghi HKLM khi UAC bật) sẽ không chạy được nữa nếu user đó không phải admin.
- **Khóa máy:** lock + overlay vốn đã chạy trong Agent (user session) nên gộp không ảnh hưởng. Nhưng lưu ý: nếu client chết/crash thì lock cũng chết theo (failsafe có sẵn: hook + cửa sổ khóa chết theo tiến trình → máy tự mở, không khóa chết).

### 6.3 (c) Phụ thuộc Python package ngoài stdlib

`requirements.txt` **thiếu** nhiều package thực tế đang dùng (chỉ ghi `mcp`, `uvicorn`, `Pillow`, `psutil`, `pywin32`). Danh sách đầy đủ đã kiểm chứng bằng `pip list` trên `C:\MangoMCP\python` (Python 3.12.10):

| Package | Phiên bản đã cài | Dùng ở | Sau khi gộp |
|---|---|---|---|
| `mcp` | 1.30.0 | `server.py` (FastMCP) | **Bỏ** (không còn MCP local) |
| `uvicorn` | 0.54.0 | `server.py` (`main()`) | **Bỏ** (không còn MCP local) |
| `websockets` | 17.4 | Client WS (ServerLink) + cài qua pip ở bước 2b | **Giữ** (bắt buộc) |
| `asyncssh` | 2.24.1 | `tunnel.py` | **Giữ** (bắt buộc cho tunnel) |
| `uiautomation` | 2.0.29 | `uia.py` | **Giữ** (bắt buộc cho `ui_*`) |
| `comtypes` | 1.4.17 | `uia.py`/`backend.py` (COM/UIA) | **Giữ** |
| `Pillow` | 13.0.0 | `backend.py` screenshot, `core.py` xử lý ảnh | **Giữ** |
| `psutil` | 7.2.2 | `backend.py` process, `overlay.py` kiểm tra exe | **Giữ** |
| `pywin32` | 312 | `session.py`, clipboard, Win32 API | **Giữ** (phần `session.py` bỏ, nhưng clipboard/Win32 còn dùng) |
| `cryptography`, `cffi`, `pydantic`, `anyio`, `httpx`, `starlette`, `sse-starlette`… | — | Phụ thuộc của `mcp`/`asyncssh`/`uvicorn` | Chỉ giữ phần `asyncssh` cần (`cryptography`, `cffi`); phần của `mcp`/`uvicorn` bỏ theo |

- **Tất cả package cần giữ đều đã có sẵn trong `C:\MangoMCP\python`.** Client 2.0 dùng chung Python portable này → không cần cài thêm gì trên máy đích, chỉ cần **sửa `requirements.txt` / script đóng gói** để ghi đủ danh sách (tránh lần sau build lại từ đầu thì thiếu `asyncssh`/`uiautomation`/`comtypes`/`websockets`).
- **Binary ngoài bắt buộc ship kèm:** `C:\MangoMCP\bin\agent-desktop.exe` (21 tool `desktop_*`) và `C:\MangoMCP\app\MangoOverlay.exe` (lớp phủ). Cả hai đều không phải code Python, không thể "gộp" bằng cách copy code — phải đóng gói kèm trong bộ cài Client 2.0.
- **Rủi ro:** `agent-desktop.exe` là binary của bên thứ ba (Vercel Labs v1.2.0); nếu mất file này, toàn bộ 21 tool `desktop_*` trả `DESKTOP_UNAVAILABLE`. `run_desktop()` đã fail rõ ràng (không fail lặng) — giữ cơ chế này.

### 6.4 (d) Logic Config GUI C# mà client phải thay thế

GUI (`MangoMCPConfig.cs`) không chứa logic engine — toàn bộ thao tác của nó đều gọi xuống class `Config` của Python rồi ghi `config.json`. Nhưng **sau khi bỏ GUI, các thao tác sau sẽ không còn đường nào làm được** nếu Client 2.0 không bổ sung:

| Thao tác GUI | Hàm C# | Hiện có tool Server nào làm được? | Cần bổ sung ở Client 2.0 |
|---|---|---|---|
| Tạo/bật/tắt/xoay/xóa client MCP (AppID.Secret) | `CreateClient`, `ToggleClient`, `RotateClient`, `DeleteClient`, `PersistClients` | **Không có** | **Mới:** thao tác quản trị client (tạo/xoay/xóa/bật/tắt), hoặc API cấu hình máy trên Server. Cần cho cả xác thực SSH tunnel (tunnel dùng `clients[]`). |
| Đặt mật khẩu chủ | `SaveMasterPassword` | **Không có** | Có thể **bỏ luôn** mật khẩu chủ (không còn MCP local để xác thực, không còn GUI để mở). Giữ lại chỉ làm phức tạp thêm. |
| Đặt cổng quyền (input/files/clipboard/admin) | `RefreshPerms` / trang Perms | **Không có** | **Mới:** thao tác đặt cổng quyền (hoặc cho Server đặt `permissions` qua API cấu hình máy). |
| Đặt allowlist mở app | (trang cấu hình) | **Không có** | **Mới:** cùng nhóm trên. |
| Đặt mật khẩu khóa + chế độ màn hình + bật/tắt bot | `SaveLock`, `ToggleBotControl`, `RefreshLock` | **Không có** | **Mới:** thao tác đặt lock (password/mode/pause_minutes/enabled). Bắt buộc phải có — nếu không, Quản trị viên mất cách bật/tắt khóa máy từ xa. |
| Bật/tắt Shell Tunnel + đổi cổng | `SaveTunnel`, `RefreshTunnel` | **Không có** (chỉ `tunnel_info` để xem) | **Mới:** thao tác bật/tắt tunnel (hoặc API cấu hình máy). |
| Thêm/xóa/đặt mặc định user Windows | `AddUser`, `RemoveUser`, `SetDefaultUser` | **Có:** `user_add`, `user_remove`, `user_set_default`, `user_list` | Không cần bổ sung. |
| Bật/tắt auto-logon | `ApplyAutoLogon` | **Có:** `auto_logon_enable/disable/status` | Không cần bổ sung. |
| Chạy/dừng task MangoMCP (Core/Agent) | `RunTask`, `UpdateServerState` | — | **Bỏ.** Không còn task Core/Agent; chỉ còn 1 Task duy nhất của Client 2.0 (do installer quản lý). |
| Đăng nhập GUI bằng mật khẩu chủ | `LoginForm.TryLogin` | — | **Bỏ** (không còn GUI). |
| Hiện secret 1 lần khi tạo client | `CredentialForm` | — | Nếu bổ sung thao tác tạo client, phải có cơ chế hiện secret 1 lần tương tự (trả về trong kết quả tool rồi Quản trị viên tự lưu; không ghi log — audit đã che key `secret`). |

**Kết luận §6.4:** bỏ GUI là bỏ luôn toàn bộ "bảng điều khiển tại máy". Client 2.0 **bắt buộc** phải có một kênh quản trị cấu hình từ Server (đề xuất: thêm nhóm tool quản trị cấu hình, hoặc mở rộng `machine_call` với các thao tác cấu hình máy + tab "Cấu hình máy" trên dashboard), nếu không máy con sẽ không còn chỉnh được gì sau khi cài đặt.

### 6.5 Rủi ro khác

- **Một process = một điểm hỏng duy nhất.** Trước đây Core sống sót khi Agent crash (tool chỉ đọc + tunnel vẫn chạy). Sau khi gộp, client crash → mất **tất cả** (engine + tunnel + lock + WS). Giảm nhẹ: Task chạy client đặt "restart on failure"; lock có failsafe tự mở máy khi process chết (an toàn, không khóa chết); tunnel + WS tự nối lại (client đã có vòng `run_forever`).
- **Hai event loop `asyncio` trong một process.** Tunnel đã chạy loop riêng trong luồng riêng (`tunnel.py:_manager`); Client 1.1.5 chạy loop WS ở luồng chính. Hai loop độc lập, không xung đột — nhưng phải giữ nguyên cách tổ chức này (không gộp tunnel vào loop WS chính).
- **Luồng lock + message pump.** `LockController` bắt buộc chạy trên luồng riêng (xem §4.7). Client 2.0 phải giữ đúng: khởi động lock trên luồng riêng, không gọi `tick()`/hook từ luồng WS.
- **Tuần tự hóa tool điều khiển.** IPC cũ chỉ cho 1 request điều khiển chạy cùng lúc (`_call_lock`). Client 2.0 phải giữ một lock tương tự quanh `execute_call` (ít nhất với tool nhóm `control`) để 2 lệnh từ Server không xen vào nhau (vd 2 thao tác chuột/phím chồng chéo).
- **Chặn input của chính mình.** Khi khóa ở chế độ `black_window`/`monitor_off`, hook nuốt phím/chuột vật lý nhưng cho `SendInput` (cờ `INJECTED`) qua. Client 2.0 tự `SendInput` nên vẫn qua được — cơ chế này đã chạy trong Agent, giữ nguyên là được.
- **Quyền elevated của Task.** Client 2.0 phải chạy elevated (ghi HKLM auto-logon, `registry_set`, một số tool admin). Installer phải tạo Task với "highest privileges" và kiểm chứng trên máy bật UAC (máy client tắt UAC nên không lộ lỗi này — đúng như vụ exe 1.1.5 từng lộ lỗi Admin trên máy client thứ hai).
- **Mất đường dự phòng trực tiếp.** Hiện tại nếu Mango Server chết, Quản trị viên vẫn điều khiển máy client trực tiếp qua MCP local (`tunnel của máy client`) hoặc SSH tunnel. Sau khi gộp (bỏ MCP local), nếu Server chết thì **không còn đường nào** vào máy từ xa ngoài SSH tunnel (nếu giữ tunnel) — và tunnel cũng nằm trong chính process client đó. Nên giữ tunnel là đường dự phòng sống còn.
- **Dọn code trùng khi gộp:** `list_processes` định nghĩa 2 lần, `tunnel_status` chết, `make_adapter()` trong `lock.py` định nghĩa 2 lần (dòng 1194 và 1199 — bản sau thắng). Dọn trong lúc gộp, kèm test hồi quy.

---

## 7. Thứ tự gộp đề xuất (7 giai đoạn)

Nguyên tắc: **gộp từ phần ít rủi ro nhất tới phần khó nhất; mỗi giai đoạn đều chạy được và kiểm chứng được độc lập; không đụng vào hệ đang chạy (`C:\MangoMCP` + Client 1.1.5) cho tới khi Client 2.0 sẵn sàng.**

### Giai đoạn 0 — Đóng băng baseline + dựng chỗ làm việc riêng

- Chụp baseline: ghi lại trạng thái máy client đang chạy (MangoMCP 0.14.2 + Client 1.1.5, machine_id `<machine-id>`, 100 tool, tunnel, lock `visible`).
- Dựng thư mục làm việc riêng trên máy client: `C:\MangoClient2\` (code + config + log riêng), **không sửa gì trong `C:\MangoMCP\`**. Dùng chung Python portable `C:\MangoMCP\python\python.exe` (đã có đủ package).
- Đăng ký Client 2.0 trên Server bằng **tên máy riêng** (vd `máy-client-2.0`) để nó hiện như một máy test độc lập, không đụng đăng ký máy client đang chạy.
- Viết test hồi quy 100 tool (gọi qua `machine_call` lên máy test, so kết quả với máy client đang chạy).

### Giai đoạn 1 — Module thuần Python (dễ nhất, không Win32)

- Gộp: `errors.py`, `audit.py`, `users.py`, `config.py` (bản rút gọn: bỏ `control`, bỏ mật khẩu chủ), `autologon.py`.
- Kiểm chứng: import được trên máy client, gọi thử `users.add/remove`, `autologon.get_status`, `Config.create_client` (trên config test, không đụng config thật), `audit.write_audit` (ghi đúng file, che secret).
- Rủi ro: thấp. `autologon.enable` chỉ test khi có mật khẩu thật + Quản trị viên đồng ý (ghi HKLM).

### Giai đoạn 2 — Engine đọc/file/admin trong process (giá trị lớn nhất, bỏ HTTP local)

- Gộp: `backend.py` + `core.py` (chỉ các tool **không** thuộc `CONTROL_TOOLS`) + `desktop.py` (chỉ tool đọc: `desktop_status/list_apps/list_windows/snapshot/find/get/clipboard_get`).
- Thay `LocalMcpClient` bằng **`DirectEngine`**: cùng phương thức `call_tool(name, args)`, nhưng tra bảng dispatch (tái dùng ý `agent.build_dispatch_table()`, mở rộng cho cả 100 tool) và gọi thẳng hàm trong process; giữ kiểm tra `allowed_tools` (Server scope) + `core.require()` (cổng MangoMCP) + chặn khi khóa tạm ngưng.
- Kiểm chứng: trên máy test `máy-client-2.0`, gọi qua Server `machine_call` các tool đọc/file/admin (`mango_status`, `system_info`, `list_directory`, `read/write_text_file`, `run_command`, `powershell`, `registry_get/set`, `save/list/delete_workflow`) và so kết quả **giống hệt** máy client (1.1.5). Đây là bước chứng minh "bỏ HTTP local mà kết quả không đổi".
- Rủi ro: trung bình. Chú ý: `run_command`/`powershell` ở Core chạy bằng SYSTEM, ở Client 2.0 chạy bằng user — kết quả có thể khác với lệnh cần quyền SYSTEM (ghi chú rõ trong test).

### Giai đoạn 3 — Tool điều khiển trong process (bỏ IPC)

- Gộp: toàn bộ `CONTROL_TOOLS` (chuột/phím/screenshot/clipboard/UIA/`desktop_*`/workflow chạy) — tức phần còn lại của `core.py` + `desktop.py` + `uia.py` + `backend.py` (đã gộp ở GĐ2).
- Bỏ: `ipc.py`, `agent.py`, `session.launch_agent`, forwarder trong `server.py`.
- Thêm lock tuần tự quanh `execute_call` (giữ tính chất "1 lệnh điều khiển cùng lúc" của IPC cũ).
- Kiểm chứng: parity test điều khiển — `desktop_snapshot` (ref + click), `mouse_click`, `keyboard_type` (gõ tiếng Việt), `screenshot`, `input_sequence`, `ui_find/ui_click`, `launch_application` (trong + ngoài allowlist), `clipboard_get/set`. So với máy client.
- Rủi ro: trung bình. Chú ý: các tool này vốn đã chạy ở user session (Agent) nên về lý thuyết chạy y hệt trong Client 2.0; điểm khác duy nhất là không còn IPC (nhanh hơn, ít lỗi `CONTROL_NOT_ACTIVE` hơn).

### Giai đoạn 4 — Khóa máy + overlay trong process

- Gộp: `lock.py` (nguyên `LockController` + adapter Win32) + `overlay.py` + ship kèm `MangoOverlay.exe`. Khởi động kiểu `agent.start_lock()` (gọi `overlay.start()` rồi tạo `LockController`, `ctrl.start(...)`) nhưng gọi từ `run_client` thay vì từ Agent.
- **Giữ nguyên luật luồng riêng:** lock chạy trên luồng riêng có message pump; không gọi lock từ luồng WS.
- Kiểm chứng: bắt đầu ở chế độ `visible` (máy client đang dùng — an toàn nhất, không che màn hình). Sau đó test `black_window`/`monitor_off` trong khung giờ quản trị viên ngồi trước máy (cần người thật nhập pass mở khóa để kiểm chứng đường tạm ngưng 15 phút + khóa lại). Kiểm chứng `lock_status` qua Server.
- Rủi ro: cao (khóa máy sai có thể khóa chết máy). Bắt buộc: failsafe đã có trong code (chết theo process, mặc định tắt, cần đặt pass trước). Không test `black_window` khi quản trị viên vắng mặt.

### Giai đoạn 5 — Shell Tunnel trong process

- Gộp: `tunnel.py` (nguyên `TunnelController`) vào Client 2.0; giữ luồng riêng + event loop riêng + theo dõi config 2s.
- Kiểm chứng: SSH vào máy test qua tunnel (Cloudflare) bằng AppID.Secret, chạy lệnh, SFTP lên/xuống file; kiểm chứng `tunnel_info`/`tunnel_status`; kiểm chứng `LOCK_PAUSED` khi khóa tạm ngưng.
- Rủi ro: trung bình. Chú ý: shell chạy bằng user đăng nhập (không còn SYSTEM) — test lại các lệnh trước đây dựa vào SYSTEM.

### Giai đoạn 6 — Dọn phần Core-only + 1 file config + bỏ GUI

- Bỏ: `server.py` (FastMCP/uvicorn/middleware/`main()`), `session.py` (trừ `find_console_session` nếu cần), `mango_mcp_server.py`, `mango_mcp_agent.py`, toàn bộ GUI C#.
- Chuyển `auto_logon_*`, `user_*`, `switch_user` (từ `server.py`) thành hàm gọi trực tiếp trong Client 2.0.
- Gộp config thành **1 file duy nhất** (`server-client.json` mở rộng — xem §2). Bỏ `MANGO_LOCAL_BEARER` (không còn MCP local để xác thực). Giữ `clients[]` (cho tunnel SSH).
- Bổ sung thao tác quản trị cấu hình do Server điều khiển (xem §6.4): tạo/xoay/xóa client, đặt cổng quyền, allowlist, lock, tunnel — dưới dạng tool mới hoặc API cấu hình máy trên Server + tab dashboard.
- Sửa `requirements.txt` cho đủ package (thêm `asyncssh`, `uiautomation`, `comtypes`, `websockets`; bỏ `mcp`, `uvicorn`).
- Dọn code trùng: `list_processes` (2 def), `tunnel_status` (chết), `make_adapter()` (2 def trong `lock.py`).

### Giai đoạn 7 — Đóng gói + cắt sang (cutover) trên máy client, rồi máy client thứ hai

- Bộ cài Client 2.0 (exe mới): 1 chương trình duy nhất, 1 Scheduled Task (logon, **highest privileges**), hiện trong Windows Uninstall, gỡ thì force-quit; nhúng: code client 2.0 + `agent-desktop.exe` + `MangoOverlay.exe` + Python portable (hoặc dùng chung `C:\MangoMCP\python` — cần chốt, xem §8).
- Cutover máy client (làm trong khung giờ quản trị viên ngồi trước máy): dừng hệ cũ (Task `MangoServerClient` 1.1.5, Task Core `MangoMCP`, Task Agent `MangoMCP-Agent`) → chạy Client 2.0 với đúng `machine_id` cũ (hoặc enroll mới + duyệt + xóa máy cũ) → kiểm chứng đủ 100 tool + tunnel + lock qua Server → mới gỡ MangoMCP cũ (giữ lại `C:\MangoMCP\archive\` theo quy tắc "chỉ giữ bản mới nhất, zip bản cũ lại").
- Sau đó cài Client 2.0 lên máy client thứ hai bằng cùng bộ cài (máy client thứ hai lúc này đã có MangoMCP 0.14.2 + Client 1.1.5 dở dang — cắt sang tương tự).
- Giữ lại khả năng rollback: bộ cài 1.1.5 + MangoMCP 0.14.2 Full zip còn trên máy client; rollback = dừng 2.0, chạy lại 1.1.5 + Core/Agent.

### Cách kiểm chứng trên máy client mà không làm hỏng hệ đang chạy

- **Tách biệt tuyệt đối:** code 2.0 ở `C:\MangoClient2\`, config riêng, log riêng, đăng ký Server riêng (`máy-client-2.0`). Không sửa `C:\MangoMCP\` cho tới ngày cutover.
- **Tránh xung đột khi chạy song song:** máy test `máy-client-2.0` dùng **cổng tunnel khác** (vd 18768 thay vì 8768) để không đụng Core đang chạy; **tắt lock** trên máy test trong lúc chạy song song (2 LockController cùng hook sẽ đánh nhau); overlay chỉ chạy 1 bản (của hệ cũ) — máy test không khởi động overlay riêng.
- **So sánh song song:** cùng 1 lệnh gọi lên cả 2 máy (`máy client` 1.1.5 và `máy-client-2.0` 2.0), kết quả phải giống nhau (trừ những chỗ đã biết khác: user chạy lệnh là user thay vì SYSTEM).
- **Cutover có quản trị viên ngồi trước máy:** vì giai đoạn 4 (khóa) và giai đoạn 7 (cắt sang) đều cần người thật kiểm chứng mở khóa / xác nhận máy vẫn điều khiển được.

---

## 8. Quyết định cần Quản trị viên chốt (trước / trong khi gộp)

1. **MCP local cổng 8766 — giữ hay bỏ?** Gộp sâu theo yêu cầu thì **bỏ** (Server là đường duy nhất cho AI). Hệ quả: Gemini/Claude/ChatGPT mất đường nối trực tiếp vào máy; nếu Server chết thì không còn đường MCP dự phòng (chỉ còn SSH tunnel). Nếu Quản trị viên muốn giữ, Client 2.0 phải giữ lại một MCP server mini (FastMCP/uvicorn) — tăng kích thước + độ phức tạp.
2. **Mật khẩu chủ — bỏ hay giữ?** Đề xuất **bỏ** (không còn MCP local/GUI để xác thực). Giữ lại **mật khẩu khóa máy** (riêng biệt, dùng để mở khóa tại máy).
3. **Auto-logon — bắt buộc bật?** Sau khi gộp, máy chỉ online sau khi có người đăng nhập (xem §6.2). Để máy tự online sau reboot, **bắt buộc bật auto-logon** (cần mật khẩu thật cho user). Quản trị viên cần chấp nhận đánh đổi: ai ngồi trước máy cũng dùng được desktop sau khi bật máy.
4. **Nơi đặt code + Python runtime:** đề xuất thư mục mới `C:\MangoClient\` cho code + config 2.0; Python portable giữ ở `C:\MangoMCP\python` (đã có đủ package) hoặc copy sang `C:\MangoClient\python` cho gọn (tốn thêm ~200 MB đĩa, nhưng độc lập hoàn toàn). Cần chốt trước GĐ7.
5. **Kênh quản trị cấu hình từ Server:** bổ sung tool quản trị cấu hình (tạo client, cổng quyền, lock, tunnel — xem §6.4) hay chỉ làm API dashboard? Đề xuất làm tool mới (đi qua `machine_call` như tool thường) để Quản trị viên/Mango gọi được từ xa như mọi tool khác.
6. **Tên + phiên bản:** Client 2.0 (tiếp nối 1.1.5) hay đổi tên sản phẩm? Và có giữ lại tên "MangoMCP" ở đâu không (vd trong log/tên Task) để khỏi nhầm với bản cũ.

---

## Phụ lục — File đã đọc (đối chiếu)

| File | Kích thước | Đã đọc |
|---|---|---|
| `C:\MangoMCP\app\README.md` | 7.965 B | Toàn bộ |
| `C:\MangoMCP\app\RULES.md` | 9.861 B | Toàn bộ |
| `C:\MangoMCP\app\requirements.txt` | 89 B | Toàn bộ |
| `C:\MangoMCP\app\config.json` | 3.043 B | Chỉ cấu trúc key (không ghi giá trị bí mật) |
| `C:\MangoMCP\app\mango_mcp_server.py` | 291 B | Toàn bộ |
| `C:\MangoMCP\app\mango_mcp_agent.py` | 556 B | Toàn bộ |
| `C:\MangoMCP\app\MangoMCPConfig.cs` | 83.668 B | Cấu trúc class/method (không đọc hết từng dòng) |
| `C:\MangoMCP\app\mangomcp\__init__.py` | 107 B | Toàn bộ |
| `C:\MangoMCP\app\mangomcp\errors.py` | 1.471 B | Toàn bộ |
| `C:\MangoMCP\app\mangomcp\audit.py` | 1.628 B | Toàn bộ |
| `C:\MangoMCP\app\mangomcp\users.py` | 6.249 B | Toàn bộ |
| `C:\MangoMCP\app\mangomcp\autologon.py` | 6.648 B | Toàn bộ |
| `C:\MangoMCP\app\mangomcp\session.py` | 7.596 B | Toàn bộ |
| `C:\MangoMCP\app\mangomcp\agent.py` | 7.945 B | Toàn bộ |
| `C:\MangoMCP\app\mangomcp\config.py` | 20.066 B | Toàn bộ |
| `C:\MangoMCP\app\mangomcp\server.py` | 29.217 B | Toàn bộ |
| `C:\MangoMCP\app\mangomcp\backend.py` | 29.348 B | Danh sách hàm + imports (chưa đọc hết từng dòng) |
| `C:\MangoMCP\app\mangomcp\desktop.py` | 28.582 B | Danh sách hàm + docstring + `run_desktop` (chưa đọc hết từng dòng) |
| `C:\MangoMCP\app\mangomcp\uia.py` | 11.073 B | Danh sách hàm + imports (chưa đọc hết từng dòng) |
| `C:\MangoMCP\app\mangomcp\ipc.py` | 14.072 B | Phần đầu + `ControlRouter` (chưa đọc hết `AgentConnection`) |
| `C:\MangoMCP\app\mangomcp\core.py` | 50.299 B | Danh sách hàm + `CONTROL_TOOLS` + `require()` (chưa đọc hết từng dòng) |
| `C:\MangoMCP\app\mangomcp\lock.py` | 58.001 B | Docstring + ~12.000 ký tự đầu + danh sách hàm (chưa đọc hết adapter Win32 từng dòng) |
| `C:\MangoMCP\app\mangomcp\overlay.py` | 5.734 B | Toàn bộ |
| `C:\MangoMCP\app\mangomcp\tunnel.py` | 15.753 B | Toàn bộ (trừ vài dòng cuối `_load_or_create_host_key`/`run_standalone`) |
| `C:\MangoMCP\bin\agent-desktop.exe` | — | Xác nhận có file (không đọc binary) |
| `C:\MangoMCP\app\overlay\MangoOverlay.cs` | — | Xác nhận có file (chưa đọc nội dung) |
| `~/workspace/mango-server/server/mangoserver/toolgroups.py` | — | Toàn bộ (nhóm Server read/control/files/admin) |
| `~/workspace/mango-server/client/` | — | `run_client.py`, `mangoclient/agent.py` (grep), `local_mcp.py` (đầu file), `config.py` (đầu file) |

**Lưu ý về độ tin cậy:** các con số (100 tool, 67 CONTROL_TOOLS, nhóm 35/51/4/10) đã đếm trực tiếp từ code và khớp nhau. Các phần ghi "chưa đọc hết từng dòng" là phần ít ảnh hưởng tới quyết định gộp (chi tiết cài đặt trong hàm); nếu khi triển khai gặp điểm chưa rõ thì đọc bổ sung đúng chỗ đó.

# Nối Agent AI khác tới Mango Server qua MCP chuẩn

Tài liệu này dành cho **Agent AI khác** (ChatGPT, Gemini, Claude...) hoặc người
vận hành chúng: cách nối tới Mango Server để đọc và điều khiển các máy
MangoMCP đã nối vào Server — chỉ cần đúng chuẩn MCP + 1 token Bearer, không
cần cài thêm gì phía Server.

Máy chủ ví dụ trong tài liệu này: `https://your-server.example.com`
(trỏ về cổng 8443 trên máy chủ). Thay bằng host Server của bạn nếu khác.

## 0. Tóm tắt nhanh

| Mục | Giá trị |
|---|---|
| Endpoint MCP | `POST https://your-server.example.com/mcp` |
| Chuẩn | MCP Streamable HTTP, JSON-RPC 2.0, 1 response / request |
| `MCP-Protocol-Version` | `2025-06-18` |
| Xác thực | Header `Authorization: Bearer <agent-token>` (token tạo trong dashboard, tab **Token Agent**) |
| Server | `Mango Server`, version `1.1.0` |
| Tool | 5 tool: `machine_list`, `machine_status`, `machine_call`, `machine_restart`, `machine_upgrade` |

## 1. Lấy token Agent

1. Mở dashboard: `https://your-server.example.com/dashboard`, đăng nhập bằng mật khẩu
   quản trị Server.
2. Vào tab **Token Agent** → tạo token mới:
   - **Tên:** đặt theo nền tảng, vd `ChatGPT`, `Claude Desktop`, `Gemini CLI`
     — tạo **riêng từng token cho từng nền tảng** để thu hồi từng cái được.
     **Không dùng chung token toàn quyền của Quản trị viên.**
   - **Máy được chạm:** chọn `["*"]` (mọi máy) hoặc chỉ máy cần dùng.
   - **Nhóm tool:** `read` / `control` / `files` / `admin` (xem mục 4).
3. Token hiện **1 lần duy nhất** lúc tạo — lưu lại ngay. Server chỉ lưu hash,
   mất token thì tạo token mới (không lấy lại được token cũ).

Token này chỉ có quyền trên Mango Server (đọc / điều khiển máy qua Server),
không phải mật khẩu quản trị, không mở được dashboard.

## 2. Header bắt buộc cho mọi request

```http
POST /mcp HTTP/1.1
Host: your-server.example.com
Authorization: Bearer <agent-token>
Content-Type: application/json
Accept: application/json, text/event-stream
MCP-Protocol-Version: 2025-06-18
```

- Thiếu / sai token → `401 Unauthorized`.
- Quá 10 lần xác thực sai trong 5 phút từ 1 IP → `429 Too Many Requests`
  (bị chặn 5 phút).
- Mọi request là JSON-RPC 2.0: `{"jsonrpc": "2.0", "id": <so>, "method": "...",
  "params": {...}}`. Server trả 1 JSON duy nhất (`application/json`).
- Request **không có `id`** được coi là notification — Server chỉ nhận và trả
  `202` rỗng (không có body).

## 3. Luồng nối chuẩn

```
initialize → notifications/initialized → tools/list → tools/call (lặp lại)
```

### 3.1 `initialize`

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2025-06-18",
    "capabilities": {},
    "clientInfo": {"name": "ten-client-cua-ban", "version": "1.0.0"}
  }
}
```

Trả về:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2025-06-18",
    "capabilities": {"tools": {}},
    "serverInfo": {"name": "Mango Server", "version": "1.1.0"}
  }
}
```

### 3.2 `notifications/initialized` (không có `id` → Server trả 202 rỗng)

```json
{"jsonrpc": "2.0", "method": "notifications/initialized"}
```

### 3.3 `tools/list`

```json
{"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
```

Trả về 5 tool (mục 4). Sau đó gọi tool bằng `tools/call`.

### 3.4 `ping` (giữ nối — một số MCP client tự gửi)

```json
{"jsonrpc": "2.0", "id": 99, "method": "ping"}
```

Trả về `{"result": {}}`. Method lạ khác → lỗi JSON-RPC `-32601 Method not found`.

## 4. Danh sách tool (5 tool, bản 1.1)

Kết quả mỗi tool trả về dạng MCP `tools/call` chuẩn:
`{"content": [{"type": "text", "text": "<JSON>"}], "isError": false}`.
Lỗi cũng trả cùng dạng nhưng `isError: true` và JSON có
`{"error": "<MA>", "message": "..."}`.

### `machine_list` — liệt kê máy token này được chạm

- Input: `{}` (không tham số).
- Trả về: `{"machines": [...]}` — mỗi máy có `machine_id`, `name`, `version`
  (bản MangoMCP local, vd `0.14.2`), `status` (`approved` / `pending` / ...),
  `online`, `last_heartbeat`, `agent_connected`. Bản 1.1 trả thêm
  `client_version` (bản client layer, vd `1.1.0`) và `reported_tools` khi máy
  đã báo lên Server.
- Chỉ liệt kê máy nằm trong danh sách máy của token.

### `machine_status` — trạng thái chi tiết 1 máy

- Input: `{"machine_id": "<machine-id>"}` (bắt buộc).
- Trả về: bản ghi public của máy + `connected` (WebSocket client có đang nối
  Server không).
- Máy không tồn tại hoặc token không được chạm → lỗi `MACHINE_NOT_FOUND`.

### `machine_call` — gọi 1 tool MangoMCP trên 1 máy

- Input: `{"machine_id": "<machine-id>", "tool": "screenshot", "args": {}}`
  (`args` tùy chọn, mặc định `{}`).
- Chờ tối đa 60 giây, kết quả chuyển tiếp từ máy về.
- **Quyền 2 lớp** (cả 2 đều phải cho phép thì lệnh mới chạy):
  1. **Token Agent** (phía Server): máy nằm trong danh sách máy của token,
     và tool thuộc nhóm mà token có (xem bảng nhóm bên dưới).
  2. **Máy client** (phía máy con): tool nằm trong `server_allowed_tools`
     của máy đó trong `server-client.json` (mặc định chỉ 34 tool đọc + chụp
     màn hình — không cho chạy lệnh, ghi file, bấm/chuột).
- Máy chưa được Quản trị viên duyệt → `MACHINE_NOT_APPROVED`. Máy offline →
  `MACHINE_OFFLINE`. Token không đủ nhóm → `TOOL_GROUP_DENIED`.
  Tool không có trong bảng nhóm mặc định thuộc nhóm `admin` (fail-closed).

### `machine_restart` — khởi động lại máy (mới trong 1.1)

- Input: `{"machine_id": "<machine-id>", "delay_seconds": 60}`
  (`delay_seconds` tùy chọn, mặc định `60`, từ `0` đến `3600`).
- Trả về: `{"ok": true, "sent": true}` — `sent: false` khi máy đang offline
  (lệnh không tới được máy).
- **Chỉ token có nhóm `admin` mới gọi được.** Máy tự khởi động lại sau số
  giây đã cho, **không hỏi người ngồi trước máy** — chỉ dùng khi thật sự cần.

### `machine_upgrade` — đặt bản client đích để máy tự nâng cấp (mới trong 1.1)

- Input: `{"machine_id": "<machine-id>", "target_version": "1.1.0"}`
  (`target_version` tùy chọn — bỏ trống thì lấy bản gói mới nhất trên Server).
- Trả về: `{"ok": true, "target_version": "1.1.0", "sent": true}` —
  `sent: false` khi máy đang offline (lệnh nằm lại ở `target_version`, máy
  nhận khi nối lại).
- **Chỉ token có nhóm `admin` mới gọi được.** Server báo cho máy qua kênh
  điều khiển; máy tự tải gói, kiểm tra SHA-256 rồi tự áp dụng (xem
  `docs/DEPLOY-1.1.md` mục (d)). Theo dõi tiến độ bằng `machine_status`
  (`upgrade_status`: `downloading` / `applying` / `done` / `failed`).

### Bảng nhóm tool (quyền của token cho `machine_call`)

| Nhóm | Tool thuộc nhóm (ví dụ) |
|---|---|
| `read` | Chỉ đọc: `mango_status`, `system_info`, `screenshot`, `list_directory`, `read_text_file`, `list_windows`, `desktop_snapshot`, ... (34 tool mặc định của client) |
| `control` | Điều khiển: `mouse_click`, `keyboard_type`, `run_command`, `powershell`, `launch_application`, `desktop_click`, `desktop_type`, ... |
| `files` | Ghi file: `write_text_file`, `copy_file`, `move_file`, `delete_file` |
| `admin` | Quản trị máy: `control_login`, `switch_user`, `auto_logon_enable`, `registry_set`, ... + mọi tool lạ chưa có trong bảng + `machine_restart` / `machine_upgrade` |

Lời khuyên: token cho AI ngoài chỉ nên có nhóm `read` (cộng `control` nếu
thật sự cần điều khiển). Nhóm `admin` chỉ cấp cho token của Quản trị viên / Mango.

## 5. Ví dụ cấu hình theo nền tảng

Mango Server chỉ cần đúng chuẩn MCP + Bearer token — **giao diện, cách lưu
token, cách gọi tool do từng app tự quản lý**. Các ví dụ dưới là cấu hình
chuẩn của từng app; nếu app đổi UI thì làm theo UI mới của app đó, Server
không đổi gì.

### 5.1 Claude Desktop (remote MCP)

Thêm vào file cấu hình Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "mango-server": {
      "url": "https://your-server.example.com/mcp",
      "headers": {
        "Authorization": "Bearer <agent-token>"
      }
    }
  }
}
```

Khởi động lại Claude Desktop. Vào phần MCP / tool của Claude, phải thấy
5 tool `machine_*` của `mango-server`.

### 5.2 ChatGPT (MCP connector)

ChatGPT (bản có hỗ trợ MCP connector / Developer mode): vào phần cài đặt MCP
connector, thêm server mới với:

- **URL:** `https://your-server.example.com/mcp`
- **Authentication:** Bearer token — dán `<agent-token>` (token riêng cho
  ChatGPT, xem mục 1).
- Nếu ChatGPT hỏi thêm header, thêm `MCP-Protocol-Version: 2025-06-18`.

Sau khi nối, ChatGPT gọi được tool qua connector như mọi MCP server khác.

### 5.3 Gemini CLI

Thêm vào file cấu hình Gemini CLI (`~/.muse/settings.json` hoặc theo
hướng dẫn hiện tại của Gemini CLI):

```json
{
  "mcpServers": {
    "mango-server": {
      "httpUrl": "https://your-server.example.com/mcp",
      "headers": {
        "Authorization": "Bearer <agent-token>"
      }
    }
  }
}
```

Khởi động lại Gemini CLI, kiểm tra bằng lệnh `/mcp` (hoặc lệnh liệt kê MCP
server của phiên bản đang dùng) — phải thấy `mango-server` với 5 tool.

### 5.4 Ghi chú tương thích (nói thật)

- Endpoint `/mcp` của Mango Server **chỉ nhận POST** (Streamable HTTP, 1
  response JSON / request) — **không có GET SSE**. Nền tảng nào bắt buộc
  luồng SSE kiểu cũ sẽ không nối được cho tới khi Server thêm GET `/mcp`.
- Tính tương thích thực tế **chưa được kiểm chứng live trên từng nền tảng**
  (ChatGPT / Gemini / Claude Desktop) ở bản 1.1 — tài liệu này ghi đúng
  chuẩn Server đang chạy + cấu hình chuẩn của từng app. Khi thử nối thật,
  nếu app nào báo lỗi, ghi lại đúng thông báo lỗi + URL + header đã dùng để
  đối chiếu với mục 2 và 3 ở trên trước khi kết luận Server sai.

## 6. Ví dụ tối thiểu bằng curl

Thay `<agent-token>` bằng agent token thật và dùng host Server của bạn
(`https://your-server.example.com`).

```bash
# 1. initialize
curl -s -X POST "https://your-server.example.com/mcp" \
  -H "Authorization: Bearer <agent-token>" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "MCP-Protocol-Version: 2025-06-18" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl-test","version":"1.0.0"}}}'

# 2. notifications/initialized (khong co id -> 202 rong)
curl -s -o /dev/null -w "%{http_code}\n" -X POST "https://your-server.example.com/mcp" \
  -H "Authorization: Bearer <agent-token>" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "MCP-Protocol-Version: 2025-06-18" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'

# 3. tools/list — phai thay 5 tool machine_*
curl -s -X POST "https://your-server.example.com/mcp" \
  -H "Authorization: Bearer <agent-token>" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "MCP-Protocol-Version: 2025-06-18" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

# 4. tools/call — liet ke may
curl -s -X POST "https://your-server.example.com/mcp" \
  -H "Authorization: Bearer <agent-token>" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "MCP-Protocol-Version: 2025-06-18" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"machine_list","arguments":{}}}'
```

Kiểm chứng nhanh không cần token: `POST /mcp` không kèm token phải trả
`401` — nếu trả khác 401 thì endpoint đang không bật xác thực, phải dừng
lại kiểm tra Server trước khi dùng.

## 7. Mã lỗi thường gặp

| Mã / lỗi | Ý nghĩa |
|---|---|
| HTTP `401` | Thiếu / sai token, hoặc token đã bị tắt / xóa. Kiểm tra lại token trong tab Token Agent. |
| HTTP `429` | Quá 10 lần xác thực sai / 5 phút / IP — đợi 5 phút rồi thử lại với token đúng. |
| `-32601 Method not found` | Gọi method MCP Server không có (chỉ có `initialize`, `tools/list`, `tools/call`, `ping`; notification không id thì trả 202). |
| `MACHINE_NOT_FOUND` | Sai `machine_id`, hoặc token không được chạm máy đó. Lấy id đúng từ `machine_list`. |
| `MACHINE_NOT_APPROVED` | Máy chưa được Quản trị viên duyệt trên dashboard — duyệt rồi gọi lại. |
| `MACHINE_OFFLINE` | Máy không nối Server lúc này (client chết / mất mạng). Kiểm tra `client.log` trên máy con. |
| `TOOL_GROUP_DENIED` | Token thiếu nhóm tool đó, hoặc máy con chặn tool đó trong `server_allowed_tools`. |
| `UNKNOWN_TOOL` | Gọi tên tool MCP không có (chỉ có 5 tool ở mục 4). |

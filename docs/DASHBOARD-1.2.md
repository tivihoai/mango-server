# Mango Server 1.2.0 — Dashboard theo mẫu AgentPCManagement

Dashboard cập nhật theo mẫu AgentPCManagement (mẫu tham khảo bên ngoài). Thay đổi Server, KHÔNG cần
nâng cấp client để xem dashboard mới (nhưng máy client cần 2.1.4+ mới
hiện đủ CPU/RAM/GPU/ổ đĩa — client 1.1.5 chỉ hiện các trường cũ).

## Có gì mới

### 1. Dashboard giao diện mới (nền tối, giống mẫu)
- Thẻ tổng quan 7 ô: Tổng máy, Đang bật, Offline, SSH 22 mở, RDP 3389 mở,
  Lần quét cuối, Lịch sử quét.
- Bảng máy đầy đủ cột: #, Máy (tên + hostname · user), IP, Trạng thái,
  Ping, SSH, RDP, CPU (% + model + số nhân + GHz), RAM (đã dùng/tổng +
  loại + tốc độ), GPU (% + model + driver + VRAM + nhiệt độ + W),
  Ổ đĩa (từng ổ: đã dùng/tổng + thanh %).
- Tìm kiếm tên/IP, lọc (Tất cả/Đang bật/Offline/Chờ duyệt), xem dạng
  Bảng/Thẻ, tự làm mới mỗi 10 giây.
- Nút Quét ngay (chạy 1 lượt ping + stats ngay), + Thêm máy (mở tab Mã
  đăng ký), Cài đặt (mở tab Cấu hình).
- Tab: Dashboard, Báo cáo, Logs máy, Nhật ký thao tác, Mã đăng ký,
  Token Agent, Cấu hình. Các chức năng cũ (duyệt/xóa/xoay secret/scope/
  nâng cấp/khởi động lại/gửi lệnh tool, mã đăng ký, token, audit, config,
  gói client) giữ nguyên, chỉ đổi giao diện.

### 2. Monitor nền (server/mangoserver/monitor.py — mới)
- **Ping mỗi 10 giây:** ping ICMP tới `last_ip` của từng máy (lệnh `ping`
  có sẵn của hệ điều hành, không cần cài thêm) + kiểm tra cổng SSH 22 và
  RDP 3389 có mở không (kết nối TCP, timeout 1 giây).
- **Stats mỗi 5 phút:** gọi tool `system_info` của từng máy đang online +
  đã duyệt qua WebSocket (hub), lưu lại để dashboard hiện. Máy offline
  hoặc lỗi thì giữ số liệu cũ, ghi `stats_error`.
- State chỉ trong bộ nhớ (mất khi Server restart); lịch sử quét giữ 50
  lần gần nhất trong bộ nhớ. Chưa có DB lịch sử quét (mẫu có DB riêng).

### 3. API mới (dashboard)
- `GET /api/machines/overview` — gộp registry + ping + stats + counts
  (frontend poll mỗi 10 giây; stats chỉ đổi khi monitor chạy lượt 5 phút).
- `POST /api/machines/scan-now` — quét ngay 1 lượt (nút "Quét ngay").
- Các API cũ không đổi.

### 4. Client 2.x — `system_info` mở rộng (tương thích ngược)
`client-2.0/client/mangoengine/core.py`: thêm `cpu_model`, `cpu_cores`,
`cpu_ghz`, `cpu_percent`, `memory_used_gb`, `memory_detail` (từng thanh
RAM: dung lượng/tốc độ/loại/hãng), `gpu` (tên/driver/VRAM/% sử dụng),
`gpu_note`, `disks` (từng ổ: tổng/đã dùng/còn trống/filesystem).
GPU lấy qua WMI (Win32_VideoController + perf counters, dùng comtypes đã
có sẵn); % GPU chỉ lấy được khi driver hỗ trợ perf counters, nếu không
trả None + ghi chú. Nhiệt độ GPU và công suất (W) WMI không có nên luôn
None (cần NVML/ADL — SDK của hãng). Các trường cũ không đổi.

## Nhịp cập nhật
- Ping/SSH/RDP: mỗi 10 giây (monitor `_ping_pass`).
- CPU/RAM/GPU/ổ đĩa: mỗi 5 phút (monitor `_stats_pass`).
- Frontend poll `/api/machines/overview` mỗi 10 giây.

## Deploy lên VM (C:\MangoMCPServer) — làm khi Quản trị viên duyệt
1. Dừng Server đang chạy trên VM (nó chạy bằng `start_server.bat` tay;
   không có Scheduled Task tự chạy lại — xem ghi chú cũ).
2. Copy thư mục `server/` mới lên VM, đè lên `C:\MangoMCPServer\server\`
   (giữ nguyên `C:\MangoMCPServer\data\` — registry/auth/audit/packages).
   Nên backup trước: copy `C:\MangoMCPServer\server` thành
   `C:\MangoMCPServer\server-1.1-backup`.
3. Chạy lại `C:\MangoMCPServer\start_server.bat`. Kiểm tra
   `https://your-server.example.com/health` trả `{"version":"1.2.0",...}`.
4. Mở dashboard, đăng nhập, xem thẻ tổng quan + bảng máy. Máy 2.1.4 sẽ
   hiện đủ stats sau tối đa 5 phút (hoặc bấm "Quét ngay").
5. Client 2.1.4 KHÔNG cần cài lại — `system_info` mới nằm trong code
   client, nhưng client đang chạy là 2.1.4 (đã có code mới từ trước khi
   build? — xem lưu ý dưới).

**LƯU Ý QUAN TRỌNG:** `system_info` mở rộng nằm trong code client 2.x
(`client-2.0/`), nhưng gói client 2.1.4 trên kho Server + exe 2.1.4 đã
build TRƯỚC khi thêm code này. Vì vậy máy test đang chạy 2.1.4 CHƯA có `system_info`
mới — dashboard sẽ hiện CPU/RAM cơ bản (trường cũ) nhưng GPU/ổ đĩa sẽ
trống cho tới khi client được nâng cấp. Cách nâng cấp: build gói client
mới (vd 2.1.5) chứa code `system_info` mới, đưa lên kho Server, đặt
target cho máy test/máy client thứ hai (tự động cập nhật đã có từ 2.1.1). Client 1.1.5 trên
máy client cũng chỉ có trường cũ — muốn đủ stats thì nâng cấp client lên 2.x.

## Cập nhật sau 1.2.0 — đồng bộ tên máy + sửa WMI (client 2.1.5 → 2.1.7)

### Đồng bộ tên máy theo hostname
- `server/mangoserver/registry.py`: thêm `Registry.sync_name(machine_id, hostname)` — chỉ đổi tên khi hostname là chuỗi không rỗng và khác tên hiện tại, lưu xuống disk.
- `server/mangoserver/monitor.py`: `_stats_pass` gọi `sync_name` sau mỗi lượt lấy `system_info`. Tên Windows đổi (vd DESKTOP-XXXXXXX → tên máy mới) thì dashboard hiện tên mới ngay lượt quét sau, không cần enroll lại.
- Test mới: `test_registry.py::test_sync_name_from_hostname`, `test_monitor12.py::test_stats_pass_syncs_name_from_hostname` + `test_stats_pass_no_rename_when_hostname_same_or_empty`.
- **Deploy**: backup `C:\MangoMCPServer\server` rồi copy thư mục `server/` mới lên VM (giữ `data/`), restart Server như lần deploy 1.2.0.

### Client 2.1.5 → 2.1.6 → 2.1.7 (đã lên kho Server)
- **2.1.5**: `system_info` mở rộng (cpu_model/cores/ghz/percent, memory_detail, gpu, disks) nhưng WMI hỏng hoàn toàn trên máy thật vì `comtypes.client.GetObject` không còn tồn tại trong comtypes 1.4.17 → mọi field WMI trống.
- **2.1.6**: sửa `_wmi_query` dùng `CoGetObject` + đọc property qua `Properties_`; GPU usage chấp nhận chuỗi số; VRAM âm (tràn 32-bit) đổi sang không dấu; CPU cộng nhân qua các hàng. Nhưng vẫn trống trong tiến trình client (session 0 đã khởi tạo COM kiểu khác) — chỉ chạy được trong python.exe mới.
- **2.1.7 (bản đúng)**: `_wmi_query` thêm fallback PowerShell `Get-CimInstance | Select-Object | ConvertTo-Json` khi comtypes trả rỗng. Đã kiểm chứng trên máy test: dashboard overview trả đủ CPU/RAM/GPU/ổ đĩa.
- Giới hạn còn lại: nhiệt độ + công suất GPU luôn None (WMI không có); CPU % = 0.0 khi máy idle (đúng); SMBIOS type 3 (DRAM ảo VMware) hiện "Unknown"; ổ D: UDF (đĩa ảo VMware) hiện 100% đầy — là đĩa CD ảo, không phải ổ thật.
- máy client thứ hai đang OFFLINE (ngay sau khi lên 2.1.6 xong); target 2.1.7 đã đặt (sent=false) và sẽ áp dụng khi máy nối lại. máy client vẫn 1.1.5, không đặt target.

## Giới hạn đã biết
- Ping dùng `last_ip` (IP public mà Server thấy khi máy nối WebSocket).
  Máy sau NAT (máy client/máy client thứ hai/máy test ở mạng nội bộ) có thể ping không tới được nếu
  router không hỗ trợ NAT hairpin — khi đó Ping hiện "—" (trung thực,
  không phải lỗi). Tương tự, SSH 22/RDP 3389 gần như luôn "Đóng" với máy
  sau NAT vì các cổng này không mở ra internet (truy cập qua Cloudflare
  Tunnel) — mẫu AgentPCManagement hiện "Mở" vì máy của họ cùng LAN và mở
  cổng thật. Đừng ngạc nhiên khi thấy "Đóng" ở đây.
- GPU usage (%) chỉ lấy được khi driver hỗ trợ WMI perf counters; trên
  máy ảo VMware SVGA có thể không có → hiện "—". Nhiệt độ/công suất GPU
  luôn "—" (WMI không có).
- Lịch sử quét chỉ giữ trong bộ nhớ (50 lần gần nhất), mất khi Server
  restart. Chưa có DB như mẫu.
- Nhánh WMI (CPU model/GHz thật, memory_detail, GPU) chưa kiểm chứng trên
  Windows thật — cần chạy `system_info` trên máy test sau khi nâng cấp client
  để xác nhận.
- Starlette 1.10.0 (bản trong .venv) đã bỏ `add_event_handler`/`on_startup`
  — monitor khởi động qua `lifespan` (asynccontextmanager) trong app.py.
  Nếu VM cài Starlette khác bản, kiểm tra lại chỗ này khi deploy.

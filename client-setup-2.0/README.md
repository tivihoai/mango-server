# Mango Client 2.1.9 — Setup.exe

File cài đặt duy nhất cho máy Windows mới: copy 1 file
`MangoClient-Setup-2.1.9.exe` sang máy đó, nhập tài khoản + mật khẩu
(dùng để điều khiển giao diện khi cần), bấm **Cài đặt**. Client chạy
bằng SYSTEM lúc Windows khởi động nên điều khiển được bằng lệnh
cmd/powershell ngay cả khi chưa ai đăng nhập. Máy sẽ hiện pending trên
dashboard cho Quản trị viên duyệt.

## File trong thư mục này

| File | Để làm gì |
|---|---|
| `MangoClientSetup.cs` | GUI cài đặt (bản chuẩn + bản CustomHost qua `#if CUSTOM_HOST`) |
| `build_client_setup.ps1` | Build exe trên Windows (có encoding guard + version guard) |
| `install_client.ps1` | Script cài thật (chạy trong exe): runtime, code, config, Task, Uninstall |
| `uninstall_client.ps1` | Gỡ bỏ |
| `app.manifest` | Yêu cầu quyền Admin cho exe |
| `INVESTIGATION-215-217.md` | Điều tra gốc lỗi cài 2.1.5/2.1.6/2.1.7 (báo mã lỗi 1) |

## Build (trên PC1)

Mở PowerShell tại thư mục `client-setup-2.0` của repo trên PC1:

```powershell
# Bản chuẩn — C# truyền Server host mặc định để cài zero-input
powershell -ExecutionPolicy Bypass -File .\build_client_setup.ps1

# Bản CustomHost — thêm ô nhập Server host/cổng lúc cài
powershell -ExecutionPolicy Bypass -File .\build_client_setup.ps1 -CustomHost
```

Kết quả:

| Lệnh | Exe ra |
|---|---|
| (không tham số) | `MangoClient-Setup-2.1.9.exe` |
| `-CustomHost` | `MangoClient-Setup-2.1.9-CustomHost.exe` |

Cả hai bản dùng **cùng code client 2.1.9** (cùng `MangoClient-2.1.9.zip`
nhúng trong exe); chỉ khác C# được biên dịch với `/define:CUSTOM_HOST`
để hiện thêm 2 ô nhập. Kèm theo mỗi exe là SHA-256 in ra lúc build —
ghi lại để đối chiếu.

## Encoding guard + version guard + CustomHost guard (2.1.9, sau điều tra 2.1.5–2.1.7)

`build_client_setup.ps1` **dừng build ngay (throw)** nếu:

- `install_client.ps1` hoặc `uninstall_client.ps1` không phải
  **UTF-8 BOM + CRLF sạch** (thiếu BOM, có `\r\r\n`, có dòng LF đơn),
  hoặc `Parser::ParseFile()` báo lỗi. (Hồi quy 2.1.5: file nguồn trên
  PC1 bị ghi lại thành `\r\r\n`, CR=940/LF=470 — xem
  `INVESTIGATION-215-217.md`.)
- Version yêu cầu (`-Version`, mặc định `2.1.9`) không khớp ở mọi chỗ:
  `VERSION` trong `mangoclient/__init__.py` và
  `mangoengine/server_tools.py`, chuỗi `Mango Client 2.1.9` trong
  `MangoClientSetup.cs` và `install_client.ps1`, `$clientVersion`
  fallback trong `install_client.ps1`. (Lỗi 2.1.5: exe build-dir nhúng
  nhầm script 2.1.6.)
- File `.ps1` trong stage/zip khác byte-exact file nguồn (SHA-256), hoặc
  resource `MangoClient.zip` trong exe khác file zip vừa đóng gói.
- Bản CustomHost: exe không được chứa host/tên riêng cá nhân (guard quét chuỗi ASCII + UTF-16LE trong exe; có là build dừng ngay).

Kiểm chứng local (Linux, không cần PC1): cả hai file `.ps1` đều BOM +
CRLF sạch (`install_client.ps1` 29.801 byte, CR=LF=533;
`uninstall_client.ps1` 6.050 byte, CR=LF=136; không `\r\r\n`, không
dòng LF đơn). Guard chạy bằng PowerShell nên **chỉ kiểm chứng được
thật khi build trên PC1**.

## Bản CustomHost — cài vào Server khác mặc định

Dùng khi máy con cần enroll vào một Mango Server khác (vd Server test, Server mới, IP LAN).

- Lúc cài, **BẮT BUỘC nhập Server host** (để trống sẽ báo lỗi và dừng cài đặt) và **Cổng** (mặc định `8443`).
  Chỉ nhập host/IP trần — không `https://`, không `:cổng`, chưa hỗ trợ
  IPv6 ở ô này.
- Giá trị nhập được C# truyền sang `install_client.ps1` bằng tham số
  `-ServerHost` / `-ServerPort`; script ghi vào `server-client.json`
  (`server_host`, `server_port`, `use_tls=true`). Bản chuẩn truyền `-ServerHost` mặc định từ C# nên **hành vi không đổi** (cài zero-input).
- Chạy trực tiếp script cũng được:
  `.\install_client.ps1 -ServerHost "192.168.1.10" -ServerPort 8443 ...`

### Bằng chứng luồng enroll dùng đúng host đã nhập

- `client-2.0/client/mangoclient/config.py:109-113` —
  `server_enroll_request_url` dựng URL từ `server_host` /
  `server_port` / `use_tls` đọc từ `server-client.json`:
  `{scheme}://{server_host}:{server_port}/api/enroll-request`.
- `client-2.0/client/mangoclient/agent.py:95` — `enroll_by_url(config, ...)`
  POST tới đúng URL đó, không dùng host hardcode nào khác.
- `client-2.0/client/run_client.py` — khi máy chưa enroll thì gọi
  `enroll_by_url(cfg, ...)`; `ServerLink` sau đó nối WebSocket tới
  `server_ws_url` (`config.py:100-102`), cũng dựng từ cùng 3 trường.
- Vậy máy cài bằng bản CustomHost sẽ enroll (pending) lên đúng Server
  đã nhập, rồi Quản trị viên duyệt trên dashboard của Server đó.

## Cài trên máy mới (Quản trị viên / người cài)

1. Copy file exe (chuẩn hoặc CustomHost) sang máy mới, nhấp đúp (bấm Yes
   nếu hỏi quyền Admin).
2. Nhập **tên tài khoản + mật khẩu** dùng để điều khiển giao diện khi
   cần. (Bản CustomHost: nhập thêm Server host/cổng trước.)
3. Bấm **Cài đặt**, đợi chạy xong. Mở dashboard của Server, tìm máy ở
   mục chờ duyệt, bấm Duyệt.

## Trạng thái

- Code 2.1.9 (chuẩn + CustomHost) trong repo; build trên PC1, test trên máy test trước khi phát hành (bản chuẩn cài zero-input, bản CustomHost nhập host tay + để trống host phải lỗi rõ ràng).

"""Client 1.1 layer cho MangoMCP 0.14.x — nối máy ra Mango Server.

Chạy như 1 tiến trình riêng bên cạnh Core 0.14.x (không sửa code 0.14.x):
- Enrollment 1 lần: đổi mã đăng ký lấy credential máy bền vững, lưu vào
  server-client.json (file RIÊNG, không đụng config.json của MangoMCP).
- WebSocket ra Server: heartbeat ~30s, tự nối lại khi rớt (backoff).
- Nhận lệnh machine_call từ Server, kiểm tra scope riêng của máy rồi
  thực thi bằng tool MangoMCP 0.14.x qua MCP loopback local
  (http://127.0.0.1:8766/mcp), trả kết quả về Server.
- Server sập/mất nối: client vẫn chạy local bình thường, đường trực tiếp
  Cloudflare cũ vẫn dùng được (fallback, xem DESIGN-SERVER-10.md §8).

LUẬT CỨNG: mật khẩu Windows (auto-logon) và mật khẩu chủ KHÔNG BAO GIỜ
rời khỏi máy — không gửi lên Server, không đi qua WebSocket. File
server-client.json chỉ chứa: địa chỉ Server, machine_id + secret của máy,
danh sách tool Server được gọi, URL MCP local. Không có mật khẩu nào khác.
"""
VERSION = "2.1.9"

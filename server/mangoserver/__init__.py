"""Mango Server 1.2 — package chính của Server.

Server chạy trên máy ảo Windows 10 (thư mục C:\\MangoMCPServer\\), cổng
mặc định 8443 (HTTP local — TLS do Cloudflare Tunnel lo), 1 tiến trình
duy nhất phục vụ: MCP endpoint (/mcp), WebSocket cho client (/ws),
dashboard web (/dashboard + /api/*).

Mới ở 1.2.0: dashboard theo mẫu AgentPCManagement (thẻ tổng quan, bảng
máy đầy đủ CPU/RAM/GPU/ổ đĩa, tab Dashboard/Báo cáo/Logs máy/Nhật ký),
monitor nền ping mỗi 10s + stats (system_info) mỗi 5 phút.
"""
VERSION = "1.2.1"

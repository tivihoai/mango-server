"""MCP endpoint của Mango Server 1.0 (Streamable HTTP, tự triển JSON-RPC).

Vì cần lấy identity của Agent từ header Bearer cho từng request để kiểm
tra phạm vi (máy nào + nhóm tool nào), endpoint này tự triển JSON-RPC
tối giản thay vì dùng FastMCP (tool của FastMCP không lấy được Bearer
identity một cách trực tiếp). Giao thức tương thích với client MCP chuẩn:
client gửi POST JSON-RPC, Server trả 1 JSON (application/json) — đúng
chuẩn Streamable HTTP (single response).

Methods:
- initialize -> {protocolVersion, capabilities:{tools:{}}, serverInfo}
- notifications/initialized -> 202 (không trả body)
- tools/list -> danh sách 3 tool: machine_list, machine_status, machine_call
- tools/call -> điều phối qua Router (kiểm tra quyền rồi chuyển tiếp WS)

Xác thực: header Authorization: Bearer <agent-token>. Sai/thiếu -> 401.
Giới hạn tốc độ: quá 10 lần xác thực sai trong 5 phút từ 1 IP -> 429.
"""
import json
import time

from starlette.responses import JSONResponse, Response

from . import toolgroups
from .hub import CallError

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "Mango Server"
SERVER_VERSION = "1.1.0"

TOOLS = [
    {
        "name": "machine_list",
        "description": "Liet ke cac may ma token nay duoc phep thay (ten, ma may, ban, online/offline, trang thai duyet).",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "machine_status",
        "description": "Trang thai chi tiet cua 1 may (ban, uptime qua heartbeat, Agent co dang noi khong, online/offline).",
        "inputSchema": {
            "type": "object",
            "properties": {"machine_id": {"type": "string"}},
            "required": ["machine_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "machine_call",
        "description": "Goi 1 tool MangoMCP tren 1 may (chuyen tiep qua WebSocket, cho toi da 60s). Chi goi duoc tool thuoc nhom ma token co va may da duyet.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "machine_id": {"type": "string"},
                "tool": {"type": "string"},
                "args": {"type": "object", "default": {}},
            },
            "required": ["machine_id", "tool"],
            "additionalProperties": False,
        },
    },
    {
        "name": "machine_restart",
        "description": "Khoi dong lai 1 may sau so giay cho truoc (mac dinh 60s). Chi token co quyen admin moi goi duoc. Tra {ok, sent} (sent=false khi may offline).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "machine_id": {"type": "string"},
                "delay_seconds": {"type": "integer", "default": 60},
            },
            "required": ["machine_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "machine_upgrade",
        "description": "Dat ban client dich cho 1 may (mac dinh la goi moi nhat trong kho). Server gui lenh nang cap qua WebSocket neu may online; may offline se nhan khi noi lai. Chi token co quyen admin moi goi duoc. Tra {ok, target_version, sent}.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "machine_id": {"type": "string"},
                "target_version": {"type": "string"},
            },
            "required": ["machine_id"],
            "additionalProperties": False,
        },
    },
]


def _text_result(payload, is_error: bool = False):
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "isError": is_error,
    }


def _tool_error(code: str, message: str):
    return _text_result({"error": code, "message": message}, is_error=True)


class Router:
    """Điều phối tools/call. Tách riêng khỏi HTTP để test unit được mà
    không cần chạy server thật."""

    def __init__(self, registry, hub, audit_log, packages=None):
        self.registry = registry
        self.hub = hub
        self.audit = audit_log
        self.packages = packages  # PackageStore (1.1) hoặc None

    def _token_may_see(self, token_record, machine_id: str) -> bool:
        allowed = token_record.get("machines", []) if token_record else []
        return "*" in allowed or machine_id in allowed

    def _token_has_admin(self, token_record, machine_id: str):
        """Kiểm tra token có quyền admin trên máy này không (dùng cho
        machine_restart / machine_upgrade). Trả (allowed, reason)."""
        if not token_record or not token_record.get("enabled", True):
            return False, "AGENT_TOKEN_DISABLED"
        if not self._token_may_see(token_record, machine_id):
            return False, "MACHINE_NOT_ALLOWED"
        if "admin" not in (token_record.get("tool_groups", []) or []):
            return False, "TOOL_GROUP_DENIED"
        return True, ""

    async def call(self, token_record, name: str, arguments: dict):
        """Thực thi 1 tool MCP với quyền của token_record.
        Trả dict theo định dạng MCP tools/call result."""
        token_name = (token_record or {}).get("name", "unknown")
        if name == "machine_list":
            machines = [
                m for m in self.registry.list_public()
                if self._token_may_see(token_record, m["machine_id"])
            ]
            self.audit.append("mcp.machine_list", actor=f"agent:{token_name}",
                              count=len(machines), ok=True)
            return _text_result({"machines": machines})

        if name == "machine_status":
            machine_id = (arguments or {}).get("machine_id", "")
            rec = self.registry.get(machine_id)
            if rec is None or not self._token_may_see(token_record, machine_id):
                self.audit.append("mcp.machine_status", actor=f"agent:{token_name}",
                                  machine_id=machine_id, ok=False, error_code="MACHINE_NOT_FOUND")
                return _tool_error("MACHINE_NOT_FOUND", f"Khong tim thay may {machine_id}")
            pub = self.registry.public(rec)
            pub["connected"] = self.hub.is_connected(machine_id)
            self.audit.append("mcp.machine_status", actor=f"agent:{token_name}",
                              machine_id=machine_id, ok=True)
            return _text_result(pub)

        if name == "machine_call":
            machine_id = (arguments or {}).get("machine_id", "")
            tool = (arguments or {}).get("tool", "")
            args = (arguments or {}).get("args", {}) or {}
            # 1. Token có được gọi tool này trên máy này không.
            allowed, reason = toolgroups.token_may_call(token_record, machine_id, tool)
            if not allowed:
                self.audit.append("mcp.machine_call", actor=f"agent:{token_name}",
                                  machine_id=machine_id, tool=tool, ok=False,
                                  error_code=reason)
                return _tool_error(reason, f"Token khong duoc phep: {reason}")
            # 2. Máy có tồn tại không.
            rec = self.registry.get(machine_id)
            if rec is None:
                self.audit.append("mcp.machine_call", actor=f"agent:{token_name}",
                                  machine_id=machine_id, tool=tool, ok=False,
                                  error_code="MACHINE_NOT_FOUND")
                return _tool_error("MACHINE_NOT_FOUND", f"Khong tim thay may {machine_id}")
            # 3. Máy đã được Quản trị viên duyệt chưa.
            if rec.get("status") != "approved":
                self.audit.append("mcp.machine_call", actor=f"agent:{token_name}",
                                  machine_id=machine_id, tool=tool, ok=False,
                                  error_code="MACHINE_NOT_APPROVED")
                return _tool_error("MACHINE_NOT_APPROVED",
                                   f"May {machine_id} chua duoc duyet (trang thai: {rec.get('status')})")
            # 4. Máy có online không.
            if not self.hub.is_connected(machine_id) or not self.registry.is_online(rec):
                self.audit.append("mcp.machine_call", actor=f"agent:{token_name}",
                                  machine_id=machine_id, tool=tool, ok=False,
                                  error_code="MACHINE_OFFLINE")
                return _tool_error("MACHINE_OFFLINE", f"May {machine_id} khong online")
            # 5. Chuyển tiếp qua WebSocket, chờ tối đa 60s.
            try:
                result = await self.hub.call(machine_id, tool, args)
            except CallError as exc:
                self.audit.append("mcp.machine_call", actor=f"agent:{token_name}",
                                  machine_id=machine_id, tool=tool, ok=False,
                                  error_code=exc.code)
                return _tool_error(exc.code, exc.message)
            self.audit.append("mcp.machine_call", actor=f"agent:{token_name}",
                              machine_id=machine_id, tool=tool, ok=True)
            if isinstance(result, dict) and "content" in result:
                return result
            return _text_result(result if isinstance(result, dict) else {"result": result})

        if name == "machine_restart":
            machine_id = (arguments or {}).get("machine_id", "")
            try:
                delay = int((arguments or {}).get("delay_seconds", 60))
            except (TypeError, ValueError):
                return _tool_error("INVALID_ARGUMENT", "delay_seconds phai la so nguyen")
            if not 0 <= delay <= 3600:
                return _tool_error("INVALID_ARGUMENT",
                                   "delay_seconds phai tu 0 den 3600")
            allowed, reason = self._token_has_admin(token_record, machine_id)
            if not allowed:
                self.audit.append("mcp.machine_restart", actor=f"agent:{token_name}",
                                  machine_id=machine_id, ok=False, error_code=reason)
                return _tool_error(reason, f"Token khong duoc phep: {reason}")
            rec = self.registry.get(machine_id)
            if rec is None:
                self.audit.append("mcp.machine_restart", actor=f"agent:{token_name}",
                                  machine_id=machine_id, ok=False,
                                  error_code="MACHINE_NOT_FOUND")
                return _tool_error("MACHINE_NOT_FOUND", f"Khong tim thay may {machine_id}")
            sent = await self.hub.send_restart(machine_id, delay)
            self.audit.append("mcp.machine_restart", actor=f"agent:{token_name}",
                              machine_id=machine_id, delay_seconds=delay,
                              sent=sent, ok=True)
            return _text_result({"ok": True, "sent": sent})

        if name == "machine_upgrade":
            machine_id = (arguments or {}).get("machine_id", "")
            target_version = (arguments or {}).get("target_version") or None
            allowed, reason = self._token_has_admin(token_record, machine_id)
            if not allowed:
                self.audit.append("mcp.machine_upgrade", actor=f"agent:{token_name}",
                                  machine_id=machine_id, ok=False, error_code=reason)
                return _tool_error(reason, f"Token khong duoc phep: {reason}")
            ok, res = await apply_upgrade_target(
                self.registry, self.hub, self.packages, machine_id, target_version)
            if not ok:
                self.audit.append("mcp.machine_upgrade", actor=f"agent:{token_name}",
                                  machine_id=machine_id, ok=False,
                                  error_code=res["error"])
                return _tool_error(res["error"], res["message"])
            self.audit.append("mcp.machine_upgrade", actor=f"agent:{token_name}",
                              machine_id=machine_id,
                              target_version=res["target_version"],
                              sent=res["sent"], ok=True)
            return _text_result({"ok": True,
                                 "target_version": res["target_version"],
                                 "sent": res["sent"]})

        return _tool_error("UNKNOWN_TOOL", f"Khong co tool {name}")


async def apply_upgrade_target(registry, hub, packages, machine_id,
                               target_version=None):
    """Đặt target_version cho máy + gửi upgrade_available ngay nếu máy
    online (§4.2 bước 2). Dùng chung cho dashboard API và MCP tool
    machine_upgrade. Trả (ok, result): result chứa target_version/sent
    khi ok, hoặc error/message khi lỗi."""
    rec = registry.get(machine_id)
    if rec is None:
        return False, {"error": "MACHINE_NOT_FOUND",
                       "message": f"Khong tim thay may {machine_id}"}
    if target_version:
        pkg = packages.get(target_version) if packages is not None else None
        if pkg is None:
            return False, {"error": "PACKAGE_NOT_FOUND",
                           "message": f"Khong co goi client {target_version} trong kho"}
        target = str(target_version)
    else:
        if packages is None:
            return False, {"error": "NO_PACKAGES",
                           "message": "Kho goi chua duoc cau hinh"}
        pkg = packages.latest()
        if pkg is None:
            return False, {"error": "NO_PACKAGES",
                           "message": "Chua co goi client nao trong kho"}
        target = str(pkg["version"])
    registry.set_target_version(machine_id, target)
    pkg = packages.get(target) if packages is not None else None
    sent = False
    if pkg is not None:
        sent = await hub.send_upgrade_available(
            machine_id, pkg["version"], pkg.get("sha256", ""),
            int(pkg.get("size", 0)), bool(pkg.get("requires_restart", False)))
    return True, {"target_version": target, "sent": sent}


class AuthFailLimiter:
    """Giới hạn tốc độ xác thực sai theo IP: quá 10 lần trong 5 phút
    thì chặn 5 phút (trả 429). Đơn giản, lưu trong bộ nhớ."""

    def __init__(self, max_failures: int = 10, window_seconds: int = 300,
                 block_seconds: int = 300):
        self.max_failures = max_failures
        self.window = window_seconds
        self.block = block_seconds
        self._failures = {}  # ip -> [ts, ...]
        self._blocked_until = {}  # ip -> ts

    def is_blocked(self, ip: str) -> bool:
        now = time.time()
        until = self._blocked_until.get(ip, 0)
        if now < until:
            return True
        fails = [t for t in self._failures.get(ip, []) if now - t < self.window]
        self._failures[ip] = fails
        return False

    def record_failure(self, ip: str) -> None:
        now = time.time()
        fails = [t for t in self._failures.get(ip, []) if now - t < self.window]
        fails.append(now)
        self._failures[ip] = fails
        if len(fails) >= self.max_failures:
            self._blocked_until[ip] = now + self.block


def make_mcp_handler(auth_store, router, limiter):
    """Trả về hàm xử lý Starlette cho POST /mcp."""

    async def handle_mcp(request):
        client_ip = request.client.host if request.client else "unknown"
        if limiter.is_blocked(client_ip):
            return JSONResponse({"error": "too_many_requests",
                                 "message": "Qua nhieu lan xac thuc sai, thu lai sau"},
                                status_code=429)
        auth = request.headers.get("authorization", "")
        token = ""
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
        agent = auth_store.verify_agent_token(token) if token else None
        if agent is None:
            limiter.record_failure(client_ip)
            return JSONResponse(
                {"error": "unauthorized",
                 "message": "Use Authorization: Bearer <agent-token>"},
                status_code=401)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"jsonrpc": "2.0", "id": None,
                 "error": {"code": -32700, "message": "Parse error"}},
                status_code=400)
        if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
            return JSONResponse(
                {"jsonrpc": "2.0", "id": body.get("id") if isinstance(body, dict) else None,
                 "error": {"code": -32600, "message": "Invalid Request"}},
                status_code=400)
        method = body.get("method", "")
        req_id = body.get("id")
        # Notification (không có id): chỉ nhận, trả 202 rỗng.
        if req_id is None:
            return Response(status_code=202)

        def ok(result):
            return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": result})

        def err(code, message):
            return JSONResponse({"jsonrpc": "2.0", "id": req_id,
                                 "error": {"code": code, "message": message}})

        if method == "ping":
            return ok({})
        if method == "initialize":
            return ok({
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            })
        if method == "tools/list":
            return ok({"tools": TOOLS})
        if method == "tools/call":
            params = body.get("params", {}) or {}
            result = await router.call(agent, params.get("name", ""),
                                       params.get("arguments", {}) or {})
            return ok(result)
        return err(-32601, f"Method not found: {method}")

    return handle_mcp

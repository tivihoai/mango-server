"""Hub kết nối WebSocket: giữ các máy đang nối tới Server và chuyển tiếp
lệnh gọi tool (machine_call) tới đúng máy, chờ kết quả tối đa 60s.

Giao thức WS (JSON, mỗi dòng 1 message):
- Client -> Server: {"type": "auth", "machine_id", "secret"}
  Server -> Client: {"type": "welcome", "machine_id", "status"}
                     hoặc {"type": "error", "error": "..."} rồi đóng nối.
- Client -> Server: {"type": "heartbeat", "version", "agent_connected"}
  Server -> Client: {"type": "heartbeat_ack", "server_time"}
- Server -> Client: {"type": "call", "call_id", "tool", "args"}
  Client -> Server: {"type": "result", "call_id", "ok": true,
                     "result": {...}} hoặc {"ok": false, "error": "..."}
- Server -> Client: {"type": "admin", "action": "disconnect"|"status",
                     "message": "..."}
- Client -> Server: {"type": "bye"} (ngắt lịch sự).

Mỗi lời gọi có call_id duy nhất; hub giữ dict call_id -> Future để
machine_call await kết quả. Timeout mặc định 60s.
"""
import asyncio
import itertools
import json
import time

CALL_TIMEOUT_SECONDS = 60.0


class CallError(Exception):
    """Lỗi khi chuyển tiếp lời gọi tới máy (offline/timeout/từ chối)."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


class MachineHub:
    """Giữ websocket của từng máy + các lời gọi đang chờ."""

    def __init__(self):
        self._connections = {}   # machine_id -> websocket
        self._pending = {}       # call_id -> asyncio.Future
        self._counter = itertools.count(1)
        self._lock = asyncio.Lock()

    async def register(self, machine_id: str, websocket) -> None:
        async with self._lock:
            old = self._connections.get(machine_id)
            if old is not None and old is not websocket:
                try:
                    await old.close(code=4000, reason="replaced_by_new_connection")
                except Exception:
                    pass
            self._connections[machine_id] = websocket

    async def unregister(self, machine_id: str, websocket) -> None:
        async with self._lock:
            if self._connections.get(machine_id) is websocket:
                del self._connections[machine_id]

    def is_connected(self, machine_id: str) -> bool:
        return machine_id in self._connections

    def connected_machines(self):
        return list(self._connections.keys())

    async def _send(self, machine_id: str, payload: dict) -> bool:
        """Gửi 1 message JSON tới máy đang nối. Trả False nếu máy offline
        hoặc gửi lỗi."""
        ws = self._connections.get(machine_id)
        if ws is None:
            return False
        try:
            await ws.send_text(json.dumps(payload))
            return True
        except Exception:
            return False

    async def send_admin(self, machine_id: str, action: str, message: str = "") -> bool:
        return await self._send(machine_id, {
            "type": "admin", "action": action, "message": message})

    async def send_apply_scope(self, machine_id: str, scope) -> bool:
        """Bảo client áp dụng scope mới ngay (Nấc 2, §2.3)."""
        return await self._send(machine_id, {
            "type": "admin", "action": "apply_scope", "scope": list(scope)})

    async def send_upgrade_available(self, machine_id: str, version: str,
                                     sha256: str, size: int,
                                     requires_restart: bool = False) -> bool:
        """Báo client có gói nâng cấp (§4.2 bước 2)."""
        return await self._send(machine_id, {
            "type": "upgrade_available", "version": version,
            "sha256": sha256, "size": int(size),
            "requires_restart": bool(requires_restart)})

    async def send_restart(self, machine_id: str, delay_seconds: int = 60) -> bool:
        """Bảo client khởi động lại máy sau `delay_seconds` (§4.5)."""
        return await self._send(machine_id, {
            "type": "admin", "action": "restart_machine",
            "delay_seconds": int(delay_seconds)})

    async def call(self, machine_id: str, tool: str, args, timeout: float = CALL_TIMEOUT_SECONDS):
        """Gửi 1 lời gọi tool tới máy, chờ kết quả. Trả dict result của
        máy (đúng định dạng MCP như khi gọi trực tiếp). Hết timeout hoặc
        máy không nối thì raise CallError."""
        ws = self._connections.get(machine_id)
        if ws is None:
            raise CallError("MACHINE_OFFLINE", f"May {machine_id} khong online")
        call_id = f"c{next(self._counter)}-{int(time.time() * 1000)}"
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._pending[call_id] = fut
        try:
            await ws.send_text(json.dumps(
                {"type": "call", "call_id": call_id, "tool": tool, "args": args or {}}))
        except Exception as exc:
            self._pending.pop(call_id, None)
            raise CallError("MACHINE_OFFLINE", f"Khong gui duoc lenh toi may: {exc}")
        try:
            result = await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(call_id, None)
            raise CallError("CALL_TIMEOUT", f"May khong tra loi trong {timeout:g}s")
        return result

    def handle_result(self, message: dict) -> bool:
        """Máy trả kết quả: đánh thức Future đang chờ. Trả True nếu có
        lời gọi đang chờ call_id này."""
        call_id = message.get("call_id")
        fut = self._pending.pop(call_id, None) if call_id else None
        if fut is None or fut.done():
            return False
        if message.get("ok"):
            fut.set_result(message.get("result", {}))
        else:
            fut.set_exception(CallError(
                str(message.get("error_code") or "MACHINE_ERROR"),
                str(message.get("error") or "May bao loi")))
        return True

"""Test tích hợp E2E 1.1 (chạy Server thật trên cổng local tạm).

Luồng test (không cần máy Windows thật, không cần tunnel):
1. Enroll máy giả BẰNG URL (/api/enroll-request, không cần mã) -> pending.
2. Duyệt máy trên dashboard.
3. Upload gói client 1.1.0 lên kho.
4. Máy giả nối WS, heartbeat báo client_version 1.0.0 + allowed_tools.
5. GET scope -> reported đúng; POST scope -> máy nhận admin apply_scope
   ngay, heartbeat sau báo scope mới, ack hết desired_scope.
6. POST upgrade (mặc định bản mới nhất) -> máy nhận upgrade_available,
   gửi upgrade_status downloading; heartbeat báo client_version 1.1.0
   -> Server xóa target_version, upgrade_status = done.
7. POST restart -> máy nhận admin restart_machine (delay 120).
8. MCP machine_restart qua token toàn quyền -> sent=true.
9. Audit không chứa secret.
"""
import asyncio
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import unittest

import httpx
import websockets

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client"))

from mangoserver.app import build_app

PORT = 18778
BASE = f"http://127.0.0.1:{PORT}"
FAKE_ZIP = b"PK\x03\x04FAKE-ZIP-CLIENT-1.1.0"


class FakeMachine11(threading.Thread):
    """Máy giả 1.1: nối WS, heartbeat kèm client_version + allowed_tools,
    áp dụng scope khi nhận admin apply_scope, báo upgrade_status khi nhận
    upgrade_available."""

    def __init__(self, machine_id, secret):
        super().__init__(daemon=True)
        self.machine_id = machine_id
        self.secret = secret
        self.loop = None
        self.welcome = None
        self.acks = []
        self.upgrade_available = []
        self.admin_msgs = []
        self.calls = []
        self.client_version = "1.0.0"
        self.allowed_tools = ["mango_status", "screenshot", "system_info"]
        self.error = None
        self.stop_flag = threading.Event()

    async def _run(self):
        try:
            async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws",
                                          max_size=1024 * 1024) as ws:
                self.ws = ws
                await ws.send(json.dumps(
                    {"type": "auth", "machine_id": self.machine_id,
                     "secret": self.secret}))
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
                self.welcome = json.loads(raw)
                await self._send_heartbeat(ws)
                while not self.stop_flag.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=2)
                    except asyncio.TimeoutError:
                        await self._send_heartbeat(ws)
                        continue
                    msg = json.loads(raw)
                    mtype = msg.get("type")
                    if mtype == "heartbeat_ack":
                        self.acks.append(msg)
                    elif mtype == "upgrade_available":
                        self.upgrade_available.append(msg)
                        await ws.send(json.dumps({
                            "type": "upgrade_status",
                            "version": msg.get("version"),
                            "status": "downloading"}))
                    elif mtype == "call":
                        self.calls.append((msg.get("tool"), msg.get("args")))
                        await ws.send(json.dumps({
                            "type": "result", "call_id": msg.get("call_id"),
                            "ok": True,
                            "result": {"content": [{"type": "text",
                                                    "text": "may-gia-11-ok"}],
                                       "isError": False},
                        }))
                    elif mtype == "admin":
                        self.admin_msgs.append(msg)
                        if msg.get("action") == "apply_scope":
                            # Client 1.1 áp dụng scope ngay rồi báo lại ở
                            # heartbeat sau.
                            self.allowed_tools = list(msg.get("scope") or [])
                        if msg.get("action") == "disconnect":
                            return
        except Exception as exc:  # noqa: BLE001 - ghi lại để test assert
            self.error = exc

    async def _send_heartbeat(self, ws):
        await ws.send(json.dumps(
            {"type": "heartbeat", "version": "0.14.2",
             "agent_connected": True,
             "client_version": self.client_version,
             "allowed_tools": list(self.allowed_tools)}))

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._run())

    def stop(self):
        self.stop_flag.set()
        self.join(timeout=5)


class TestIntegration11(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.app = build_app(cls.tmp)
        cls.app.state.auth.set_admin_password("test-admin-password")
        _, cls.boss_token = cls.app.state.auth.create_agent_token(
            "Admin", ["*"], ["read", "control", "files", "admin"])
        import uvicorn
        config = uvicorn.Config(cls.app, host="127.0.0.1", port=PORT,
                                log_level="error")
        cls.server = uvicorn.Server(config)
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                r = httpx.get(f"{BASE}/health", timeout=2, trust_env=False)
                if r.status_code == 200:
                    return
            except Exception:
                time.sleep(0.3)
        raise RuntimeError("Server khong khoi dong duoc")

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=10)

    def _login(self):
        c = httpx.Client(base_url=BASE, timeout=10, trust_env=False)
        r = c.post("/api/login", json={"password": "test-admin-password"})
        self.assertEqual(r.status_code, 200)
        return c

    def _mcp_call(self, token, name, arguments):
        r = httpx.post(f"{BASE}/mcp", trust_env=False, json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": arguments}},
            headers={"Authorization": f"Bearer {token}"}, timeout=30)
        self.assertEqual(r.status_code, 200, r.text[:300])
        return r.json()["result"]

    def _wait(self, cond, timeout=15, what="dieu kien"):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if cond():
                return True
            time.sleep(0.2)
        self.fail(f"Het gio cho {what}")

    def test_full_flow_11(self):
        http = self._login()
        # 1. Enroll bằng URL (không cần mã đăng ký).
        r = httpx.post(f"{BASE}/api/enroll-request", trust_env=False, json={
            "machine_name": "PC-11", "version": "0.14.2",
            "client_version": "1.0.0",
            "allowed_tools": ["mango_status", "screenshot", "system_info"]},
            timeout=10)
        self.assertEqual(r.status_code, 200)
        machine_id = r.json()["machine_id"]
        secret = r.json()["secret"]
        self.assertEqual(r.json()["status"], "pending")
        # 2. Duyệt máy.
        r = http.post(f"/api/machines/{machine_id}/approve", json={})
        self.assertEqual(r.status_code, 200)
        # 3. Upload gói client 1.1.0.
        r = http.post("/api/packages",
                      files={"file": ("client-1.1.0.zip", FAKE_ZIP,
                                      "application/zip")},
                      data={"version": "1.1.0", "requires_restart": "false",
                            "note": "goi test e2e"})
        self.assertEqual(r.status_code, 200, r.text[:300])
        self.assertEqual(r.json()["package"]["sha256"],
                         hashlib.sha256(FAKE_ZIP).hexdigest())
        # 4. Máy giả nối WS + heartbeat 1.1.
        machine = FakeMachine11(machine_id, secret)
        machine.start()
        self._wait(lambda: machine.welcome is not None, what="may gia noi WS")
        self.assertEqual(machine.welcome.get("status"), "approved")
        self.assertIsNone(machine.error)
        try:
            # 5. Scope: GET thấy reported; POST desired -> máy nhận ngay.
            r = http.get(f"/api/machines/{machine_id}/scope")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["reported_tools"],
                             ["mango_status", "screenshot", "system_info"])
            self.assertEqual(r.json()["effective_scope"],
                             ["mango_status", "screenshot", "system_info"])
            r = http.post(f"/api/machines/{machine_id}/scope",
                          json={"desired_scope": ["mango_status", "screenshot"]})
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.json()["sent"])
            self._wait(
                lambda: any(m.get("action") == "apply_scope"
                            for m in machine.admin_msgs),
                what="may nhan apply_scope")
            scope_msg = [m for m in machine.admin_msgs
                         if m.get("action") == "apply_scope"][-1]
            self.assertEqual(scope_msg["scope"], ["mango_status", "screenshot"])
            # Heartbeat sau báo scope mới -> registry đổi reported, ack
            # tiếp theo hết desired_scope (vì reported == desired).
            self._wait(
                lambda: self.app.state.registry.get(machine_id).get(
                    "reported_tools") == ["mango_status", "screenshot"],
                what="registry thay reported_tools moi")
            time.sleep(0.5)  # chờ ack của chính heartbeat đó về tới máy
            self.assertTrue(machine.acks)
            self.assertIsNone(machine.acks[-1].get("desired_scope"))
            # 6. Nâng cấp: đặt bản đích -> máy nhận upgrade_available.
            r = http.post(f"/api/machines/{machine_id}/upgrade", json={})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["target_version"], "1.1.0")
            self.assertTrue(r.json()["sent"])
            self._wait(lambda: len(machine.upgrade_available) >= 1,
                       what="may nhan upgrade_available")
            up = machine.upgrade_available[-1]
            self.assertEqual(up["version"], "1.1.0")
            self.assertEqual(up["sha256"], hashlib.sha256(FAKE_ZIP).hexdigest())
            self.assertEqual(up["size"], len(FAKE_ZIP))
            # Máy báo downloading -> registry ghi nhận.
            self._wait(
                lambda: self.app.state.registry.get(machine_id).get(
                    "upgrade_status") == "downloading",
                what="upgrade_status downloading")
            # Heartbeat tiếp theo vẫn còn target -> ack có upgrade.
            self._wait(
                lambda: any(a.get("upgrade") and
                            a["upgrade"]["version"] == "1.1.0"
                            for a in machine.acks),
                what="ack co upgrade")
            # Máy "nâng cấp xong, chạy lại" với client_version mới.
            machine.client_version = "1.1.0"
            self._wait(
                lambda: self.app.state.registry.get(machine_id).get(
                    "target_version") is None
                and self.app.state.registry.get(machine_id).get(
                    "upgrade_status") == "done",
                what="Server xoa target + status done")
            self.assertEqual(
                self.app.state.registry.get(machine_id)["client_version"],
                "1.1.0")
            # 7. Khởi động lại máy.
            r = http.post(f"/api/machines/{machine_id}/restart",
                          json={"delay_seconds": 120})
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.json()["sent"])
            self._wait(
                lambda: any(m.get("action") == "restart_machine"
                            for m in machine.admin_msgs),
                what="may nhan restart_machine")
            restart_msg = [m for m in machine.admin_msgs
                           if m.get("action") == "restart_machine"][-1]
            self.assertEqual(restart_msg["delay_seconds"], 120)
            # 8. MCP machine_restart qua token toàn quyền -> sent=true.
            res = self._mcp_call(self.boss_token, "machine_restart", {
                "machine_id": machine_id, "delay_seconds": 30})
            self.assertFalse(res["isError"])
            self.assertIn('"sent": true', res["content"][0]["text"])
            # 9. Audit không chứa secret.
            r = http.get("/api/audit?limit=100")
            self.assertEqual(r.status_code, 200)
            blob = json.dumps(r.json()["entries"])
            self.assertNotIn(secret, blob)
        finally:
            machine.stop()


if __name__ == "__main__":
    unittest.main()

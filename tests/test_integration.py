"""Test tích hợp end-to-end (chạy Server thật trên cổng local tạm).

Luồng test (không cần máy Windows thật, không cần tunnel):
1. Khởi động Server thật (uvicorn trong thread) trên 127.0.0.1:18777.
2. Tạo mã đăng ký -> enroll máy giả -> máy ở trạng thái pending.
3. Máy giả nối WebSocket, gửi heartbeat.
4. Gọi machine_call khi máy còn pending -> MACHINE_NOT_APPROVED.
5. Duyệt máy trên dashboard -> gọi machine_call -> máy giả trả kết quả.
6. Token chỉ đọc gọi run_command -> TOOL_GROUP_DENIED.
7. Kiểm tra audit không chứa secret.
"""
import asyncio
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

PORT = 18777
BASE = f"http://127.0.0.1:{PORT}"


class FakeMachine(threading.Thread):
    """Máy giả chạy trong thread riêng: nối WS, heartbeat, trả lời call."""

    def __init__(self, machine_id, secret, result_text="may-gia-ok"):
        super().__init__(daemon=True)
        self.machine_id = machine_id
        self.secret = secret
        self.result_text = result_text
        self.loop = None
        self.calls = []
        self.welcome = None
        self.stop_flag = threading.Event()

    async def _run(self):
        try:
            async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws",
                                          max_size=1024 * 1024) as ws:
                await ws.send(json.dumps(
                    {"type": "auth", "machine_id": self.machine_id,
                     "secret": self.secret}))
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
                self.welcome = json.loads(raw)
                # Gui heartbeat ngay sau khi noi (giong client that).
                await ws.send(json.dumps(
                    {"type": "heartbeat", "version": "0.14.2",
                     "agent_connected": True}))
                while not self.stop_flag.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=2)
                    except asyncio.TimeoutError:
                        await ws.send(json.dumps(
                            {"type": "heartbeat", "version": "0.14.2",
                             "agent_connected": True}))
                        continue
                    msg = json.loads(raw)
                    if msg.get("type") == "call":
                        self.calls.append((msg.get("tool"), msg.get("args")))
                        await ws.send(json.dumps({
                            "type": "result", "call_id": msg.get("call_id"),
                            "ok": True,
                            "result": {"content": [{"type": "text",
                                                    "text": self.result_text}],
                                       "isError": False},
                        }))
                    elif msg.get("type") == "admin":
                        if msg.get("action") == "disconnect":
                            return
        except Exception as exc:  # noqa: BLE001 - ghi lại để test assert
            self.error = exc

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._run())

    def stop(self):
        self.stop_flag.set()
        self.join(timeout=5)


class TestIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.app = build_app(cls.tmp)
        cls.app.state.auth.set_admin_password("test-admin-password")
        _, cls.boss_token = cls.app.state.auth.create_agent_token(
            "Admin", ["*"], ["read", "control", "files", "admin"])
        _, cls.read_token = cls.app.state.auth.create_agent_token(
            "chi-doc", ["*"], ["read"])
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

    def _mcp_call(self, token, name, arguments):
        r = httpx.post(f"{BASE}/mcp", trust_env=False, json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": arguments}},
            headers={"Authorization": f"Bearer {token}"}, timeout=30)
        self.assertEqual(r.status_code, 200, r.text[:300])
        # Trả result dict MCP (content/isError); caller tự đọc text.
        return r.json()["result"]

    def _mcp_text(self, result):
        return result["content"][0]["text"]

    def _login(self):
        c = httpx.Client(base_url=BASE, timeout=10, trust_env=False)
        r = c.post("/api/login", json={"password": "test-admin-password"})
        self.assertEqual(r.status_code, 200)
        return c

    def test_full_flow(self):
        http = self._login()
        # 1. Tạo mã đăng ký.
        r = http.post("/api/enrollment", json={"label": "may-test"})
        self.assertEqual(r.status_code, 200)
        enroll_token = r.json()["token"]
        # 2. Enroll máy giả.
        r = httpx.post(f"{BASE}/api/enroll", trust_env=False, json={
            "enrollment_token": enroll_token, "machine_name": "PC-test",
            "version": "0.14.2"}, timeout=10)
        self.assertEqual(r.status_code, 200)
        machine_id = r.json()["machine_id"]
        secret = r.json()["secret"]
        self.assertEqual(r.json()["status"], "pending")
        # 3. Máy giả nối WS + heartbeat.
        machine = FakeMachine(machine_id, secret)
        machine.start()
        deadline = time.time() + 15
        while machine.welcome is None and time.time() < deadline:
            time.sleep(0.2)
        self.assertIsNotNone(machine.welcome, "May gia khong noi duoc WS")
        self.assertEqual(machine.welcome.get("status"), "pending")
        try:
            # 4. Gọi khi còn pending -> bị từ chối.
            res = self._mcp_call(self.boss_token, "machine_call", {
                "machine_id": machine_id, "tool": "mango_status", "args": {}})
            self.assertTrue(res["isError"])
            self.assertIn("MACHINE_NOT_APPROVED", self._mcp_text(res))
            # 5. Duyệt máy, gọi lại -> thành công, kết quả từ máy giả.
            r = http.post(f"/api/machines/{machine_id}/approve", json={})
            self.assertEqual(r.status_code, 200)
            res = self._mcp_call(self.boss_token, "machine_call", {
                "machine_id": machine_id, "tool": "mango_status", "args": {}})
            self.assertFalse(res["isError"])
            self.assertIn("may-gia-ok", self._mcp_text(res))
            self.assertEqual(machine.calls, [("mango_status", {})])
            # machine_list thấy máy, machine_status thấy online.
            res = self._mcp_call(self.boss_token, "machine_list", {})
            out = json.loads(self._mcp_text(res))
            self.assertEqual(len(out["machines"]), 1)
            self.assertTrue(out["machines"][0]["online"])
            res = self._mcp_call(self.boss_token, "machine_status", {"machine_id": machine_id})
            out = json.loads(self._mcp_text(res))
            self.assertTrue(out["online"])
            self.assertTrue(out["connected"])
            # 6. Token chỉ đọc gọi run_command -> bị chặn.
            res = self._mcp_call(self.read_token, "machine_call", {
                "machine_id": machine_id, "tool": "run_command",
                "args": {"command": "dir"}})
            self.assertTrue(res["isError"])
            self.assertIn("TOOL_GROUP_DENIED", self._mcp_text(res))
            self.assertEqual(len(machine.calls), 1)  # không hề tới máy
            # 7. Audit có ghi, không chứa secret.
            r = http.get("/api/audit?limit=50")
            self.assertEqual(r.status_code, 200)
            blob = json.dumps(r.json()["entries"])
            self.assertNotIn(secret, blob)
            self.assertNotIn(enroll_token, blob)
            self.assertIn("mcp.machine_call", blob)
        finally:
            machine.stop()


if __name__ == "__main__":
    unittest.main()

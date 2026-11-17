"""Test HTTP cho MCP endpoint + dashboard (Starlette TestClient, chạy
app thật trên thư mục data tạm, không cần mạng/tunnel)."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from starlette.testclient import TestClient

from mangoserver.app import build_app


def _client():
    tmp = tempfile.mkdtemp()
    app = build_app(tmp)
    # Đặt mật khẩu quản trị + token Agent toàn quyền để test.
    app.state.auth.set_admin_password("test-admin-password")
    _, token = app.state.auth.create_agent_token(
        "test-agent", ["*"], ["read", "control", "files", "admin"])
    return TestClient(app), token, tmp


def _mcp(client, token, method, params=None, req_id=1):
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    body = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
    return client.post("/mcp", json=body, headers=headers)


class TestMcpHttp(unittest.TestCase):
    def test_health_no_auth(self):
        client, _, _ = _client()
        r = client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")
        self.assertEqual(r.json()["version"], "1.2.1")

    def test_mcp_requires_bearer(self):
        client, _, _ = _client()
        r = _mcp(client, None, "tools/list")
        self.assertEqual(r.status_code, 401)
        r = _mcp(client, "sai", "tools/list")
        self.assertEqual(r.status_code, 401)

    def test_initialize_and_tools_list(self):
        client, token, _ = _client()
        r = _mcp(client, token, "initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "t", "version": "1"}})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["result"]["serverInfo"]["name"], "Mango Server")
        self.assertEqual(body["result"]["protocolVersion"], "2025-06-18")
        r = _mcp(client, token, "tools/list", req_id=2)
        names = [t["name"] for t in r.json()["result"]["tools"]]
        self.assertEqual(names, ["machine_list", "machine_status", "machine_call",
                                  "machine_restart", "machine_upgrade"])

    def test_machine_list_empty_then_enrolled(self):
        client, token, _ = _client()
        r = _mcp(client, token, "tools/call", {
            "name": "machine_list", "arguments": {}}, req_id=3)
        payload = json.loads(r.json()["result"]["content"][0]["text"])
        self.assertEqual(payload["machines"], [])

    def test_unknown_method(self):
        client, token, _ = _client()
        r = _mcp(client, token, "khong_co_method")
        self.assertIn("error", r.json())

    def test_rate_limit_blocks_after_failures(self):
        client, _, _ = _client()
        for _ in range(11):
            _mcp(client, "sai", "tools/list")
        r = _mcp(client, "sai", "tools/list")
        self.assertEqual(r.status_code, 429)


class TestDashboardHttp(unittest.TestCase):
    def _login(self, client, password="test-admin-password"):
        return client.post("/api/login", json={"password": password})

    def test_login_wrong_then_right(self):
        client, _, _ = _client()
        r = self._login(client, "sai")
        self.assertEqual(r.status_code, 401)
        r = self._login(client)
        self.assertEqual(r.status_code, 200)
        self.assertIn("ms_session", r.cookies)

    def test_api_requires_login(self):
        client, _, _ = _client()
        r = client.get("/api/machines")
        self.assertEqual(r.status_code, 401)
        self._login(client)
        r = client.get("/api/machines")
        self.assertEqual(r.status_code, 200)

    def test_dashboard_page_served(self):
        client, _, _ = _client()
        r = client.get("/dashboard")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Mango Server", r.text)
        self.assertIn("Đăng nhập", r.text)

    def test_enroll_and_approve_flow(self):
        client, _, _ = _client()
        # Tạo mã đăng ký (cần login).
        self._login(client)
        r = client.post("/api/enrollment", json={"label": "may-01"})
        self.assertEqual(r.status_code, 200)
        enroll_token = r.json()["token"]
        # Máy enroll (public, không cần session) -> pending.
        r2 = client.post("/api/enroll", json={
            "enrollment_token": enroll_token, "machine_name": "may-01",
            "version": "0.14.2"})
        self.assertEqual(r2.status_code, 200)
        body = r2.json()
        self.assertEqual(body["status"], "pending")
        machine_id = body["machine_id"]
        secret = body["secret"]
        # Mã đã dùng rồi thì không enroll được nữa.
        r3 = client.post("/api/enroll", json={
            "enrollment_token": enroll_token, "machine_name": "PC-khac",
            "version": "0.14.2"})
        self.assertEqual(r3.status_code, 401)
        # Duyệt máy trên dashboard.
        r4 = client.post(f"/api/machines/{machine_id}/approve", json={})
        self.assertEqual(r4.status_code, 200)
        self.assertEqual(r4.json()["machine"]["status"], "approved")
        # Secret xoay được.
        r5 = client.post(f"/api/machines/{machine_id}/rotate-secret", json={})
        self.assertEqual(r5.status_code, 200)
        self.assertNotEqual(r5.json()["secret"], secret)

    def test_agent_token_crud(self):
        client, _, _ = _client()
        self._login(client)
        r = client.post("/api/agent-tokens", json={
            "name": "Agent-moi", "machines": ["m1"], "tool_groups": ["read"]})
        self.assertEqual(r.status_code, 200)
        token = r.json()["token"]
        self.assertTrue(token.startswith("mango_agent_"))
        tid = r.json()["record"]["id"]
        r = client.get("/api/agent-tokens")
        self.assertEqual(len(r.json()["tokens"]), 2)  # token test + token mới
        r = client.post(f"/api/agent-tokens/{tid}/disable", json={})
        self.assertTrue(r.json()["ok"])
        r = client.post(f"/api/agent-tokens/{tid}/delete", json={})
        self.assertTrue(r.json()["ok"])

    def test_audit_endpoint(self):
        client, _, _ = _client()
        self._login(client)
        r = client.get("/api/audit?limit=10")
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.json()["entries"], list)


if __name__ == "__main__":
    unittest.main()

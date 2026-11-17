"""Test 1.1 — Nấc 2: quản lý scope máy (§2.1, §2.3).

Registry: update_reported / set_desired_scope / set_target_version /
set_upgrade_status / public() có field mới.
HTTP: GET/POST /api/machines/{id}/scope.
WS: heartbeat báo client_version + allowed_tools, heartbeat_ack trả
desired_scope khi đã đặt và khác reported (client 1.0 không gửi field
mới vẫn nối được).
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from starlette.testclient import TestClient

from mangoserver.app import build_app
from mangoserver.registry import Registry
from mangoserver.store import JsonStore


def _registry():
    tmp = tempfile.mkdtemp()
    return Registry(JsonStore(os.path.join(tmp, "registry.json"), {"machines": {}}))


def _client():
    tmp = tempfile.mkdtemp()
    app = build_app(tmp)
    app.state.auth.set_admin_password("test-admin-password")
    return TestClient(app), app


def _enrolled_machine(app, name="may-01"):
    r = app.state.registry.enroll(name, "0.14.2", "secret-1", "mango_test1")
    return r["machine_id"]


class TestRegistryScope(unittest.TestCase):
    def test_enroll_defaults_new_fields(self):
        reg = _registry()
        rec = reg.enroll("may-01", "0.14.2", "s", "mango_abc")
        self.assertEqual(rec["client_version"], "")
        self.assertEqual(rec["reported_tools"], [])
        self.assertIsNone(rec["desired_scope"])
        self.assertIsNone(rec["target_version"])
        self.assertEqual(rec["upgrade_status"], "")
        self.assertEqual(rec["upgrade_status_at"], 0)
        self.assertEqual(rec["last_seen_scope_at"], 0)

    def test_update_reported(self):
        reg = _registry()
        reg.enroll("may-01", "0.14.2", "s", "mango_abc")
        rec = reg.update_reported("mango_abc", "1.1.0", ["mango_status"])
        self.assertEqual(rec["client_version"], "1.1.0")
        self.assertEqual(rec["reported_tools"], ["mango_status"])
        self.assertGreater(rec["last_seen_scope_at"], 0)
        # Client 1.0 không gửi field mới -> giữ nguyên giá trị cũ.
        rec = reg.update_reported("mango_abc", None, None)
        self.assertEqual(rec["client_version"], "1.1.0")
        self.assertEqual(rec["reported_tools"], ["mango_status"])
        self.assertIsNone(reg.update_reported("mango_khong-co", "1.1.0", []))

    def test_set_desired_scope(self):
        reg = _registry()
        reg.enroll("may-01", "0.14.2", "s", "mango_abc")
        self.assertTrue(reg.set_desired_scope("mango_abc", ["mango_status"]))
        self.assertEqual(reg.get("mango_abc")["desired_scope"], ["mango_status"])
        # Scope rỗng [] = cấm hết — cho phép.
        self.assertTrue(reg.set_desired_scope("mango_abc", []))
        self.assertEqual(reg.get("mango_abc")["desired_scope"], [])
        for bad in ("mango_status", [""], ["  "], [123], [None], {"a": 1}):
            with self.assertRaises(ValueError, msg=f"scope={bad!r}"):
                reg.set_desired_scope("mango_abc", bad)
        self.assertFalse(reg.set_desired_scope("mango_khong-co", ["x"]))

    def test_set_target_version_and_upgrade_status(self):
        reg = _registry()
        reg.enroll("may-01", "0.14.2", "s", "mango_abc")
        self.assertTrue(reg.set_target_version("mango_abc", "1.1.0"))
        self.assertEqual(reg.get("mango_abc")["target_version"], "1.1.0")
        self.assertTrue(reg.set_target_version("mango_abc", None))
        self.assertIsNone(reg.get("mango_abc")["target_version"])
        self.assertFalse(reg.set_target_version("mango_khong-co", "1.1.0"))
        for status in ("downloading", "applying", "done", "failed", "restarting"):
            self.assertTrue(reg.set_upgrade_status("mango_abc", status))
            self.assertEqual(reg.get("mango_abc")["upgrade_status"], status)
            self.assertGreater(reg.get("mango_abc")["upgrade_status_at"], 0)
        self.assertFalse(reg.set_upgrade_status("mango_abc", "la"))
        self.assertFalse(reg.set_upgrade_status("mango_khong-co", "done"))

    def test_public_includes_new_fields_no_secret(self):
        reg = _registry()
        reg.enroll("may-01", "0.14.2", "s", "mango_abc")
        reg.update_reported("mango_abc", "1.1.0", ["mango_status"])
        reg.set_desired_scope("mango_abc", ["screenshot"])
        reg.set_target_version("mango_abc", "1.2.0")
        pub = reg.public(reg.get("mango_abc"))
        self.assertEqual(pub["client_version"], "1.1.0")
        self.assertEqual(pub["reported_tools"], ["mango_status"])
        self.assertEqual(pub["desired_scope"], ["screenshot"])
        self.assertEqual(pub["target_version"], "1.2.0")
        self.assertNotIn("secret_sha256", pub)
        self.assertNotIn("secret", json.dumps(pub))

    def test_machines_with_target(self):
        reg = _registry()
        reg.enroll("may-01", "0.14.2", "s", "m1")
        reg.enroll("may-02", "0.14.2", "s", "m2")
        reg.set_target_version("m1", "1.1.0")
        self.assertEqual(reg.machines_with_target("1.1.0"), ["m1"])
        self.assertEqual(reg.machines_with_target("9.9.9"), [])


class TestScopeApi(unittest.TestCase):
    def _login(self, client):
        client.post("/api/login", json={"password": "test-admin-password"})

    def test_scope_requires_login(self):
        client, app = _client()
        mid = _enrolled_machine(app)
        r = client.get(f"/api/machines/{mid}/scope")
        self.assertEqual(r.status_code, 401)
        r = client.post(f"/api/machines/{mid}/scope", json={"desired_scope": []})
        self.assertEqual(r.status_code, 401)

    def test_scope_get_set_flow(self):
        client, app = _client()
        self._login(client)
        mid = _enrolled_machine(app)
        app.state.registry.update_reported(mid, "1.1.0",
                                           ["mango_status", "screenshot"])
        r = client.get(f"/api/machines/{mid}/scope")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["reported_tools"], ["mango_status", "screenshot"])
        self.assertIsNone(body["desired_scope"])
        self.assertEqual(body["effective_scope"], ["mango_status", "screenshot"])
        self.assertGreater(body["reported_at"], 0)
        # Đặt desired_scope khác reported -> effective đổi theo desired.
        r = client.post(f"/api/machines/{mid}/scope",
                        json={"desired_scope": ["mango_status"]})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertEqual(r.json()["machine"]["desired_scope"], ["mango_status"])
        r = client.get(f"/api/machines/{mid}/scope")
        self.assertEqual(r.json()["effective_scope"], ["mango_status"])
        # Scope rỗng = cấm hết.
        r = client.post(f"/api/machines/{mid}/scope", json={"desired_scope": []})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(client.get(f"/api/machines/{mid}/scope").json()["effective_scope"], [])

    def test_scope_set_validation(self):
        client, app = _client()
        self._login(client)
        mid = _enrolled_machine(app)
        for bad in ({}, {"desired_scope": "mango_status"},
                    {"desired_scope": [""]}, {"desired_scope": [123]}):
            r = client.post(f"/api/machines/{mid}/scope", json=bad)
            self.assertEqual(r.status_code, 400, f"body={bad!r}")
        r = client.post("/api/machines/mango_khong-co/scope",
                        json={"desired_scope": ["x"]})
        self.assertEqual(r.status_code, 404)
        r = client.get("/api/machines/mango_khong-co/scope")
        self.assertEqual(r.status_code, 404)


class TestHeartbeatScopeWs(unittest.TestCase):
    def test_heartbeat_ack_desired_scope(self):
        client, app = _client()
        mid = _enrolled_machine(app)
        app.state.registry.set_desired_scope(mid, ["mango_status", "screenshot"])
        with client.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps(
                {"type": "auth", "machine_id": mid, "secret": "secret-1"}))
            welcome = json.loads(ws.receive_text())
            self.assertEqual(welcome["type"], "welcome")
            # Heartbeat 1.1: báo client_version + allowed_tools.
            ws.send_text(json.dumps(
                {"type": "heartbeat", "version": "0.14.2",
                 "agent_connected": True, "client_version": "1.1.0",
                 "allowed_tools": ["mango_status"]}))
            ack = json.loads(ws.receive_text())
            self.assertEqual(ack["type"], "heartbeat_ack")
            # desired_scope đã đặt và khác reported -> gửi về.
            self.assertEqual(ack["desired_scope"], ["mango_status", "screenshot"])
            self.assertIsNone(ack["upgrade"])
            rec = app.state.registry.get(mid)
            self.assertEqual(rec["client_version"], "1.1.0")
            self.assertEqual(rec["reported_tools"], ["mango_status"])
            # Heartbeat tiếp theo báo đúng scope mong muốn -> không gửi nữa.
            ws.send_text(json.dumps(
                {"type": "heartbeat", "version": "0.14.2",
                 "agent_connected": True, "client_version": "1.1.0",
                 "allowed_tools": ["mango_status", "screenshot"]}))
            ack2 = json.loads(ws.receive_text())
            self.assertIsNone(ack2["desired_scope"])

    def test_heartbeat_old_client_compat(self):
        client, app = _client()
        mid = _enrolled_machine(app)
        with client.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps(
                {"type": "auth", "machine_id": mid, "secret": "secret-1"}))
            self.assertEqual(json.loads(ws.receive_text())["type"], "welcome")
            # Client 1.0: heartbeat cũ, không có client_version/allowed_tools.
            ws.send_text(json.dumps(
                {"type": "heartbeat", "version": "0.14.2",
                 "agent_connected": True}))
            ack = json.loads(ws.receive_text())
            self.assertEqual(ack["type"], "heartbeat_ack")
            self.assertIsNone(ack["desired_scope"])
            self.assertIsNone(ack["upgrade"])
            rec = app.state.registry.get(mid)
            self.assertEqual(rec["client_version"], "")
            self.assertEqual(rec["reported_tools"], [])


if __name__ == "__main__":
    unittest.main()

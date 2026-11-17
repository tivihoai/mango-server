"""Test 1.1 — Nấc 1: tab Cấu hình (GET /api/config, đổi mật khẩu,
đổi hạn mã đăng ký) + settings enrollment TTL trong auth.json."""
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
    app.state.auth.set_admin_password("test-admin-password")
    return TestClient(app), app, tmp


class TestConfigApi(unittest.TestCase):
    def _login(self, client, password="test-admin-password"):
        return client.post("/api/login", json={"password": password})

    def test_config_requires_login(self):
        client, _, _ = _client()
        r = client.get("/api/config")
        self.assertEqual(r.status_code, 401)

    def test_config_fields(self):
        client, app, tmp = _client()
        self._login(client)
        r = client.get("/api/config")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["version"], "1.2.1")
        self.assertEqual(body["host"], "127.0.0.1")
        self.assertEqual(body["port"], 8443)
        self.assertEqual(body["data_dir"], tmp)
        self.assertIn("uptime_seconds", body)
        self.assertIn("started_at", body)
        self.assertEqual(body["machines_total"], 0)
        self.assertEqual(body["machines_online"], 0)
        self.assertEqual(body["machines_pending"], 0)
        self.assertEqual(body["agent_tokens_total"], 0)
        self.assertEqual(body["enrollment_ttl_seconds"], 86400)
        self.assertTrue(body["admin_password_set"])

    def test_change_password_wrong_current(self):
        client, _, _ = _client()
        self._login(client)
        r = client.post("/api/config/change-password", json={
            "current_password": "sai", "new_password": "mat-khau-moi"})
        self.assertEqual(r.status_code, 401)

    def test_change_password_too_short(self):
        client, _, _ = _client()
        self._login(client)
        r = client.post("/api/config/change-password", json={
            "current_password": "test-admin-password", "new_password": "abc"})
        self.assertEqual(r.status_code, 400)

    def test_change_password_ok_then_login_with_new(self):
        client, _, _ = _client()
        self._login(client)
        r = client.post("/api/config/change-password", json={
            "current_password": "test-admin-password", "new_password": "mat-khau-moi"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        # Mật khẩu cũ hết hiệu lực, mật khẩu mới đăng nhập được.
        r = self._login(client, "test-admin-password")
        self.assertEqual(r.status_code, 401)
        r = self._login(client, "mat-khau-moi")
        self.assertEqual(r.status_code, 200)

    def test_enrollment_ttl_validation(self):
        client, _, _ = _client()
        self._login(client)
        for bad in (59, 2592001, 0, -5, "abc", None):
            r = client.post("/api/config/enrollment-ttl", json={"seconds": bad})
            self.assertEqual(r.status_code, 400, f"seconds={bad!r}")
        for good in (60, 3600, 2592000):
            r = client.post("/api/config/enrollment-ttl", json={"seconds": good})
            self.assertEqual(r.status_code, 200, f"seconds={good!r}")
            self.assertEqual(r.json()["enrollment_ttl_seconds"], good)
            r = client.get("/api/config")
            self.assertEqual(r.json()["enrollment_ttl_seconds"], good)

    def test_enrollment_ttl_affects_new_token(self):
        client, app, _ = _client()
        self._login(client)
        client.post("/api/config/enrollment-ttl", json={"seconds": 3600})
        token = app.state.auth.create_enrollment_token("test")
        recs = app.state.auth.store.data["enrollment_tokens"]
        rec = recs[-1]
        self.assertEqual(rec["expires_at"] - rec["created_at"], 3600)
        # Token thô không được lưu trong file.
        raw = open(app.state.auth.store.path, encoding="utf-8").read()
        self.assertNotIn(token, raw)

    def test_auth_store_ttl_defaults_and_persistence(self):
        _, app, tmp = _client()
        self.assertEqual(app.state.auth.get_enrollment_ttl(), 86400)
        app.state.auth.set_enrollment_ttl(7200)
        # Đọc lại từ file: settings đã lưu bền.
        from mangoserver.auth import AuthStore
        from mangoserver.store import JsonStore
        again = AuthStore(JsonStore(os.path.join(tmp, "auth.json"), {}))
        self.assertEqual(again.get_enrollment_ttl(), 7200)
        with self.assertRaises(ValueError):
            app.state.auth.set_enrollment_ttl(30)


if __name__ == "__main__":
    unittest.main()

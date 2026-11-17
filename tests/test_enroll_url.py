"""Test 1.1 — Enroll bằng URL (§3.1): POST /api/enroll-request public,
rate-limit riêng, máy pending, secret chỉ trả 1 lần. Enroll cũ bằng mã
đăng ký vẫn chạy."""
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
    app.state.auth.set_admin_password("test-admin-password")
    return TestClient(app), app


class TestEnrollRequest(unittest.TestCase):
    def _login(self, client):
        return client.post("/api/login", json={"password": "test-admin-password"})

    def test_enroll_request_ok(self):
        client, app = _client()
        r = client.post("/api/enroll-request", json={
            "machine_name": "PC-moi", "version": "0.14.2",
            "client_version": "1.1.0",
            "allowed_tools": ["mango_status", "screenshot"]})
        self.assertEqual(r.status_code, 200, r.text[:300])
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["status"], "pending")
        machine_id = body["machine_id"]
        secret = body["secret"]
        self.assertTrue(machine_id.startswith("mango_"))
        rec = app.state.registry.get(machine_id)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["status"], "pending")
        self.assertEqual(rec["client_version"], "1.1.0")
        self.assertEqual(rec["reported_tools"], ["mango_status", "screenshot"])
        # Secret thô không lưu trong registry.json; audit không chứa secret.
        raw = open(app.state.registry.store.path, encoding="utf-8").read()
        self.assertNotIn(secret, raw)
        audit_raw = open(app.state.audit.path, encoding="utf-8").read()
        self.assertNotIn(secret, audit_raw)
        self.assertIn("enroll_request.ok", audit_raw)
        # Credential dùng được để xác thực máy.
        self.assertIsNotNone(app.state.registry.verify_machine(machine_id, secret))

    def test_enroll_request_minimal_body(self):
        client, app = _client()
        r = client.post("/api/enroll-request", json={"machine_name": "PC-toi-gian"})
        self.assertEqual(r.status_code, 200)
        rec = app.state.registry.get(r.json()["machine_id"])
        self.assertEqual(rec["client_version"], "")
        self.assertEqual(rec["reported_tools"], [])

    def test_enroll_request_bad_body(self):
        # Mỗi body sai dùng app mới (limiter chặn sau 5 lần sai / IP).
        for bad in ({}, {"machine_name": ""}, {"machine_name": 123},
                    {"machine_name": "PC", "allowed_tools": "mango_status"},
                    {"machine_name": "PC", "allowed_tools": [123]},
                    {"machine_name": "PC", "client_version": 5}):
            client, _ = _client()
            r = client.post("/api/enroll-request", json=bad)
            self.assertEqual(r.status_code, 400, f"body={bad!r}")
        client, _ = _client()
        r = client.post("/api/enroll-request", content="khong-phai-json",
                        headers={"Content-Type": "application/json"})
        self.assertEqual(r.status_code, 400)

    def test_enroll_request_rate_limit(self):
        client, _ = _client()
        # 5 lần thất bại -> lần thứ 6 bị chặn 429.
        for _ in range(5):
            r = client.post("/api/enroll-request", json={})
            self.assertEqual(r.status_code, 400)
        r = client.post("/api/enroll-request", json={})
        self.assertEqual(r.status_code, 429)
        # Kể cả body đúng cũng bị chặn khi đang trong thời gian chặn.
        r = client.post("/api/enroll-request", json={"machine_name": "PC"})
        self.assertEqual(r.status_code, 429)

    def test_enroll_request_success_not_rate_limited(self):
        client, _ = _client()
        # Yêu cầu thành công không tăng bộ đếm limiter.
        for i in range(6):
            r = client.post("/api/enroll-request",
                            json={"machine_name": f"PC-{i}"})
            self.assertEqual(r.status_code, 200, f"lan {i}: {r.text[:200]}")

    def test_old_enroll_by_token_still_works(self):
        client, app = _client()
        self._login(client)
        r = client.post("/api/enrollment", json={"label": "may-01"})
        self.assertEqual(r.status_code, 200)
        enroll_token = r.json()["token"]
        r = client.post("/api/enroll", json={
            "enrollment_token": enroll_token, "machine_name": "may-01-cu",
            "version": "0.14.2"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "pending")
        # Mã đã dùng thì không enroll được nữa.
        r = client.post("/api/enroll", json={
            "enrollment_token": enroll_token, "machine_name": "PC-khac",
            "version": "0.14.2"})
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":
    unittest.main()

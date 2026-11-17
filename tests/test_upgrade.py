"""Test 1.1 — Kho gói + nâng cấp (§4.1, §4.2, §4.4, §4.5).

PackageStore + compare_versions; API upload/list/download/delete gói;
POST /api/machines/{id}/upgrade; POST /api/machines/{id}/restart.
"""
import hashlib
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from starlette.testclient import TestClient

from mangoserver.app import build_app
from mangoserver.packages import PackageStore, compare_versions
from mangoserver.store import JsonStore

FAKE_ZIP = b"PK\x03\x04FAKE-ZIP-CONTENT-1.1.0"


def _client():
    tmp = tempfile.mkdtemp()
    app = build_app(tmp)
    app.state.auth.set_admin_password("test-admin-password")
    return TestClient(app), app


def _packages(tmp=None):
    tmp = tmp or tempfile.mkdtemp()
    store = JsonStore(os.path.join(tmp, "packages.json"), {"packages": {}})
    return PackageStore(store, os.path.join(tmp, "packages"))


def _upload(client, version, data=FAKE_ZIP, filename=None, **extra):
    filename = filename or f"client-{version}.zip"
    fields = {"version": version, "requires_restart": "false",
              "note": extra.pop("note", "test")}
    fields.update(extra)
    return client.post("/api/packages",
                       files={"file": (filename, data, "application/zip")},
                       data=fields)


def _enroll_request(client, name="may-01"):
    r = client.post("/api/enroll-request", json={"machine_name": name})
    assert r.status_code == 200, r.text[:200]
    return r.json()["machine_id"], r.json()["secret"]


class TestCompareVersions(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(compare_versions("1.1.0", "1.0.0"), 1)
        self.assertEqual(compare_versions("1.0.0", "1.1.0"), -1)
        self.assertEqual(compare_versions("1.1.0", "1.1.0"), 0)
        self.assertEqual(compare_versions("1.1", "1.1.0"), 0)
        self.assertEqual(compare_versions("1.10.0", "1.9.9"), 1)
        self.assertEqual(compare_versions("2.0", "10.0"), -1)
        self.assertEqual(compare_versions("abc", "1.0"), -1)
        self.assertEqual(compare_versions("", "0.0.0"), 0)
        self.assertEqual(compare_versions("1.1.0", ""), 1)


class TestPackageStore(unittest.TestCase):
    def _record(self, version):
        return {"version": version, "filename": f"client-{version}.zip",
                "sha256": "abc", "size": 10, "requires_restart": False,
                "created_at": 1, "note": ""}

    def test_add_list_get_latest(self):
        store = _packages()
        store.add(self._record("1.0.0"))
        store.add(self._record("1.10.0"))
        store.add(self._record("1.2.0"))
        self.assertEqual([r["version"] for r in store.list()],
                         ["1.0.0", "1.2.0", "1.10.0"])
        self.assertEqual(store.get("1.2.0")["filename"], "client-1.2.0.zip")
        self.assertIsNone(store.get("9.9.9"))
        self.assertEqual(store.latest()["version"], "1.10.0")
        self.assertEqual(store.latest_newer_than("1.2.0")["version"], "1.10.0")
        self.assertEqual(store.latest_newer_than("1.10.0"), None)
        self.assertEqual(store.latest_newer_than("0.9.0")["version"], "1.10.0")

    def test_delete(self):
        tmp = tempfile.mkdtemp()
        store = _packages(tmp)
        pkg_dir = os.path.join(tmp, "packages")
        os.makedirs(pkg_dir, exist_ok=True)
        open(os.path.join(pkg_dir, "client-1.0.0.zip"), "wb").write(b"x")
        store.add(self._record("1.0.0"))
        self.assertTrue(store.delete("1.0.0"))
        self.assertIsNone(store.get("1.0.0"))
        self.assertFalse(os.path.exists(os.path.join(pkg_dir, "client-1.0.0.zip")))
        self.assertFalse(store.delete("1.0.0"))

    def test_empty_store(self):
        store = _packages()
        self.assertEqual(store.list(), [])
        self.assertIsNone(store.latest())
        self.assertIsNone(store.latest_newer_than("1.0.0"))


class TestPackagesApi(unittest.TestCase):
    def _login(self, client):
        client.post("/api/login", json={"password": "test-admin-password"})

    def test_packages_requires_login(self):
        client, _ = _client()
        self.assertEqual(client.get("/api/packages").status_code, 401)
        r = client.post("/api/packages",
                        files={"file": ("a.zip", b"x", "application/zip")},
                        data={"version": "1.0.0"})
        self.assertEqual(r.status_code, 401)

    def test_upload_list_download_delete(self):
        client, app = _client()
        self._login(client)
        r = _upload(client, "1.1.0")
        self.assertEqual(r.status_code, 200, r.text[:300])
        pkg = r.json()["package"]
        self.assertEqual(pkg["version"], "1.1.0")
        self.assertEqual(pkg["sha256"], hashlib.sha256(FAKE_ZIP).hexdigest())
        self.assertEqual(pkg["size"], len(FAKE_ZIP))
        self.assertEqual(pkg["filename"], "client-1.1.0.zip")
        r = client.get("/api/packages")
        self.assertEqual([p["version"] for p in r.json()["packages"]], ["1.1.0"])
        # Download bằng credential máy (không cần session dashboard).
        mid, secret = _enroll_request(client)
        r = client.get("/api/packages/1.1.0/download",
                       headers={"Authorization": f"Bearer {mid}.{secret}"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, FAKE_ZIP)
        self.assertIn("application/zip", r.headers["content-type"])
        # Sai secret / không auth / gói không có.
        r = client.get("/api/packages/1.1.0/download",
                       headers={"Authorization": f"Bearer {mid}.sai"})
        self.assertEqual(r.status_code, 401)
        r = client.get("/api/packages/1.1.0/download")
        self.assertEqual(r.status_code, 401)
        r = client.get("/api/packages/9.9.9/download",
                       headers={"Authorization": f"Bearer {mid}.{secret}"})
        self.assertEqual(r.status_code, 404)
        # Audit ghi download nhưng không ghi secret.
        audit_raw = open(app.state.audit.path, encoding="utf-8").read()
        self.assertIn("package.download", audit_raw)
        self.assertNotIn(secret, audit_raw)
        # Xóa gói.
        r = client.delete("/api/packages/1.1.0")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(client.get("/api/packages").json()["packages"], [])
        r = client.delete("/api/packages/1.1.0")
        self.assertEqual(r.status_code, 404)

    def test_upload_rejects_bad_filename(self):
        client, _ = _client()
        self._login(client)
        r = _upload(client, "1.1.0", filename="../evil.zip")
        self.assertEqual(r.status_code, 400)
        r = _upload(client, "1.1.0", filename="sub/dir.zip")
        self.assertEqual(r.status_code, 400)
        r = _upload(client, "1.1.0", filename="pkg.txt")
        self.assertEqual(r.status_code, 400)
        r = client.post("/api/packages",
                        files={"file": ("a.zip", b"x", "application/zip")},
                        data={})
        self.assertEqual(r.status_code, 400)

    def test_delete_blocked_when_target_version(self):
        client, app = _client()
        self._login(client)
        _upload(client, "1.1.0")
        mid, _ = _enroll_request(client)
        app.state.registry.set_target_version(mid, "1.1.0")
        r = client.delete("/api/packages/1.1.0")
        self.assertEqual(r.status_code, 409)
        app.state.registry.set_target_version(mid, None)
        r = client.delete("/api/packages/1.1.0")
        self.assertEqual(r.status_code, 200)


class TestUpgradeApi(unittest.TestCase):
    def _login(self, client):
        client.post("/api/login", json={"password": "test-admin-password"})

    def test_upgrade_requires_login_and_machine(self):
        client, _ = _client()
        r = client.post("/api/machines/mango_khong-co/upgrade", json={})
        self.assertEqual(r.status_code, 401)
        self._login(client)
        r = client.post("/api/machines/mango_khong-co/upgrade", json={})
        self.assertEqual(r.status_code, 404)

    def test_upgrade_no_packages(self):
        client, _ = _client()
        self._login(client)
        mid, _ = _enroll_request(client)
        r = client.post(f"/api/machines/{mid}/upgrade", json={})
        self.assertEqual(r.status_code, 400)
        self.assertIn("NO_PACKAGES", r.text)

    def test_upgrade_default_latest_and_explicit(self):
        client, app = _client()
        self._login(client)
        _upload(client, "1.0.0", data=b"zip-100")
        _upload(client, "1.1.0")
        mid, _ = _enroll_request(client)
        # Mặc định = gói mới nhất, máy offline nên sent=false.
        r = client.post(f"/api/machines/{mid}/upgrade", json={})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["target_version"], "1.1.0")
        self.assertFalse(r.json()["sent"])
        self.assertEqual(app.state.registry.get(mid)["target_version"], "1.1.0")
        # Chỉ định bản cũ hơn vẫn được.
        r = client.post(f"/api/machines/{mid}/upgrade",
                        json={"target_version": "1.0.0"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["target_version"], "1.0.0")
        # Bản không có trong kho -> 404.
        r = client.post(f"/api/machines/{mid}/upgrade",
                        json={"target_version": "9.9.9"})
        self.assertEqual(r.status_code, 404)


class TestRestartApi(unittest.TestCase):
    def _login(self, client):
        client.post("/api/login", json={"password": "test-admin-password"})

    def test_restart_validation(self):
        client, _ = _client()
        self._login(client)
        mid, _ = _enroll_request(client)
        for bad in (-1, 3601, "abc"):
            r = client.post(f"/api/machines/{mid}/restart",
                            json={"delay_seconds": bad})
            self.assertEqual(r.status_code, 400, f"delay={bad!r}")
        r = client.post("/api/machines/mango_khong-co/restart",
                        json={"delay_seconds": 60})
        self.assertEqual(r.status_code, 404)

    def test_restart_offline_sent_false(self):
        client, _ = _client()
        self._login(client)
        mid, _ = _enroll_request(client)
        r = client.post(f"/api/machines/{mid}/restart", json={})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertFalse(r.json()["sent"])  # máy chưa nối WS
        r = client.post(f"/api/machines/{mid}/restart",
                        json={"delay_seconds": 0})
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()

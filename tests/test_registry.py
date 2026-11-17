"""Test unit cho mangoserver.registry — enroll, duyệt, heartbeat,
online/offline, thu hồi, xoay secret."""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from mangoserver.registry import HEARTBEAT_TIMEOUT_SECONDS, Registry
from mangoserver.store import JsonStore


def _registry():
    tmp = tempfile.mkdtemp()
    store = JsonStore(os.path.join(tmp, "registry.json"), {"machines": {}})
    return Registry(store)


class TestRegistry(unittest.TestCase):
    def test_enroll_defaults_to_pending(self):
        reg = _registry()
        rec = reg.enroll("may-01", "0.14.2", "secret-123", "mango_abc")
        self.assertEqual(rec["status"], "pending")
        self.assertEqual(rec["name"], "may-01")
        # Secret thô không được lưu (chỉ hash).
        raw = open(reg.store.path, encoding="utf-8").read()
        self.assertNotIn("secret-123", raw)

    def test_verify_machine(self):
        reg = _registry()
        reg.enroll("may-01", "0.14.2", "secret-123", "mango_abc")
        self.assertIsNotNone(reg.verify_machine("mango_abc", "secret-123"))
        self.assertIsNone(reg.verify_machine("mango_abc", "sai"))
        self.assertIsNone(reg.verify_machine("mango_khac", "secret-123"))

    def test_approve_reject_revoke(self):
        reg = _registry()
        reg.enroll("may-01", "0.14.2", "s", "mango_abc")
        self.assertTrue(reg.set_status("mango_abc", "approved", by="admin"))
        self.assertEqual(reg.get("mango_abc")["status"], "approved")
        self.assertTrue(reg.get("mango_abc")["approved_at"] > 0)
        self.assertTrue(reg.set_status("mango_abc", "rejected"))
        self.assertEqual(reg.get("mango_abc")["status"], "rejected")
        self.assertTrue(reg.set_status("mango_abc", "revoked"))
        # Revoked thì xác thực thất bại.
        self.assertIsNone(reg.verify_machine("mango_abc", "s"))
        self.assertFalse(reg.set_status("mango_abc", "trang-thai-la"))
        self.assertFalse(reg.set_status("mango_khong-co", "approved"))

    def test_heartbeat_online_offline(self):
        reg = _registry()
        reg.enroll("may-01", "0.14.2", "s", "mango_abc")
        rec = reg.get("mango_abc")
        self.assertFalse(reg.is_online(rec))  # chưa heartbeat lần nào
        reg.heartbeat("mango_abc", version="0.14.2", agent_connected=True, ip="1.2.3.4")
        rec = reg.get("mango_abc")
        self.assertTrue(reg.is_online(rec))
        self.assertEqual(rec["version"], "0.14.2")
        self.assertTrue(rec["agent_connected"])
        # Gia lap qua 90s khong heartbeat.
        rec["last_heartbeat"] = int(time.time()) - HEARTBEAT_TIMEOUT_SECONDS - 1
        self.assertFalse(reg.is_online(rec))

    def test_sync_name_from_hostname(self):
        """Đồng bộ tên máy theo hostname thực tế (dashboard 1.2.x)."""
        reg = _registry()
        reg.enroll("DESKTOP-EXAMPLE01", "2.1.4", "s", "mango_pc3")
        # Hostname khác -> đổi tên, lưu xuống disk.
        self.assertTrue(reg.sync_name("mango_pc3", "may-03"))
        self.assertEqual(reg.get("mango_pc3")["name"], "may-03")
        raw = open(reg.store.path, encoding="utf-8").read()
        self.assertIn("may-03", raw)
        self.assertNotIn("DESKTOP-EXAMPLE01", raw)
        # Hostname trùng -> không đổi, trả False.
        self.assertFalse(reg.sync_name("mango_pc3", "may-03"))
        # Hostname rỗng / chỉ khoảng trắng / không phải chuỗi -> False.
        self.assertFalse(reg.sync_name("mango_pc3", ""))
        self.assertFalse(reg.sync_name("mango_pc3", "   "))
        self.assertFalse(reg.sync_name("mango_pc3", None))
        self.assertFalse(reg.sync_name("mango_pc3", 123))
        # Khoảng trắng thừa ở hai đầu bị cắt.
        self.assertTrue(reg.sync_name("mango_pc3", "  may-03-New  "))
        self.assertEqual(reg.get("mango_pc3")["name"], "may-03-New")
        # Máy không tồn tại -> False.
        self.assertFalse(reg.sync_name("mango_khong-co", "PC9"))
        # Không đổi machine_id hay trường khác.
        rec = reg.get("mango_pc3")
        self.assertEqual(rec["machine_id"], "mango_pc3")
        self.assertEqual(rec["status"], "pending")
        self.assertFalse(rec["agent_connected"])  # enroll xong chưa heartbeat

    def test_rotate_secret(self):
        reg = _registry()
        reg.enroll("may-01", "0.14.2", "cu", "mango_abc")
        self.assertTrue(reg.rotate_secret("mango_abc", "moi"))
        self.assertIsNone(reg.verify_machine("mango_abc", "cu"))
        self.assertIsNotNone(reg.verify_machine("mango_abc", "moi"))
        self.assertFalse(reg.rotate_secret("mango_khong-co", "moi"))

    def test_public_strips_secret(self):
        import json
        reg = _registry()
        reg.enroll("may-01", "0.14.2", "s", "mango_abc")
        pub = reg.public(reg.get("mango_abc"))
        self.assertNotIn("secret_sha256", pub)
        self.assertNotIn("secret-123", json.dumps(pub))
        self.assertNotIn("s", json.dumps(pub.get("secret_sha256", "")))
        self.assertEqual(pub["machine_id"], "mango_abc")
        self.assertIn("online", pub)

    def test_delete(self):
        reg = _registry()
        reg.enroll("may-01", "0.14.2", "s", "mango_abc")
        self.assertTrue(reg.delete("mango_abc"))
        self.assertIsNone(reg.get("mango_abc"))
        self.assertFalse(reg.delete("mango_abc"))


if __name__ == "__main__":
    unittest.main()

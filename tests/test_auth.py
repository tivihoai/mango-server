"""Test unit cho mangoserver.auth — mật khẩu quản trị, mã đăng ký,
token Agent. Dùng JsonStore thật trên thư mục tạm (ghi file thật)."""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from mangoserver.auth import AuthStore
from mangoserver.store import JsonStore


def _auth():
    tmp = tempfile.mkdtemp()
    store = JsonStore(os.path.join(tmp, "auth.json"), {
        "admin_password_sha256": "", "enrollment_tokens": [], "agent_tokens": [],
    })
    return AuthStore(store)


class TestAdminPassword(unittest.TestCase):
    def test_set_and_verify(self):
        auth = _auth()
        self.assertFalse(auth.admin_password_set())
        auth.set_admin_password("mat-khau-manh")
        self.assertTrue(auth.admin_password_set())
        self.assertTrue(auth.verify_admin_password("mat-khau-manh"))
        self.assertFalse(auth.verify_admin_password("sai"))
        self.assertFalse(auth.verify_admin_password(""))

    def test_short_password_rejected(self):
        auth = _auth()
        with self.assertRaises(ValueError):
            auth.set_admin_password("123")


class TestEnrollment(unittest.TestCase):
    def test_create_consume_once(self):
        auth = _auth()
        token = auth.create_enrollment_token("may-01")
        self.assertTrue(token)
        rec = auth.consume_enrollment_token(token)
        self.assertIsNotNone(rec)
        # Dùng lần 2 phải thất bại (1 lần duy nhất).
        self.assertIsNone(auth.consume_enrollment_token(token))

    def test_wrong_token_rejected(self):
        auth = _auth()
        auth.create_enrollment_token()
        self.assertIsNone(auth.consume_enrollment_token("ma-sai"))

    def test_expired_token_rejected(self):
        auth = _auth()
        token = auth.create_enrollment_token()
        # Gia han het han bang cach sua truc tiep ban ghi.
        auth.store.data["enrollment_tokens"][0]["expires_at"] = int(time.time()) - 1
        auth.store.save()
        self.assertIsNone(auth.consume_enrollment_token(token))

    def test_revoke(self):
        auth = _auth()
        token = auth.create_enrollment_token()
        digest = auth.store.data["enrollment_tokens"][0]["token_sha256"]
        self.assertTrue(auth.revoke_enrollment_token(digest))
        self.assertIsNone(auth.consume_enrollment_token(token))
        # Token thô không được lưu ở đâu trong file (chỉ hash).
        raw = open(auth.store.path, encoding="utf-8").read()
        self.assertNotIn(token, raw)

    def test_list_hides_hash(self):
        auth = _auth()
        token = auth.create_enrollment_token("may-01")
        listed = auth.list_enrollment_tokens()
        self.assertEqual(len(listed), 1)
        self.assertNotIn("token_sha256", listed[0])
        self.assertNotIn(token, str(listed))


class TestAgentToken(unittest.TestCase):
    def test_create_verify_scopes(self):
        auth = _auth()
        rec, token = auth.create_agent_token("Muse", ["*"], ["read"])
        self.assertTrue(token.startswith("mango_agent_"))
        got = auth.verify_agent_token(token)
        self.assertIsNotNone(got)
        self.assertEqual(got["name"], "Muse")
        self.assertEqual(got["machines"], ["*"])
        self.assertFalse(auth.verify_agent_token("sai"))

    def test_disable_and_delete(self):
        auth = _auth()
        rec, token = auth.create_agent_token("A", ["m1"], ["read"])
        self.assertTrue(auth.set_agent_token_enabled(rec["id"], False))
        self.assertIsNone(auth.verify_agent_token(token))
        self.assertTrue(auth.set_agent_token_enabled(rec["id"], True))
        self.assertIsNotNone(auth.verify_agent_token(token))
        self.assertTrue(auth.delete_agent_token(rec["id"]))
        self.assertIsNone(auth.verify_agent_token(token))

    def test_token_not_stored_raw(self):
        auth = _auth()
        _, token = auth.create_agent_token("A", ["*"], ["read"])
        raw = open(auth.store.path, encoding="utf-8").read()
        self.assertNotIn(token, raw)


if __name__ == "__main__":
    unittest.main()

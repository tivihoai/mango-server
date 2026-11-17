"""Test unit cho mangoserver.security — che bí mật + hash."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from mangoserver.security import hash_matches, new_token, redact, sha256, summarize_args


class TestHash(unittest.TestCase):
    def test_sha256_known_value(self):
        self.assertEqual(
            sha256("1234"),
            "03ac674216f3e15c761ee1a5e255f067953623c8b388b4459e13f978d7c846f4")

    def test_hash_matches(self):
        h = sha256("mat-khau-bi-mat")
        self.assertTrue(hash_matches("mat-khau-bi-mat", h))
        self.assertFalse(hash_matches("mat-khau-khac", h))
        self.assertFalse(hash_matches("", h))
        self.assertFalse(hash_matches("mat-khau-bi-mat", ""))

    def test_new_token_unique(self):
        tokens = {new_token() for _ in range(100)}
        self.assertEqual(len(tokens), 100)
        for t in tokens:
            self.assertNotIn(" ", t)
            self.assertNotIn("/", t)


class TestRedact(unittest.TestCase):
    def test_password_secret_token_masked(self):
        args = {"username": "admin", "password": "Abcd#$2027",
                "secret": "s3cr3t", "token": "tok123",
                "nested": {"api_token": "xyz", "keep": "yes"}}
        out = redact(args)
        self.assertEqual(out["password"], "***")
        self.assertEqual(out["secret"], "***")
        self.assertEqual(out["token"], "***")
        self.assertEqual(out["nested"]["api_token"], "***")
        self.assertEqual(out["nested"]["keep"], "yes")
        self.assertEqual(out["username"], "admin")
        # Gia tri goc khong duoc lo ra trong output JSON.
        self.assertNotIn("Abcd#$2027", str(out))
        self.assertNotIn("s3cr3t", str(out))
        self.assertNotIn("tok123", str(out))

    def test_redact_list(self):
        out = redact([{"password": "pw"}, "plain"])
        self.assertEqual(out[0]["password"], "***")
        self.assertEqual(out[1], "plain")

    def test_summarize_args_masks_and_limits(self):
        s = summarize_args({"password": "r4t-d4i", "tool": "x" * 500})
        self.assertNotIn("r4t-d4i", s)
        self.assertLessEqual(len(s), 200)


if __name__ == "__main__":
    unittest.main()

import unittest

from server.operator_auth import OperatorAuth, hash_password, safe_next_url, verify_password
from tools.setup_operator_password import configure_auth


class OperatorAuthUnitTest(unittest.TestCase):
    def test_password_hash_round_trip(self):
        encoded = hash_password("a sufficiently long password", iterations=100_000, salt=b"0123456789abcdef")
        self.assertTrue(verify_password("a sufficiently long password", encoded))
        self.assertFalse(verify_password("wrong password", encoded))
        self.assertNotIn("sufficiently", encoded)

    def test_signed_session_expires_and_rejects_tampering(self):
        auth = OperatorAuth({
            "enabled": True,
            "password_hash": hash_password("operator password", iterations=100_000, salt=b"0123456789abcdef"),
            "session_secret": "test-secret",
            "session_hours": 1,
        })
        token = auth.make_session_token(now=1_000)
        self.assertTrue(auth.verify_session_token(token, now=1_001))
        self.assertFalse(auth.verify_session_token(token, now=4_601))
        self.assertFalse(auth.verify_session_token(token + "x", now=1_001))

    def test_login_failure_rate_limit(self):
        auth = OperatorAuth({
            "enabled": True,
            "password_hash": hash_password("operator password", iterations=100_000, salt=b"0123456789abcdef"),
            "session_secret": "test-secret",
            "max_failures": 3,
            "failure_window_seconds": 60,
        })
        for offset in range(3):
            auth.record_failure("127.0.0.1", now=10 + offset)
        self.assertTrue(auth.is_rate_limited("127.0.0.1", now=20))
        self.assertFalse(auth.is_rate_limited("127.0.0.1", now=80))

    def test_safe_next_url_rejects_external_redirects(self):
        self.assertEqual(safe_next_url("/admin?round=1"), "/admin?round=1")
        self.assertEqual(safe_next_url("https://evil.example/path"), "/")
        self.assertEqual(safe_next_url("//evil.example/path"), "/")
        self.assertEqual(safe_next_url("/\\evil.example/path"), "/")

    def test_configure_auth_stores_no_plaintext_and_rotates_secret(self):
        config = {"operator_auth": {"session_secret": "old-secret"}}
        updated = configure_auth(config, "new secure password", session_hours=24, secure_cookie=True)
        auth_config = updated["operator_auth"]
        self.assertTrue(auth_config["enabled"])
        self.assertNotIn("new secure password", str(auth_config))
        self.assertNotEqual(auth_config["session_secret"], "old-secret")
        self.assertEqual(auth_config["session_hours"], 24)
        self.assertTrue(auth_config["secure_cookie"])


if __name__ == "__main__":
    unittest.main()

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docqa.auth import (  # noqa: E402
    AuthConfigurationError,
    DEMO_PASSWORD_HASH,
    DEMO_USERS,
    verify_password,
)


class TestAuthentication(unittest.TestCase):
    def test_demo_login_is_the_only_configured_account(self):
        self.assertEqual(set(DEMO_USERS), {"admin"})
        self.assertTrue(verify_password("123456", DEMO_USERS["admin"]))
        self.assertFalse(verify_password("wrong", DEMO_USERS["admin"]))

    def test_malformed_password_hash_is_rejected(self):
        with self.assertRaises(AuthConfigurationError):
            verify_password("123456", "plaintext")
        self.assertNotIn("123456", DEMO_PASSWORD_HASH)


if __name__ == "__main__":
    unittest.main()

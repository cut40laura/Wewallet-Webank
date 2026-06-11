"""Unit tests for auth: SMS code lifecycle and brute-force lockout.

Run from the project root:
    python3 -m unittest tests.test_auth -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ["WEWALLET_AUTH_SECRET"] = "test-secret"
# Point the SQLite database at a throwaway file so tests never touch real data.
_DB_DIR = tempfile.mkdtemp(prefix="wewallet-test-auth-")
os.environ["WEWALLET_DB"] = str(Path(_DB_DIR) / "test.sqlite")

sys.path.insert(0, str(REPO_ROOT / "ui"))

import auth  # noqa: E402
import db  # noqa: E402

PHONE = "13800138000"


class SmsCodeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        with db.transaction() as conn:
            conn.execute("DELETE FROM sms_codes")

    def _issue_code(self) -> str:
        code = auth.create_sms_code(PHONE)
        assert code is not None
        return code

    def test_correct_code_consumed_once(self) -> None:
        code = self._issue_code()
        self.assertTrue(auth.consume_sms_code(PHONE, code))
        # Single-use: the same code must not verify twice.
        self.assertFalse(auth.consume_sms_code(PHONE, code))

    def test_wrong_code_rejected(self) -> None:
        self._issue_code()
        self.assertFalse(auth.consume_sms_code(PHONE, "000000"))

    def test_code_invalidated_after_max_attempts(self) -> None:
        code = self._issue_code()
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(auth.SMS_MAX_VERIFY_ATTEMPTS):
            self.assertFalse(auth.consume_sms_code(PHONE, wrong))
        # The correct code is now burned: brute force exhausted the budget.
        self.assertFalse(auth.consume_sms_code(PHONE, code))

    def test_correct_code_within_attempt_budget_still_works(self) -> None:
        code = self._issue_code()
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(auth.SMS_MAX_VERIFY_ATTEMPTS - 1):
            self.assertFalse(auth.consume_sms_code(PHONE, wrong))
        self.assertTrue(auth.consume_sms_code(PHONE, code))

    def test_attempts_isolated_per_phone(self) -> None:
        other_phone = "13900139000"
        code = self._issue_code()
        other_code = auth.create_sms_code(other_phone)
        assert other_code is not None
        wrong = "000000" if other_code != "000000" else "111111"
        for _ in range(auth.SMS_MAX_VERIFY_ATTEMPTS):
            self.assertFalse(auth.consume_sms_code(other_phone, wrong))
        # Hammering the other phone must not burn this phone's code.
        self.assertTrue(auth.consume_sms_code(PHONE, code))

    def test_resend_cooldown(self) -> None:
        self.assertIsNotNone(auth.create_sms_code(PHONE))
        self.assertIsNone(auth.create_sms_code(PHONE))


if __name__ == "__main__":
    unittest.main()

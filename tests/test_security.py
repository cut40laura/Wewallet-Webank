"""Unit tests for the security helpers (rate limiting + CSRF origin check).

Run from the project root:
    python3 -m unittest tests.test_security -v
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ["WEWALLET_AUTH_SECRET"] = "test-secret"

sys.path.insert(0, str(REPO_ROOT / "ui"))

import security  # noqa: E402


class RateLimitTestCase(unittest.TestCase):
    def setUp(self) -> None:
        security.reset_rate_limits()
        # Local override so the test does not depend on production tuning.
        self._original = dict(security.RATE_LIMITS)
        security.RATE_LIMITS["test_bucket"] = (3, 60.0)

    def tearDown(self) -> None:
        security.RATE_LIMITS.clear()
        security.RATE_LIMITS.update(self._original)
        security.reset_rate_limits()

    def test_allows_requests_below_limit(self) -> None:
        for _ in range(3):
            self.assertTrue(security.check_rate_limit("1.1.1.1", "test_bucket"))

    def test_blocks_request_over_limit(self) -> None:
        for _ in range(3):
            security.check_rate_limit("1.1.1.1", "test_bucket")
        self.assertFalse(security.check_rate_limit("1.1.1.1", "test_bucket"))

    def test_per_ip_isolation(self) -> None:
        for _ in range(3):
            security.check_rate_limit("1.1.1.1", "test_bucket")
        # A different IP gets its own quota.
        self.assertTrue(security.check_rate_limit("2.2.2.2", "test_bucket"))

    def test_unknown_bucket_is_unlimited(self) -> None:
        for _ in range(100):
            self.assertTrue(security.check_rate_limit("1.1.1.1", "no_such_bucket"))


class BucketRoutingTestCase(unittest.TestCase):
    def test_sms_send_bucket(self) -> None:
        self.assertEqual(security.bucket_for_path("/api/auth/sms/send"), "auth_sms_send")

    def test_login_buckets(self) -> None:
        self.assertEqual(security.bucket_for_path("/api/auth/password/login"), "auth_login")
        self.assertEqual(security.bucket_for_path("/api/auth/sms/verify"), "auth_login")

    def test_register_bucket(self) -> None:
        self.assertEqual(security.bucket_for_path("/api/auth/register"), "auth_register")

    def test_other_auth_bucket(self) -> None:
        self.assertEqual(security.bucket_for_path("/api/auth/logout"), "auth_other")

    def test_non_auth_path_unbucketed(self) -> None:
        self.assertIsNone(security.bucket_for_path("/api/chat"))
        self.assertIsNone(security.bucket_for_path("/api/profile"))


class CsrfTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._enforce = security.CSRF_ENFORCE
        self._allow_missing = security.CSRF_ALLOW_MISSING_ORIGIN
        security.CSRF_ENFORCE = True
        security.CSRF_ALLOW_MISSING_ORIGIN = True

    def tearDown(self) -> None:
        security.CSRF_ENFORCE = self._enforce
        security.CSRF_ALLOW_MISSING_ORIGIN = self._allow_missing

    def test_disabled_enforce_allows_all(self) -> None:
        security.CSRF_ENFORCE = False
        self.assertTrue(security.check_csrf("https://evil.example", "", "myapp"))

    def test_missing_origin_and_referer_allowed_when_configured(self) -> None:
        self.assertTrue(security.check_csrf("", "", "myapp:8787"))

    def test_missing_origin_blocked_when_configured(self) -> None:
        security.CSRF_ALLOW_MISSING_ORIGIN = False
        self.assertFalse(security.check_csrf("", "", "myapp:8787"))

    def test_origin_matches_host(self) -> None:
        self.assertTrue(
            security.check_csrf("http://myapp:8787", "", "myapp:8787")
        )

    def test_origin_mismatch_blocked(self) -> None:
        self.assertFalse(
            security.check_csrf("http://evil.example", "", "myapp:8787")
        )

    def test_referer_used_when_origin_absent(self) -> None:
        self.assertTrue(
            security.check_csrf("", "http://myapp:8787/chat", "myapp:8787")
        )

    def test_referer_mismatch_blocked(self) -> None:
        self.assertFalse(
            security.check_csrf("", "http://evil.example/page", "myapp:8787")
        )

    def test_origin_match_case_insensitive(self) -> None:
        self.assertTrue(
            security.check_csrf("http://MyApp:8787", "", "myapp:8787")
        )

    def test_missing_host_blocks(self) -> None:
        self.assertFalse(security.check_csrf("http://myapp:8787", "", ""))


if __name__ == "__main__":
    unittest.main()

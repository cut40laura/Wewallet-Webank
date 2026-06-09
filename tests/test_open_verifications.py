"""Unit tests for cross-channel open verification items (video → memory write-back).

Run from the project root:
    python3 -m unittest tests.test_open_verifications -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_TEST_TMP = tempfile.mkdtemp(prefix="wewallet-ov-test-")

os.environ["WEWALLET_APP_DATA_DIR"] = _TEST_TMP
os.environ["WEWALLET_UI_DATA_DIR"] = os.path.join(_TEST_TMP, "ui-data")
os.environ["HERMES_HOME"] = os.path.join(_TEST_TMP, "hermes-home")
os.environ["WEWALLET_ENTERPRISE_HERMES_ROOT"] = os.path.join(_TEST_TMP, "ent-hermes")
os.environ["WEWALLET_PROFILE_FILE"] = os.path.join(_TEST_TMP, "profile.md")
os.environ["CUSTOMER_MANAGER_KB_DIR"] = os.path.join(_TEST_TMP, "kb")
os.environ["CUSTOMER_MANAGER_KB_DB"] = os.path.join(_TEST_TMP, "knowledge.sqlite")
os.environ["WEWALLET_AUTH_SECRET"] = "test-secret-for-unittest"

sys.path.insert(0, str(REPO_ROOT / "ui"))

import profile_service  # noqa: E402

ENT = "ent_0123456789ab"


class OpenVerificationsTest(unittest.TestCase):
    def setUp(self) -> None:
        # isolate each test: clear any state for the enterprise
        profile_service.save_profile_state(ENT, {})

    def test_add_load_roundtrip(self) -> None:
        added = profile_service.add_open_verifications(
            ENT,
            [{"field": "月流水", "stated": "10万", "known": "30万", "summary": "月流水对不上"}],
            source="视频通话",
        )
        self.assertEqual(added, 1)
        items = profile_service.load_open_verifications(ENT)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["source"], "视频通话")
        self.assertEqual(items[0]["status"], "open")
        self.assertTrue(items[0]["created_at"])

    def test_dedup_same_signature(self) -> None:
        item = {"field": "月流水", "stated": "10万", "known": "30万", "summary": "x"}
        profile_service.add_open_verifications(ENT, [item], source="视频通话")
        added_again = profile_service.add_open_verifications(ENT, [dict(item)], source="视频通话")
        self.assertEqual(added_again, 0)
        self.assertEqual(len(profile_service.load_open_verifications(ENT)), 1)

    def test_empty_and_invalid_ignored(self) -> None:
        self.assertEqual(profile_service.add_open_verifications(ENT, [], source="x"), 0)
        self.assertEqual(profile_service.add_open_verifications(ENT, [{}], source="x"), 0)
        self.assertEqual(profile_service.add_open_verifications(ENT, ["bad"], source="x"), 0)  # type: ignore[list-item]
        self.assertEqual(len(profile_service.load_open_verifications(ENT)), 0)

    def test_format_block_lists_open_only(self) -> None:
        profile_service.add_open_verifications(
            ENT, [{"summary": "店名前后不一致"}], source="视频通话"
        )
        block = profile_service.format_open_verifications_block(ENT)
        self.assertIn("店名前后不一致", block)
        self.assertIn("视频通话", block)

        # Resolve it → should drop out of the block.
        state = profile_service.load_profile_state(ENT)
        state["open_verifications"][0]["status"] = "resolved"
        profile_service.save_profile_state(ENT, state)
        self.assertEqual(profile_service.format_open_verifications_block(ENT), "")

    def test_block_empty_when_none(self) -> None:
        self.assertEqual(profile_service.format_open_verifications_block(ENT), "")

    def test_state_bookkeeping_preserved(self) -> None:
        # Simulate a profile-update writing its bookkeeping, then a write-back.
        profile_service.save_profile_state(ENT, {"last_profile_user_turn_count": 7, "in_progress": False})
        profile_service.add_open_verifications(ENT, [{"summary": "疑点A"}], source="视频通话")
        state = profile_service.load_profile_state(ENT)
        self.assertEqual(state["last_profile_user_turn_count"], 7)  # not clobbered
        self.assertEqual(len(state["open_verifications"]), 1)


if __name__ == "__main__":
    unittest.main()

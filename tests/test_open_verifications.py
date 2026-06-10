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

os.environ["WEWALLET_AUTH_SECRET"] = "test-secret"
os.environ["WEWALLET_DB"] = os.path.join(_TEST_TMP, "test.sqlite")
os.environ["WEWALLET_APP_DATA_DIR"] = _TEST_TMP
os.environ["WEWALLET_UI_DATA_DIR"] = os.path.join(_TEST_TMP, "ui-data")
os.environ["HERMES_HOME"] = os.path.join(_TEST_TMP, "hermes-home")
os.environ["WEWALLET_ENTERPRISE_HERMES_ROOT"] = os.path.join(_TEST_TMP, "ent-hermes")
os.environ["WEWALLET_PROFILE_FILE"] = os.path.join(_TEST_TMP, "profile.md")
os.environ["CUSTOMER_MANAGER_KB_DIR"] = os.path.join(_TEST_TMP, "kb")
os.environ["CUSTOMER_MANAGER_KB_DB"] = os.path.join(_TEST_TMP, "knowledge.sqlite")

sys.path.insert(0, str(REPO_ROOT / "ui"))

import profile_service  # noqa: E402

ENT = "ent_0123456789ab"


class OpenVerificationsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        # 每个用例隔离：清掉该企业的全部状态。
        profile_service.save_profile_state(ENT, {})

    def test_add_load_roundtrip(self) -> None:
        added = profile_service.add_open_verifications(ENT, [
            {"text": "口述火锅店但画面是卧室", "source": "视频通话 abc123", "level": "medium"},
        ])
        self.assertEqual(added, 1)
        items = profile_service.list_open_verifications(ENT)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["text"], "口述火锅店但画面是卧室")
        self.assertEqual(items[0]["source"], "视频通话 abc123")
        self.assertTrue(items[0]["created_at"])

    def test_dedupe_by_text(self) -> None:
        profile_service.add_open_verifications(ENT, [{"text": "同一条疑点"}])
        added = profile_service.add_open_verifications(ENT, [
            {"text": "同一条疑点"}, {"text": "新疑点"},
        ])
        self.assertEqual(added, 1)
        self.assertEqual(len(profile_service.list_open_verifications(ENT)), 2)

    def test_skips_empty_and_garbage(self) -> None:
        added = profile_service.add_open_verifications(ENT, [
            {"text": ""}, {"text": "   "}, "not-a-dict", {},
        ])
        self.assertEqual(added, 0)
        self.assertEqual(profile_service.list_open_verifications(ENT), [])

    def test_capped_at_max(self) -> None:
        items = [{"text": f"疑点{i}"} for i in range(profile_service.OPEN_VERIFICATIONS_MAX + 5)]
        profile_service.add_open_verifications(ENT, items)
        kept = profile_service.list_open_verifications(ENT)
        self.assertEqual(len(kept), profile_service.OPEN_VERIFICATIONS_MAX)
        self.assertEqual(kept[-1]["text"], f"疑点{profile_service.OPEN_VERIFICATIONS_MAX + 4}")

    def test_block_rendering(self) -> None:
        self.assertEqual(profile_service.open_verifications_block(ENT), "")
        profile_service.add_open_verifications(ENT, [
            {"text": "店名前后说法不一", "source": "视频通话 abc123"},
            {"text": "无来源疑点"},
        ])
        block = profile_service.open_verifications_block(ENT)
        self.assertIn("- 店名前后说法不一（视频通话 abc123）", block)
        self.assertIn("- 无来源疑点", block)

    def test_does_not_clobber_other_state(self) -> None:
        profile_service.save_profile_state(ENT, {"last_profile_updated_at": "2026-06-10"})
        profile_service.add_open_verifications(ENT, [{"text": "疑点"}])
        state = profile_service.load_profile_state(ENT)
        self.assertEqual(state["last_profile_updated_at"], "2026-06-10")
        self.assertEqual(len(state["open_verifications"]), 1)

    def test_digest_keeps_identity_section(self) -> None:
        # 回归：客户与企业画像章节存着法定姓名/常用称呼，是身份核验基线。
        # 曾因蒸馏关键词不含"画像"被整段丢掉 → 通话里报假名比对不出来。
        markdown = (
            "# 企业风控画像\n\n## 一、当前风控结论\n- 风险结论：低\n\n"
            "## 二、客户与企业画像\n| 法定姓名 | 麦立俊 |\n\n"
            "## 七、内部审计日志\n- 略\n"
        )
        kept = profile_service._select_profile_sections(markdown)
        self.assertIn("法定姓名", kept)
        self.assertIn("麦立俊", kept)
        self.assertNotIn("内部审计日志", kept)

    def test_call_memory_context_includes_items(self) -> None:
        profile_service.add_open_verifications(ENT, [{"text": "口述与画面不符", "source": "视频通话 abc123"}])
        context = profile_service.build_call_memory_context(ENT, [])
        self.assertIn("待核实疑点", context)
        self.assertIn("口述与画面不符", context)


if __name__ == "__main__":
    unittest.main()

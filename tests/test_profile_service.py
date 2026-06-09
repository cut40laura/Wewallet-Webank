"""Integration tests for the async profile-update flow.

Run from the project root:
    python3 -m unittest tests.test_profile_service -v
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_TEST_TMP = tempfile.mkdtemp(prefix="wewallet-test-")

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
from config import enterprise_dir, enterprise_profile_file, enterprise_versions_dir  # noqa: E402


def _make_messages(user_turns: int) -> list[dict]:
    msgs: list[dict] = []
    for i in range(user_turns):
        msgs.append({"role": "user", "content": f"客户问题{i}"})
        msgs.append({"role": "assistant", "content": f"客户经理回答{i}"})
    return msgs


CANNED_PROFILE = (
    "# 企业风控画像\n\n"
    "## 当前风险\n- low\n\n"
    "## 风险信号\n- 暂无\n\n"
    "## 字段变更审计\n- 无\n"
)


class StubGateway:
    def __init__(self, content: str = CANNED_PROFILE) -> None:
        self.content = content
        self.submits: list[dict] = []
        self.resets: list[str] = []
        self.error: Exception | None = None

    def submit(self, session_name, prompt, **kwargs):
        self.submits.append({"session": session_name, "prompt": prompt})
        if self.error:
            raise self.error
        return {
            "content": self.content,
            "thinking": "",
            "progress": [],
            "inline_diffs": [],
            "raw": {"session_id": "stub"},
        }

    def reset_session(self, session_name):
        self.resets.append(session_name)


class ProfileServiceTestCase(unittest.TestCase):
    ENTERPRISE_ID = "ent_aaaaaaaaaaaa"
    ENTERPRISE = {"id": ENTERPRISE_ID, "name": "测试企业"}

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(_TEST_TMP, ignore_errors=True)

    def setUp(self) -> None:
        ent_dir = enterprise_dir(self.ENTERPRISE_ID)
        if ent_dir.exists():
            shutil.rmtree(ent_dir, ignore_errors=True)
        ent_dir.mkdir(parents=True, exist_ok=True)
        enterprise_versions_dir(self.ENTERPRISE_ID).mkdir(parents=True, exist_ok=True)
        self._original_gateway_factory = profile_service.gateway_for_enterprise
        self.stub = StubGateway()
        profile_service.gateway_for_enterprise = lambda _eid, _stub=self.stub: _stub
        # Reset the in-memory profile lock so tests don't share state.
        from gateway import PROFILE_UPDATE_LOCKS
        PROFILE_UPDATE_LOCKS.pop(self.ENTERPRISE_ID, None)

    def tearDown(self) -> None:
        profile_service.gateway_for_enterprise = self._original_gateway_factory

    def _wait_for_done(self, timeout: float = 5.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = profile_service.load_profile_state(self.ENTERPRISE_ID)
            if state and not state.get("in_progress"):
                return state
            time.sleep(0.05)
        self.fail(f"profile update did not complete within {timeout}s")

    def test_schedule_returns_none_when_no_user_turns(self) -> None:
        result = profile_service.schedule_profile_update(
            self.ENTERPRISE_ID, self.ENTERPRISE, [], trigger="auto",
        )
        self.assertIsNone(result)
        self.assertEqual(self.stub.submits, [])

    def test_schedule_returns_none_at_non_interval(self) -> None:
        result = profile_service.schedule_profile_update(
            self.ENTERPRISE_ID, self.ENTERPRISE, _make_messages(9), trigger="auto",
        )
        self.assertIsNone(result)
        self.assertEqual(self.stub.submits, [])

    def test_schedule_runs_at_interval_and_writes_profile(self) -> None:
        result = profile_service.schedule_profile_update(
            self.ENTERPRISE_ID, self.ENTERPRISE, _make_messages(10), trigger="auto",
        )
        self.assertTrue(result["scheduled"])
        self.assertEqual(result["user_turn_count"], 10)

        state = self._wait_for_done()
        self.assertFalse(state["in_progress"])
        self.assertEqual(state["last_profile_user_turn_count"], 10)
        self.assertEqual(state["last_profile_trigger"], "auto")
        self.assertTrue(state["last_profile_changed"])
        self.assertTrue(state["last_profile_updated_at"])
        self.assertEqual(state.get("last_error", ""), "")

        path = enterprise_profile_file(self.ENTERPRISE_ID)
        self.assertTrue(path.exists())
        self.assertIn("企业风控画像", path.read_text(encoding="utf-8"))
        self.assertEqual(len(self.stub.submits), 1)

    def test_concurrent_schedule_reports_in_progress(self) -> None:
        profile_service.save_profile_state(self.ENTERPRISE_ID, {"in_progress": True})
        result = profile_service.schedule_profile_update(
            self.ENTERPRISE_ID, self.ENTERPRISE, _make_messages(10), trigger="auto",
        )
        self.assertEqual(result, {
            "scheduled": False,
            "in_progress": True,
            "user_turn_count": 10,
            "interval": 10,
        })
        # The stub should not have been called.
        self.assertEqual(self.stub.submits, [])

    def test_manual_trigger_does_not_override_interval(self) -> None:
        result = profile_service.schedule_profile_update(
            self.ENTERPRISE_ID, self.ENTERPRISE, _make_messages(3), trigger="manual",
        )
        self.assertIsNone(result)
        self.assertEqual(self.stub.submits, [])

    def test_chat_prompt_prioritizes_latest_message_after_farewell(self) -> None:
        prompt = profile_service.build_gateway_chat_turn(
            [], "先这样吧，回头聊。", self.ENTERPRISE, knowledge_hits=[],
        )
        self.assertIn("以客户最新消息为准", prompt)
        self.assertIn("告别不是永久状态", prompt)

    def test_gateway_failure_records_error(self) -> None:
        self.stub.error = RuntimeError("智能体超时")
        result = profile_service.schedule_profile_update(
            self.ENTERPRISE_ID, self.ENTERPRISE, _make_messages(10), trigger="auto",
        )
        self.assertTrue(result["scheduled"])

        state = self._wait_for_done()
        self.assertFalse(state["in_progress"])
        self.assertIn("智能体超时", state.get("last_error", ""))
        self.assertEqual(state["last_profile_trigger"], "auto")

    def test_second_schedule_after_completion_advances(self) -> None:
        profile_service.schedule_profile_update(
            self.ENTERPRISE_ID, self.ENTERPRISE, _make_messages(10), trigger="auto",
        )
        first_state = self._wait_for_done()
        self.assertEqual(first_state["last_profile_user_turn_count"], 10)

        result = profile_service.schedule_profile_update(
            self.ENTERPRISE_ID, self.ENTERPRISE, _make_messages(20), trigger="auto",
        )
        self.assertTrue(result and result["scheduled"])
        second_state = self._wait_for_done()
        self.assertEqual(second_state["last_profile_user_turn_count"], 20)
        self.assertEqual(len(self.stub.submits), 2)


if __name__ == "__main__":
    unittest.main()

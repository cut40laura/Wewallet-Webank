"""Unit tests for video-call due-diligence records (video_calls.py).

Run from the project root:
    python3 -m unittest tests.test_video_calls -v
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
_DB_DIR = tempfile.mkdtemp(prefix="wewallet-test-vc-")
os.environ["WEWALLET_DB"] = str(Path(_DB_DIR) / "test.sqlite")

sys.path.insert(0, str(REPO_ROOT / "ui"))

import db  # noqa: E402
import video_calls  # noqa: E402

ENT_A = "ent_aaaaaaaaaaaa"
ENT_B = "ent_bbbbbbbbbbbb"

TRANSCRIPT = [
    {"role": "user", "content": "我开火锅店的", "channel": "voice"},
    {"role": "assistant", "content": "生意咋样呀？", "channel": "voice"},
]
OBSERVATIONS = [
    {"caption": "画面里是卧室", "place_type": "卧室", "person_present": True,
     "looking_off_screen": False, "anomalies": ["口述店面与画面不符"], "ts": "2026-06-10T12:00:00"},
]


class RecordRoundtripTestCase(unittest.TestCase):
    def setUp(self) -> None:
        with db.transaction() as conn:
            conn.execute("DELETE FROM video_calls")

    def test_record_then_load_roundtrip(self) -> None:
        call_id = video_calls.record_call(
            ENT_A, "user-1",
            transcript=TRANSCRIPT, observations=OBSERVATIONS,
            metadata={"duration_sec": 65, "started_at": "2026-06-10T11:59:00"},
        )
        loaded = video_calls.load_call(call_id, ENT_A)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["transcript"], TRANSCRIPT)
        self.assertEqual(loaded["observations"], OBSERVATIONS)
        self.assertIsNone(loaded["risk"])  # 后台线程补写前为空
        self.assertEqual(loaded["metadata"]["duration_sec"], 65)
        self.assertEqual(loaded["started_at"], "2026-06-10T11:59:00")
        self.assertTrue(loaded["ended_at"])

    def test_enterprise_isolation(self) -> None:
        call_id = video_calls.record_call(
            ENT_A, None, transcript=TRANSCRIPT, observations=None, metadata=None)
        # B 企业读不到、补写不动 A 企业的通话。
        self.assertIsNone(video_calls.load_call(call_id, ENT_B))
        self.assertFalse(video_calls.set_call_risk(call_id, ENT_B, {"level": "high"}))
        self.assertEqual(video_calls.list_calls(ENT_B), [])
        # A 企业自己一切正常。
        self.assertIsNotNone(video_calls.load_call(call_id, ENT_A))

    def test_set_call_risk_overwrites(self) -> None:
        call_id = video_calls.record_call(
            ENT_A, None, transcript=TRANSCRIPT, observations=None, metadata=None)
        self.assertTrue(video_calls.set_call_risk(call_id, ENT_A, {"level": "low", "reasons": []}))
        self.assertTrue(video_calls.set_call_risk(
            call_id, ENT_A, {"level": "medium", "reasons": ["前后说法矛盾"]}))
        loaded = video_calls.load_call(call_id, ENT_A)
        self.assertEqual(loaded["risk"]["level"], "medium")

    def test_list_calls_descending(self) -> None:
        first = video_calls.record_call(ENT_A, None, transcript=TRANSCRIPT, observations=None, metadata=None)
        second = video_calls.record_call(ENT_A, None, transcript=TRANSCRIPT, observations=None, metadata=None)
        ids = [c["id"] for c in video_calls.list_calls(ENT_A)]
        self.assertEqual(ids, [second, first])


class ObservationRegistryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        video_calls.drain_observations(ENT_A)
        video_calls.drain_observations(ENT_B)

    def test_note_then_drain(self) -> None:
        video_calls.note_observation(ENT_A, {"caption": "第一帧"})
        video_calls.note_observation(ENT_A, {"caption": "第二帧"})
        video_calls.note_observation(ENT_B, {"caption": "别家的帧"})
        drained = video_calls.drain_observations(ENT_A)
        self.assertEqual([o["caption"] for o in drained], ["第一帧", "第二帧"])
        self.assertTrue(all(o.get("ts") for o in drained))  # 落痕带时间戳
        self.assertNotIn("_mono", drained[0])  # 内部字段不外漏
        # drain 即清空；B 企业的不受影响。
        self.assertEqual(video_calls.drain_observations(ENT_A), [])
        self.assertEqual(len(video_calls.drain_observations(ENT_B)), 1)

    def test_note_ignores_garbage(self) -> None:
        video_calls.note_observation("", {"caption": "无企业"})
        video_calls.note_observation(ENT_A, None)
        video_calls.note_observation(ENT_A, "not-a-dict")
        self.assertEqual(video_calls.drain_observations(ENT_A), [])

    def test_buffer_capped(self) -> None:
        for i in range(video_calls._OBS_MAX_PER_ENTERPRISE + 10):
            video_calls.note_observation(ENT_A, {"caption": f"帧{i}"})
        drained = video_calls.drain_observations(ENT_A)
        self.assertEqual(len(drained), video_calls._OBS_MAX_PER_ENTERPRISE)
        self.assertEqual(drained[-1]["caption"], f"帧{video_calls._OBS_MAX_PER_ENTERPRISE + 9}")


class RiskRulesTestCase(unittest.TestCase):
    def test_aggregate_signals(self) -> None:
        signals = video_calls.aggregate_risk_signals([
            {"anomalies": ["矛盾A", "矛盾B"], "looking_off_screen": True,
             "person_present": False, "visible_documents": ["营业执照"]},
            {"anomalies": [], "looking_off_screen": False,
             "person_present": True, "visible_documents": ["营业执照", "流水单"]},
            "garbage",
        ])
        self.assertEqual(signals["frame_count"], 3)
        self.assertEqual(signals["anomaly_count"], 2)
        self.assertEqual(signals["off_screen_count"], 1)
        self.assertEqual(signals["person_absent_count"], 1)
        self.assertEqual(signals["documents_seen"], ["营业执照", "流水单"])

    def test_rule_level(self) -> None:
        self.assertEqual(video_calls.rule_level({"anomaly_count": 1, "frame_count": 1}), "medium")
        self.assertEqual(video_calls.rule_level(
            {"anomaly_count": 0, "frame_count": 4, "off_screen_count": 3}), "medium")
        self.assertEqual(video_calls.rule_level(
            {"anomaly_count": 0, "frame_count": 4, "off_screen_count": 1}), "low")
        self.assertEqual(video_calls.rule_level({"anomaly_count": 0, "frame_count": 0}), "low")

    def test_build_risk_summary_rules_only(self) -> None:
        # 无转写 → 不走 LLM，纯规则结论（不发网络请求）。
        risk = video_calls.build_risk_summary(None, OBSERVATIONS)
        self.assertEqual(risk["level"], "medium")
        self.assertEqual(risk["reasons"], [])
        self.assertEqual(risk["signals"]["anomaly_count"], 1)

    def test_contradictions_bump_level(self) -> None:
        # 实时矛盾是强信号：即便画面干净，也至少抬到 medium，并计入 signals。
        contradictions = [{"field": "月流水", "stated": "十万", "known": "三十万"}]
        risk = video_calls.build_risk_summary(None, None, contradictions)
        self.assertEqual(risk["level"], "medium")
        self.assertEqual(risk["signals"]["contradiction_count"], 1)


class ContradictionRegistryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        video_calls.drain_contradictions(ENT_A)
        video_calls.drain_contradictions(ENT_B)

    def test_note_then_drain_isolated(self) -> None:
        video_calls.note_contradiction(ENT_A, {"field": "店名", "stated": "川香居", "known": "蜀味轩"})
        video_calls.note_contradiction(ENT_B, {"field": "别家", "stated": "x", "known": "y"})
        drained = video_calls.drain_contradictions(ENT_A)
        self.assertEqual(len(drained), 1)
        self.assertEqual(drained[0]["field"], "店名")
        self.assertTrue(drained[0]["ts"])
        self.assertNotIn("_mono", drained[0])
        self.assertEqual(video_calls.drain_contradictions(ENT_A), [])  # drain 即清空
        self.assertEqual(len(video_calls.drain_contradictions(ENT_B)), 1)

    def test_note_ignores_garbage(self) -> None:
        video_calls.note_contradiction("", {"field": "x"})
        video_calls.note_contradiction(ENT_A, None)
        self.assertEqual(video_calls.drain_contradictions(ENT_A), [])


class CheckContradictionsGuardTestCase(unittest.TestCase):
    def test_empty_inputs_short_circuit(self) -> None:
        # 没档案或没口述 → 直接 []，不发网络请求。
        import voicecall
        self.assertEqual(voicecall.check_contradictions("", "我月流水十万"), [])
        self.assertEqual(voicecall.check_contradictions("档案：月流水三十万", ""), [])


if __name__ == "__main__":
    unittest.main()

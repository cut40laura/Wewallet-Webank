"""Unit tests for the video-call persistence layer.

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
_TEST_TMP = tempfile.mkdtemp(prefix="wewallet-vc-test-")

os.environ["WEWALLET_UI_DATA_DIR"] = os.path.join(_TEST_TMP, "ui-data")
os.environ["WEWALLET_DB"] = os.path.join(_TEST_TMP, "ui-data", "wewallet.sqlite")
os.environ["WEWALLET_AUTH_SECRET"] = "test-secret-for-unittest"

sys.path.insert(0, str(REPO_ROOT / "ui"))

import video_calls  # noqa: E402

ENT_A = "ent-aaa"
ENT_B = "ent-bbb"


class VideoCallPersistenceTest(unittest.TestCase):
    def test_start_complete_load_roundtrip(self) -> None:
        call_id = video_calls.start_call(ENT_A, "user-1")
        self.assertTrue(call_id)

        active = video_calls.load_call(call_id, ENT_A)
        self.assertIsNotNone(active)
        self.assertEqual(active["status"], "active")
        self.assertIsNone(active["ended_at"])
        self.assertEqual(active["user_id"], "user-1")

        transcript = [
            {"role": "user", "text": "你好", "ts": 1.0},
            {"role": "ai", "text": "您好，在的", "ts": 2.0},
        ]
        observations = [{"caption": "店铺内", "place_type": "店铺", "ts": 1.5}]
        risk = {"level": "low", "reasons": ["画面与口述一致"], "signals": {"anomaly_count": 0}}
        metadata = {"duration_sec": 42, "channel": "voice", "models": {"vision": "doubao-seed"}}

        video_calls.complete_call(
            call_id,
            ENT_A,
            transcript=transcript,
            observations=observations,
            risk=risk,
            metadata=metadata,
        )

        done = video_calls.load_call(call_id, ENT_A)
        self.assertEqual(done["status"], "completed")
        self.assertIsNotNone(done["ended_at"])
        self.assertEqual(done["transcript"], transcript)
        self.assertEqual(done["observations"], observations)
        self.assertEqual(done["risk"], risk)
        self.assertEqual(done["metadata"], metadata)

    def test_enterprise_isolation_on_read(self) -> None:
        call_id = video_calls.start_call(ENT_A, "user-1")
        # Another enterprise must not see this call.
        self.assertIsNone(video_calls.load_call(call_id, ENT_B))

    def test_enterprise_isolation_on_complete(self) -> None:
        call_id = video_calls.start_call(ENT_A, "user-1")
        # Completing under the wrong enterprise must not touch the row.
        updated = video_calls.complete_call(
            call_id, ENT_B, transcript=[], observations=[], risk=None, metadata={}
        )
        self.assertFalse(updated)
        still_active = video_calls.load_call(call_id, ENT_A)
        self.assertEqual(still_active["status"], "active")

    def test_list_calls_scoped_and_ordered(self) -> None:
        a1 = video_calls.start_call(ENT_A, "u")
        a2 = video_calls.start_call(ENT_A, "u")
        video_calls.start_call(ENT_B, "u")

        listed = video_calls.list_calls(ENT_A)
        ids = [row["id"] for row in listed]
        # Only enterprise A's calls, newest first.
        self.assertIn(a1, ids)
        self.assertIn(a2, ids)
        self.assertTrue(all(row["enterprise_id"] == ENT_A for row in listed))
        self.assertEqual(ids[0], a2)

    def test_complete_is_idempotent_overwrite(self) -> None:
        call_id = video_calls.start_call(ENT_A, "user-1")
        video_calls.complete_call(
            call_id, ENT_A, transcript=[{"role": "user", "text": "一", "ts": 1}],
            observations=[], risk=None, metadata={},
        )
        video_calls.complete_call(
            call_id, ENT_A, transcript=[{"role": "user", "text": "二", "ts": 2}],
            observations=[], risk={"level": "medium"}, metadata={"duration_sec": 9},
        )
        done = video_calls.load_call(call_id, ENT_A)
        self.assertEqual(done["transcript"], [{"role": "user", "text": "二", "ts": 2}])
        self.assertEqual(done["risk"], {"level": "medium"})

    def test_complete_normalizes_realtime_asr_repetition(self) -> None:
        call_id = video_calls.start_call(ENT_A, "user-1")
        noisy = (
            "对对对呀对呀对呀你对呀你对呀你看对呀你看对呀你看我"
            "对呀你看我对呀你看我现在对呀你看我现在对呀你看我现在"
            "对呀你看我现在在对呀你看我现在在店里对呀你看我现在在店里吗"
            "对呀，你看我现在在店里吗？对呀你看我现在在店里吗对呀，"
            "你看我现在在店里吗？对呀，你看我现在在店里呢。对呀，你看我现在在店里呢。"
        )
        observations = [
            {
                "place_type": "居住/宿舍",
                "person_present": True,
                "person_description": "戴眼镜，穿深色上衣，手托脸看向镜头",
                "notable_objects": ["上下铺床", "上下铺床", ""],
                "visible_documents": [],
                "caption": " 一名男子处于宿舍内 ",
                "image": "should-not-survive",
                "ts": "1780989380.928",
            },
            "bad-observation",
        ]

        video_calls.complete_call(
            call_id,
            ENT_A,
            transcript=[{"role": "user", "text": noisy, "ts": 1}],
            observations=observations,
            risk=None,
            metadata={"duration_sec": 10},
        )

        done = video_calls.load_call(call_id, ENT_A)
        self.assertEqual(
            done["transcript"],
            [{"role": "user", "text": "对呀，你看我现在在店里吗？对呀，你看我现在在店里呢。", "ts": 1.0}],
        )
        self.assertEqual(
            done["observations"],
            [
                {
                    "place_type": "居住/宿舍",
                    "person_present": True,
                    "person_description": "戴眼镜，穿深色上衣，手托脸看向镜头",
                    "notable_objects": ["上下铺床"],
                    "caption": "一名男子处于宿舍内",
                    "ts": 1780989380.928,
                }
            ],
        )
        self.assertTrue(done["metadata"]["normalization"]["transcript"]["changed"])
        self.assertGreater(done["metadata"]["normalization"]["transcript"]["chars_removed"], 0)

    def test_complete_normalizes_latest_video_call_samples(self) -> None:
        call_id = video_calls.start_call(ENT_A, "user-1")
        transcript = [
            {
                "role": "user",
                "text": (
                    "我我我我现在我现在我现在我现在在我现在在我现在在飞机"
                    "我现在在飞机上我现在在飞机上呢我现在在飞机上呢。我现在在飞机上呢"
                    "有点我现在在飞机上呢有点听不到我现在在飞机上呢，有点听不到。"
                    "我现在在飞机上呢有点听不到我现在在飞机上呢，有点听不到。"
                    "我现在在飞机上呢，有点听不到。"
                ),
                "ts": 1,
            },
            {
                "role": "user",
                "text": (
                    "嗯嗯嗯嗯对嗯对嗯对口嗯对口误嗯对口误了对，口误了。"
                    "嗯对口误了嗯对口误了嗯，对口误了。嗯，对口误了。"
                ),
                "ts": 2,
            },
            {
                "role": "user",
                "text": (
                    "你你你为什么你为什么觉得你为什么觉得我在宿舍"
                    "你为什么觉得我在宿舍不觉得我在公务舱呢"
                    "你为什么觉得我在宿舍，不觉得我在公务舱呢？"
                    "你为什么觉得我在宿舍，不觉得我在公务舱呢？"
                ),
                "ts": 3,
            },
        ]

        video_calls.complete_call(
            call_id,
            ENT_A,
            transcript=transcript,
            observations=[],
            risk=None,
            metadata={"duration_sec": 12},
        )

        done = video_calls.load_call(call_id, ENT_A)
        self.assertEqual(
            [item["text"] for item in done["transcript"]],
            [
                "我现在在飞机上呢有点听不到。",
                "嗯对口误了。",
                "你为什么觉得我在宿舍不觉得我在公务舱呢？",
            ],
        )


if __name__ == "__main__":
    unittest.main()

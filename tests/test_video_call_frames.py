from __future__ import annotations

import base64
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_TEST_TMP = tempfile.mkdtemp(prefix="wewallet-vc-frames-test-")

os.environ["WEWALLET_UI_DATA_DIR"] = os.path.join(_TEST_TMP, "ui-data")
os.environ["WEWALLET_DB"] = os.path.join(_TEST_TMP, "ui-data", "wewallet.sqlite")
os.environ["WEWALLET_AUTH_SECRET"] = "test-secret-for-unittest"

sys.path.insert(0, str(REPO_ROOT / "ui"))

from config import enterprise_uploads_dir  # noqa: E402
from server import _persist_observation_frames  # noqa: E402


class VideoCallFramePersistenceTest(unittest.TestCase):
    def test_frames_are_saved_under_call_id_directory(self) -> None:
        enterprise_id = "ent_abcdef123456"
        call_id = "call-123"
        tiny_jpg = base64.b64encode(b"\xff\xd8\xff\xd9").decode("ascii")
        observations = [{"caption": "宿舍画面", "ts": 1780991902.794}]
        frames = [{"ts": 1780991902.794, "image": f"data:image/jpeg;base64,{tiny_jpg}"}]

        saved = _persist_observation_frames(
            enterprise_id,
            call_id,
            observations,
            frames,
            "2026-06-09T16:25:40+0800",
        )

        self.assertEqual(
            saved[0]["image_url"],
            f"/uploads/{enterprise_id}/video-calls/video-call-20260609-162540-call123/frame-000-20260609-155822.jpg",
        )
        frame_path = (
            enterprise_uploads_dir(enterprise_id)
            / "video-calls"
            / "video-call-20260609-162540-call123"
            / "frame-000-20260609-155822.jpg"
        )
        self.assertTrue(frame_path.exists())
        self.assertEqual(frame_path.read_bytes(), b"\xff\xd8\xff\xd9")


if __name__ == "__main__":
    unittest.main()

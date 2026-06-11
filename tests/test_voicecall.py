from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "ui"))

import json  # noqa: E402
import struct  # noqa: E402

import voicecall_doubao as dbq  # noqa: E402
from voicecall import _extract_json, _parse_observation, _salvage_caption  # noqa: E402
from voicecall_relay import _caption_with_scene, _verify_hint  # noqa: E402


class VoicecallVisionTestCase(unittest.TestCase):
    def test_parses_structured_observation(self) -> None:
        raw = (
            '{"place_type":"办公室","person_present":true,"person_count":1,'
            '"looking_off_screen":false,"visible_documents":["营业执照"],'
            '"document_text":"测试公司","notable_objects":[],"anomalies":[],'
            '"caption":"客户展示营业执照"}'
        )
        observation = _parse_observation(raw)
        self.assertIsNotNone(observation)
        self.assertEqual(observation["caption"], "客户展示营业执照")
        self.assertEqual(observation["visible_documents"], ["营业执照"])

    def test_extracts_json_from_fence_and_surrounding_text(self) -> None:
        fenced = '```json\n{"caption":"画面清晰","visible_documents":[]}\n```'
        surrounded = '模型说明 {"caption":"客户在店内"} 结束'
        self.assertEqual(_parse_observation(fenced)["caption"], "画面清晰")
        self.assertEqual(_parse_observation(surrounded)["caption"], "客户在店内")

    def test_salvages_caption_from_truncated_json(self) -> None:
        self.assertEqual(_salvage_caption('{"caption":"截断文字'), "截断文字")

    def test_builds_private_verification_hint(self) -> None:
        hint = _verify_hint({
            "visible_documents": ["营业执照"],
            "looking_off_screen": True,
            "anomalies": ["场所不符"],
        })
        self.assertIn("口头念出", hint)
        self.assertIn("照稿念", hint)
        self.assertIn("场所不符", hint)

    def test_scene_mismatch_hint_for_residential(self) -> None:
        # 画面像居家 → 触发"画面 vs 口述场景"交叉核验提示
        hint = _verify_hint({"place_type": "居住/家", "visible_documents": [], "anomalies": []})
        self.assertIn("居住/家", hint)
        self.assertIn("经营", hint)

    def test_no_scene_hint_for_business_place(self) -> None:
        # 正常营业场所不该误报疑点
        self.assertEqual(_verify_hint({"place_type": "店铺", "visible_documents": [], "anomalies": []}), "")

    def test_caption_carries_scene_for_concrete_place(self) -> None:
        out = _caption_with_scene("一个人坐在床边", {"place_type": "居住/家"})
        self.assertTrue(out.startswith("[画面]"))  # 保留前缀（人设当亲眼所见）
        self.assertIn("居住/家", out)

    def test_caption_omits_scene_when_unclear(self) -> None:
        self.assertEqual(_caption_with_scene("画面糊", {"place_type": "看不清"}), "[画面] 画面糊")

    def test_caption_states_no_person(self) -> None:
        # 画面无人 → 注入硬事实"没看到人"，让小微能反驳"我这有5个人"
        out = _caption_with_scene("空房间", {"person_present": False, "person_count": 0})
        self.assertIn("没看到人", out)

    def test_caption_states_person_count(self) -> None:
        out = _caption_with_scene("几人围坐", {"person_present": True, "person_count": 3})
        self.assertIn("3人", out)

    def test_caption_person_present_without_count(self) -> None:
        out = _caption_with_scene("有人入镜", {"person_present": True})
        self.assertIn("可见人物", out)


class DoubaoCodecTestCase(unittest.TestCase):
    """豆包 openspeech 实时对话二进制帧编解码（voicecall_doubao）。"""

    def test_full_client_frame_roundtrip(self) -> None:
        sid = "sess-abcd-1234-efgh"
        payload = {"content": "[画面] 客户展示营业执照"}
        frame = dbq.make_full_client_frame(dbq.EVENT_CHAT_TEXT_QUERY, payload, sid)
        dec = dbq.decode_frame(frame)
        self.assertIsNotNone(dec)
        self.assertEqual(dec.event, dbq.EVENT_CHAT_TEXT_QUERY)
        self.assertEqual(dec.session_id, sid)
        self.assertEqual(dec.json, payload)

    def test_audio_frame_roundtrip(self) -> None:
        sid = "sess-abcd-1234-efgh"
        audio = b"\x01\x02\x03\x04" * 16
        dec = dbq.decode_frame(dbq.make_audio_frame(audio, sid))
        self.assertEqual(dec.event, dbq.EVENT_TASK_REQUEST)
        self.assertEqual(dec.payload, audio)

    def test_upstream_headers_prefer_app_id(self) -> None:
        h = dbq.build_upstream_headers(
            "cid", app_id="A", access_key="K", api_key="ignored",
            app_key="PK", resource_id="volc.speech.dialog")
        self.assertEqual(h["X-Api-App-ID"], "A")
        self.assertEqual(h["X-Api-Access-Key"], "K")
        self.assertNotIn("X-Api-Key", h)

    def test_upstream_headers_fallback_to_api_key(self) -> None:
        h = dbq.build_upstream_headers(
            "cid", app_id="", access_key="", api_key="XK",
            app_key="PK", resource_id="volc.speech.dialog")
        self.assertEqual(h["X-Api-Key"], "XK")
        self.assertNotIn("X-Api-App-ID", h)

    @staticmethod
    def _server_frame(event: int, payload: bytes, serialization: int) -> bytes:
        return b"".join([
            bytes([0x11, 0x94, (serialization << 4), 0x00]),
            struct.pack(">I", event),
            struct.pack(">I", len(payload)),
            payload,
        ])

    def test_translate_asr_emits_transcript_not_speech_started(self) -> None:
        # speech_started 已移到中继按"语音起点"判定，translate_frame 不再每帧发（否则几十个
        # interim 会反复掐断小微）。这里只该回传转写文本。
        frame = self._server_frame(
            dbq.EVENT_ASR_RESPONSE,
            json.dumps({"results": [{"text": "你好我想贷款", "is_interim": True}]}).encode(), 1)
        out = dbq.translate_frame(dbq.decode_frame(frame))
        types = [p["type"] for p in out]
        self.assertNotIn("input_audio_buffer.speech_started", types)
        self.assertTrue(any(p.get("transcript") == "你好我想贷款" for p in out))

    def test_translate_tts_audio_is_base64_pcm24k(self) -> None:
        import base64
        pcm = b"\x10\x00\x20\x00\x30\x00"
        out = dbq.translate_frame(dbq.decode_frame(self._server_frame(dbq.EVENT_TTS_RESPONSE, pcm, 0)))
        self.assertEqual(out[0]["type"], "response.audio.delta")
        # 字段名必须是 delta（前端契约），不是 audio——曾因此小微收到音频却不播
        self.assertEqual(base64.b64decode(out[0]["delta"]), pcm)
        self.assertEqual(out[0]["sample_rate"], 24000)


if __name__ == "__main__":
    unittest.main()

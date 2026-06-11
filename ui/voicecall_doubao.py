"""豆包 openspeech「实时对话」(volc.speech.dialog) 的二进制协议编解码。

字节跳动 openspeech 的实时对话大模型不是 OpenAI 兼容的 JSON-over-WS，而是一套
**自定义二进制帧协议**：4 字节 header + 可选 code/sequence/event/session_id + 4 字节
长度前缀的 payload。这里只放纯粹的「帧 ⇆ 事件」编解码和会话配置，异步连接/桥接逻辑在
voicecall_relay.py。

参考实现：火山 openspeech 实时对话 demo（与 Webank-wallet-参考/realtime/
doubao-realtime-proxy.mjs 同协议），本模块是其 Python 移植。

帧结构（big-endian）：
    byte0: (version<<4)|(header_size/4)   —— 客户端固定 0x11（version1、header 4 字节）
    byte1: (message_type<<4)|flags        —— full-client=0x14、audio-only=0x24、
                                              服务端 full-server=0x9.. / error=0xf..
    byte2: (serialization<<4)|compression —— JSON=0x10、raw 二进制(音频)=0x00
    byte3: 0x00（保留）
    之后按 flags：flags==0x04 跟 4 字节 event；event>=100 时可能跟 session_id
    （4 字节长度 + utf8）；最后 4 字节 payload 长度 + payload。
"""
from __future__ import annotations

import base64
import json
import re
import struct
from typing import Any, Optional

# ── 事件码 ──────────────────────────────────────────────────────────────────
# 客户端 → 服务端
EVENT_START_CONNECTION = 1
EVENT_FINISH_CONNECTION = 2
EVENT_START_SESSION = 100
EVENT_FINISH_SESSION = 102
EVENT_TASK_REQUEST = 200  # 上行音频帧
EVENT_END_ASR = 400
EVENT_CHAT_TEXT_QUERY = 501  # 注入文字（看画面旁白/手动核验）
EVENT_CLIENT_INTERRUPT = 515  # 打断 AI 播报

# 服务端 → 客户端
EVENT_CONNECTION_STARTED = 50
EVENT_CONNECTION_FAILED = 51
EVENT_CONNECTION_FINISHED = 52
EVENT_SESSION_STARTED = 150
EVENT_SESSION_CANCELED = 151
EVENT_SESSION_FINISHED = 152
EVENT_SESSION_FAILED = 153
EVENT_USAGE = 154
EVENT_TTS_SENTENCE_START = 350
EVENT_TTS_SENTENCE_END = 351
EVENT_TTS_RESPONSE = 352  # TTS 音频分片（payload 是裸 pcm_s16le）
EVENT_TTS_ENDED = 359
EVENT_TTS_SUBTITLE = 364  # AI 字幕
EVENT_ASR_INFO = 450
EVENT_ASR_RESPONSE = 451  # 用户 ASR 文本
EVENT_ASR_ENDED = 459
EVENT_CHAT_RESPONSE = 550  # AI 文本（LLM）
EVENT_CHAT_TEXT_QUERY_CONFIRMED = 553
EVENT_CHAT_ENDED = 559
EVENT_DIALOG_COMMON_ERROR = 599

TTS_SAMPLE_RATE = 24000  # 服务端 TTS 输出
ASR_SAMPLE_RATE = 16000  # 客户端上行音频要求


# ── 编码：客户端 → 上游 ────────────────────────────────────────────────────
def _u32(value: int) -> bytes:
    return struct.pack(">I", value & 0xFFFFFFFF)


def make_full_client_frame(event: int, payload: Optional[dict[str, Any]], session_id: Optional[str]) -> bytes:
    """full-client（JSON）帧：StartConnection/StartSession/ChatTextQuery/Interrupt 等。"""
    payload_bytes = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
    parts = [bytes([0x11, 0x14, 0x10, 0x00]), _u32(event)]
    if session_id:
        sid = session_id.encode("utf-8")
        parts.append(_u32(len(sid)))
        parts.append(sid)
    parts.append(_u32(len(payload_bytes)))
    parts.append(payload_bytes)
    return b"".join(parts)


def make_audio_frame(audio_bytes: bytes, session_id: str) -> bytes:
    """audio-only 帧：上行麦克风 PCM16（TaskRequest）。"""
    sid = session_id.encode("utf-8")
    return b"".join([
        bytes([0x11, 0x24, 0x00, 0x00]),
        _u32(EVENT_TASK_REQUEST),
        _u32(len(sid)),
        sid,
        _u32(len(audio_bytes)),
        audio_bytes,
    ])


# ── 解码：上游 → 结构化帧 ──────────────────────────────────────────────────
class DoubaoFrame:
    __slots__ = ("message_type", "flags", "serialization", "compression",
                 "code", "sequence", "event", "session_id", "payload", "json")

    def __init__(self) -> None:
        self.message_type = 0
        self.flags = 0
        self.serialization = 0
        self.compression = 0
        self.code: Optional[int] = None
        self.sequence: Optional[int] = None
        self.event: Optional[int] = None
        self.session_id: Optional[str] = None
        self.payload: bytes = b""
        self.json: Optional[dict[str, Any]] = None


_SESSION_ID_RE = re.compile(r"^[\w-]{8,128}$")


def decode_frame(data: bytes) -> Optional[DoubaoFrame]:
    """解析一帧豆包二进制；长度不足/异常返回 None。"""
    buf = bytes(data)
    if len(buf) < 8:
        return None

    f = DoubaoFrame()
    header_size = (buf[0] & 0x0F) * 4
    f.message_type = buf[1] >> 4
    f.flags = buf[1] & 0x0F
    f.serialization = buf[2] >> 4
    f.compression = buf[2] & 0x0F
    offset = header_size

    # error 帧（message_type==0x0f）带 4 字节错误码
    if f.message_type == 0x0F and offset + 4 <= len(buf):
        f.code = struct.unpack_from(">i", buf, offset)[0]
        offset += 4

    if f.flags in (0x01, 0x02, 0x03) and offset + 4 <= len(buf):
        f.sequence = struct.unpack_from(">i", buf, offset)[0]
        offset += 4

    if f.flags == 0x04 and offset + 4 <= len(buf):
        f.event = struct.unpack_from(">I", buf, offset)[0]
        offset += 4

    # event>=100 的帧可能带 session_id（4 字节长度 + utf8）
    if f.event and f.event >= 100 and offset + 4 <= len(buf):
        maybe_len = struct.unpack_from(">I", buf, offset)[0]
        if 0 < maybe_len <= 128 and offset + 4 + maybe_len + 4 <= len(buf):
            maybe_sid = buf[offset + 4: offset + 4 + maybe_len].decode("utf-8", "replace")
            if _SESSION_ID_RE.match(maybe_sid):
                f.session_id = maybe_sid
                offset += 4 + maybe_len

    if offset + 4 > len(buf):
        return f  # 无 payload（如某些控制帧）

    payload_size = struct.unpack_from(">I", buf, offset)[0]
    offset += 4
    f.payload = buf[offset: offset + payload_size]
    if f.serialization == 0x01:
        try:
            f.json = json.loads(f.payload.decode("utf-8", "replace"))
        except (ValueError, TypeError):
            f.json = None
    return f


# ── 翻译：豆包帧 → 前端抽象事件（与中继↔浏览器协议一致）──────────────────────
def translate_frame(frame: DoubaoFrame) -> list[dict[str, Any]]:
    """把一帧豆包事件翻成前端 RealtimeEngine 认识的抽象事件列表。

    抽象协议（与原 StepFun 路径一致，故前端基本不用改）：
      - input_audio_buffer.speech_started               用户开口 → 前端打断/截帧
      - conversation.item.input_audio_transcription.completed  用户 ASR 文本
      - response.audio.delta {audio:b64 pcm_s16le@24k}  AI 语音分片
      - response.audio_transcript.delta {delta}         AI 字幕
      - response.text.delta {delta}                     AI 文本（LLM，前端忽略也无妨）
      - response.done                                   本轮结束
      - error / proxy.*                                 异常
    """
    out: list[dict[str, Any]] = []
    data = frame.json or {}
    ev = frame.event

    if frame.message_type == 0x0F or ev == EVENT_DIALOG_COMMON_ERROR:
        out.append({
            "type": "error",
            "event": ev,
            "code": frame.code,
            "message": data.get("error") or data.get("message") or "豆包实时语音返回错误。",
        })
        return out

    if ev == EVENT_CONNECTION_STARTED:
        out.append({"type": "proxy.upstream_connection_started"})
    elif ev == EVENT_SESSION_STARTED:
        out.append({"type": "proxy.upstream_session_started", "dialog_id": data.get("dialog_id", "")})
    elif ev == EVENT_ASR_RESPONSE:
        # 注意：speech_started / 打断【不在这里发】——它们只该在用户"语音起点"触发一次，由
        # voicecall_relay._pump_doubao_upstream 按 user_turn_active 状态判定。否则一句话几十个
        # interim 帧每个都会让前端停播 + 打断豆包，把小微切得稀碎（"没说完又说一句"的根因）。
        text = "".join(item.get("text", "") for item in (data.get("results") or []) if item.get("text"))
        if text:
            out.append({"type": "conversation.item.input_audio_transcription.completed", "transcript": text})
    elif ev == EVENT_CHAT_RESPONSE:
        if data.get("content"):
            out.append({"type": "response.text.delta", "delta": data["content"]})
    elif ev == EVENT_TTS_SUBTITLE:
        if data.get("text"):
            out.append({"type": "response.audio_transcript.delta", "delta": data["text"]})
    elif ev == EVENT_TTS_RESPONSE:
        # 字段名 delta：对齐前端 voicecall.js 的 `if (ev.delta) playDelta(...)` 契约
        # （与 response.audio_transcript.delta 一致）。放 audio 字段前端读不到 → 不播 = 小微不出声。
        out.append({
            "type": "response.audio.delta",
            "delta": base64.b64encode(frame.payload).decode("ascii"),
            "encoding": "pcm_s16le",
            "sample_rate": TTS_SAMPLE_RATE,
        })
    elif ev == EVENT_ASR_ENDED:
        out.append({"type": "input_audio_transcription.done"})
    elif ev == EVENT_TTS_ENDED:
        # 只在音频真正播完时发 response.done。CHAT_ENDED（文字生成完）比 TTS_ENDED 早 ~1.5s，
        # 若也翻成 response.done，前端会在 TTS 字幕还在流时清字幕状态 + 记录一次回复，
        # 导致字幕从半句中间断头重来、同一句话双份进通话记录。CHAT_ENDED 走下面的
        # proxy.event 透传，前端不动作。
        out.append({"type": "response.done", "event": ev})
    elif ev in (EVENT_SESSION_FAILED, EVENT_CONNECTION_FAILED):
        out.append({"type": "error", "event": ev,
                    "message": data.get("error") or data.get("message") or "豆包实时语音会话失败。"})
    elif ev:
        out.append({"type": "proxy.event", "event": ev})
    return out


def is_failure_event(event: Optional[int]) -> bool:
    return event in (EVENT_CONNECTION_FAILED, EVENT_SESSION_FAILED, EVENT_SESSION_CANCELED)


# ── 会话配置 / 请求头 ──────────────────────────────────────────────────────
def build_upstream_headers(connect_id: str, *, app_id: str, access_key: str,
                           api_key: str, app_key: str, resource_id: str) -> dict[str, str]:
    """上游 WS 握手请求头。优先 App ID + Access Key；否则退回新版 X-Api-Key。"""
    headers = {
        "X-Api-Resource-Id": resource_id,
        "X-Api-App-Key": app_key,
        "X-Api-Connect-Id": connect_id,
    }
    if app_id and access_key:
        headers["X-Api-App-ID"] = app_id
        headers["X-Api-Access-Key"] = access_key
    elif api_key:
        headers["X-Api-Key"] = api_key
    return headers


def build_session_config(system_role: str, *, tts_speaker: str, model_version: str,
                         bot_name: str = "微众小微贷",
                         end_smooth_window_ms: int = 400, asr_twopass: bool = False) -> dict[str, Any]:
    """StartSession 的 payload：TTS 音色 / ASR 音频参数 / 对话人设。

    降延迟相关（实测用户说完→第一声约 1s，主要花在这两项）：
    - ``end_smooth_window_ms``：判定"说完了"要等的静音时长。600→400 更快接话；太小会在
      用户停顿时抢话，400 是兼顾。
    - ``asr_twopass``：两遍 ASR 更准但更慢；关掉用一遍结果，明显降延迟，代价是转写略糙。
    """
    return {
        "tts": {
            "speaker": tts_speaker,
            "audio_config": {"format": "pcm_s16le", "sample_rate": TTS_SAMPLE_RATE,
                             "channel": 1, "speech_rate": 0, "loudness_rate": 0},
            "extra": {},
        },
        "asr": {
            "audio_info": {"format": "pcm", "sample_rate": ASR_SAMPLE_RATE, "channel": 1},
            "extra": {"end_smooth_window_ms": end_smooth_window_ms,
                      "enable_custom_vad": False, "enable_asr_twopass": asr_twopass},
        },
        "dialog": {
            "bot_name": bot_name,
            "system_role": system_role,
            "speaking_style": "口语化、自然、亲和，一次只说一两句，简短不啰嗦。",
            "dialog_id": "",
            "extra": {
                "strict_audit": True,
                "input_mod": "audio",
                "enable_loudness_norm": True,
                "enable_conversation_truncate": True,
                "enable_user_query_exit": True,
                "model": model_version,
            },
        },
    }

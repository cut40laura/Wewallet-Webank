"""Speech-to-text via DashScope qwen3-asr-flash.

The browser's MediaRecorder produces audio/webm (Opus). qwen3-asr-flash
accepts that container inline as base64 — no transcoding needed. For
30-second voice memos the round-trip is ~1–2s, which is acceptable to do
synchronously during chat ingestion (the transcript needs to be in the
LLM prompt of the same turn).

We use the multimodal-generation endpoint with audio-only payload (no
text prompt) — that's the recommended invocation for the dedicated ASR
model and produces punctuated transcripts plus emotion/language metadata.
The fallback path here also works for the older qwen-audio-turbo model,
so the env var can swap between them without code changes.

Failure mode is "fall back to empty string": the chat turn still goes
through with the original "[语音附件]" placeholder. We do NOT block the
turn on a flaky ASR call.
"""
from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any

import requests

from config import (
    ASR_MAX_AUDIO_BYTES,
    DASHSCOPE_API_KEY,
    DASHSCOPE_ASR_MODEL,
)


ASR_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
REQUEST_TIMEOUT_S = 60
# Models with "asr" in the id are dedicated ASR (qwen3-asr-flash etc.) and
# should be invoked with audio-only payload. Generic audio chat models
# (qwen-audio-turbo, qwen2-audio-instruct, ...) will hallucinate a reply
# unless told to transcribe.
TRANSCRIPT_PROMPT = "请把这段语音里的内容用中文文字写出来，只输出原文逐字，不要做任何解释或评论。"

# What MediaRecorder commonly outputs + what qwen-audio actually accepts.
_AUDIO_MIME_OVERRIDES = {
    ".webm": "audio/webm",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
}


def is_audio_mime(mime: str) -> bool:
    return str(mime or "").startswith("audio/")


def guess_audio_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in _AUDIO_MIME_OVERRIDES:
        return _AUDIO_MIME_OVERRIDES[suffix]
    guess = mimetypes.guess_type(str(path))[0]
    return guess if guess and is_audio_mime(guess) else "audio/webm"


def transcribe_audio(path: Path) -> dict[str, Any]:
    """Transcribe an audio file. Returns ``text``, ``emotion``, ``language``, ``error``.

    ``emotion`` / ``language`` come from qwen3-asr-flash's ``audio_info``
    annotations. Generic audio chat models don't emit them; in that case
    both fields are empty strings.

    Empty ``text`` means "couldn't hear it" — the chat layer keeps the raw
    audio attachment so the customer can re-send. ``error`` is for progress
    events / diagnostics; it's never shown to the customer.
    """
    empty = {"text": "", "emotion": "", "language": "", "error": ""}
    if not DASHSCOPE_API_KEY:
        return {**empty, "error": "DASHSCOPE_API_KEY 未配置，语音识别已禁用"}
    try:
        size = path.stat().st_size
    except OSError as exc:
        return {**empty, "error": f"audio file not readable: {exc}"}
    if size <= 0:
        return {**empty, "error": "audio file is empty"}
    if size > ASR_MAX_AUDIO_BYTES:
        return {**empty, "error": f"audio file too large ({size} bytes > {ASR_MAX_AUDIO_BYTES})"}

    mime = guess_audio_mime(path)
    b64 = base64.b64encode(path.read_bytes()).decode()
    data_uri = f"data:{mime};base64,{b64}"

    content: list[dict[str, str]] = [{"audio": data_uri}]
    if "asr" not in DASHSCOPE_ASR_MODEL.lower():
        # Generic audio chat models need an explicit instruction or they'll
        # respond conversationally to whatever the audio says.
        content.append({"text": TRANSCRIPT_PROMPT})

    payload = {
        "model": DASHSCOPE_ASR_MODEL,
        "input": {"messages": [{"role": "user", "content": content}]},
    }
    try:
        r = requests.post(
            ASR_URL,
            headers={
                "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=REQUEST_TIMEOUT_S,
        )
        r.raise_for_status()
        body = r.json()
    except requests.exceptions.RequestException as exc:
        return {**empty, "error": f"asr request failed: {exc}"}
    except ValueError as exc:
        return {**empty, "error": f"asr response not json: {exc}"}

    text = _extract_text(body)
    emotion, language = _extract_audio_info(body)
    if not text:
        return {**empty, "emotion": emotion, "language": language,
                "error": f"asr returned no text: {body}"}
    return {"text": text, "emotion": emotion, "language": language, "error": ""}


def _extract_audio_info(body: dict) -> tuple[str, str]:
    """Read qwen3-asr-flash's annotations for emotion + language."""
    try:
        annotations = body["output"]["choices"][0]["message"].get("annotations") or []
    except (KeyError, IndexError, TypeError):
        return "", ""
    for ann in annotations:
        if isinstance(ann, dict) and ann.get("type") == "audio_info":
            return str(ann.get("emotion") or "").strip().lower(), str(ann.get("language") or "").strip().lower()
    return "", ""


def _extract_text(body: dict) -> str:
    try:
        content = body["output"]["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts).strip()
    return ""


if __name__ == "__main__":
    import sys, json
    if len(sys.argv) < 2:
        print("usage: python asr.py <audio_path>", file=sys.stderr)
        sys.exit(2)
    result = transcribe_audio(Path(sys.argv[1]))
    print(json.dumps(result, ensure_ascii=False, indent=2))

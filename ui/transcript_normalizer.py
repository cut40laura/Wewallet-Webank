"""Canonicalization helpers for video/voice-call records."""
from __future__ import annotations

import copy
import re
from typing import Any


_CJK_RUN_RE = re.compile(r"([\u3400-\u9fff])\1{2,}")
_SPACE_RE = re.compile(r"\s+")
_SENTENCE_RE = re.compile(r"([^。！？]+)([。！？]?)")


def _collapse_char_runs(text: str) -> str:
    # ASR stutters often arrive as "你你你" or "对对对"; keep one.
    return _CJK_RUN_RE.sub(r"\1", text)


def _collapse_adjacent_repeats(text: str, *, max_size: int = 24) -> str:
    changed = True
    while changed:
        changed = False
        for size in range(min(max_size, len(text) // 2), 1, -1):
            out: list[str] = []
            i = 0
            while i < len(text):
                frag = text[i:i + size]
                if len(frag) < size:
                    out.append(text[i:])
                    break
                j = i + size
                count = 1
                while text[j:j + size] == frag:
                    count += 1
                    j += size
                if count >= 2:
                    out.append(frag)
                    i = j
                    changed = True
                else:
                    out.append(text[i])
                    i += 1
            text = "".join(out)
    return text


def _trim_asr_prefix_accumulation(text: str) -> str:
    """Keep the final utterance when ASR accumulated prefixes into one line.

    Example: "对呀你 对呀你看 对呀你看我..." should become the last complete
    phrase instead of keeping every intermediate prefix.
    """
    n = len(text)
    if n < 12:
        return text
    for length in range(min(n - 2, 80), 3, -1):
        suffix = text[-length:]
        prefix = text[:-length]
        if len(prefix) < 4:
            continue
        if suffix in prefix:
            return suffix

        pos = 0
        covered = 0
        chunks = 0
        while pos < len(prefix):
            match = 0
            for k in range(min(length, len(prefix) - pos), 1, -1):
                if prefix.startswith(suffix[:k], pos):
                    match = k
                    break
            if match:
                covered += match
                chunks += 1
                pos += match
            else:
                pos += 1
        if chunks >= 2 and covered >= 6 and covered / max(1, len(prefix)) >= 0.72:
            return suffix
    return text


def _restore_leading_polarity(original: str, cleaned: str) -> str:
    squashed = _collapse_adjacent_repeats(_collapse_char_runs(_SPACE_RE.sub("", original)))
    for prefix in ("不是", "没有", "对呀", "对啊", "是的", "嗯", "哦"):
        if squashed.startswith(prefix) and cleaned and not cleaned.startswith(prefix):
            return f"{prefix}，{cleaned}"
    return cleaned


def _restore_leading_pause(text: str) -> str:
    for prefix in ("不是", "没有", "对呀", "对啊", "是的"):
        if text.startswith(prefix) and len(text) > len(prefix) and text[len(prefix)] != "，":
            return f"{prefix}，{text[len(prefix):]}"
    return text


def normalize_call_text(text: Any) -> str:
    """Normalize one transcript string while preserving the intended meaning."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    raw = re.sub(r"[，,]\s*", "，", raw)
    raw = re.sub(r"[。\.]+", "。", raw)
    raw = re.sub(r"[？?]+", "？", raw)
    raw = re.sub(r"[！!]+", "！", raw)

    parts: list[str] = []
    for match in _SENTENCE_RE.finditer(raw):
        body = match.group(1).strip(" ，,")
        punct = match.group(2)
        if not body:
            continue
        cleaned = _SPACE_RE.sub("", body.replace("，", "").replace(",", ""))
        for _ in range(4):
            prev = cleaned
            cleaned = _collapse_char_runs(cleaned)
            cleaned = _collapse_adjacent_repeats(cleaned)
            cleaned = _trim_asr_prefix_accumulation(cleaned)
            cleaned = _collapse_adjacent_repeats(cleaned)
            if cleaned == prev:
                break
        cleaned = _restore_leading_pause(_restore_leading_polarity(body, cleaned)).strip(" ，,")
        if cleaned:
            parts.append(f"{cleaned}{punct}")

    out: list[str] = []
    keys: list[str] = []
    for part in parts:
        key = re.sub(r"[。！？]$", "", part).replace("，", "")
        while keys and key and keys[-1] and keys[-1] in key and keys[-1] != key:
            keys.pop()
            out.pop()
        if len(keys) >= 2 and f"{keys[-2]}{keys[-1]}" in key:
            keys.pop()
            out.pop()
            keys.pop()
            out.pop()
        if keys and keys[-1] == key:
            continue
        out.append(part)
        keys.append(key)
    return "".join(out)


def normalize_transcript(transcript: Any) -> tuple[Any, dict[str, Any]]:
    if not isinstance(transcript, list):
        return transcript, {"changed": False, "text_changed_count": 0, "chars_removed": 0}

    normalized: list[dict[str, Any]] = []
    changed_count = 0
    chars_removed = 0
    for item in transcript:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        if role not in {"user", "ai"}:
            role = "user" if role == "客户" else "ai" if role in {"assistant", "bot"} else role
        text = normalize_call_text(item.get("text"))
        if role == "ai":
            text = str(item.get("text") or "").strip()
        if not role or not text:
            continue
        raw_text = str(item.get("text") or "")
        if text != raw_text:
            changed_count += 1
            chars_removed += max(0, len(raw_text) - len(text))
        entry: dict[str, Any] = {"role": role, "text": text}
        if isinstance(item.get("ts"), (int, float)):
            entry["ts"] = float(item["ts"])
        normalized.append(entry)

    compacted: list[dict[str, Any]] = []
    for entry in normalized:
        if compacted and compacted[-1]["role"] == entry["role"] and compacted[-1]["text"] == entry["text"]:
            continue
        compacted.append(entry)
    return compacted, {
        "changed": compacted != transcript,
        "text_changed_count": changed_count,
        "chars_removed": chars_removed,
        "input_count": len(transcript),
        "output_count": len(compacted),
    }


def _string_list(value: Any, *, limit: int = 20) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def normalize_observations(observations: Any) -> tuple[Any, dict[str, Any]]:
    if not isinstance(observations, list):
        return observations, {"changed": False, "input_count": 0, "output_count": 0}
    allowed = (
        "place_type",
        "person_present",
        "person_count",
        "person_description",
        "looking_off_screen",
        "visible_documents",
        "document_text",
        "notable_objects",
        "anomalies",
        "caption",
        "ts",
        "image_url",
    )
    normalized: list[dict[str, Any]] = []
    for obs in observations:
        if not isinstance(obs, dict):
            continue
        entry: dict[str, Any] = {}
        for key in allowed:
            if key not in obs:
                continue
            value = obs.get(key)
            if key in {"visible_documents", "notable_objects", "anomalies"}:
                value = _string_list(value)
                if not value:
                    continue
            elif key == "person_count":
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    continue
            elif key in {"person_present", "looking_off_screen"}:
                value = bool(value)
            elif key == "ts":
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    continue
            elif isinstance(value, str):
                value = value.strip()
                if not value:
                    continue
            elif value is None:
                continue
            entry[key] = value
        if entry:
            normalized.append(entry)
    return normalized, {
        "changed": normalized != observations,
        "input_count": len(observations),
        "output_count": len(normalized),
    }


def normalize_call_payload(
    transcript: Any,
    observations: Any,
    metadata: Any,
) -> tuple[Any, Any, Any]:
    norm_transcript, transcript_stats = normalize_transcript(transcript)
    norm_observations, observation_stats = normalize_observations(observations)
    if not transcript_stats.get("changed") and not observation_stats.get("changed"):
        return norm_transcript, norm_observations, metadata

    norm_metadata = copy.deepcopy(metadata) if isinstance(metadata, dict) else {}
    norm_metadata["normalization"] = {
        "version": 1,
        "transcript": transcript_stats,
        "observations": observation_stats,
    }
    return norm_transcript, norm_observations, norm_metadata

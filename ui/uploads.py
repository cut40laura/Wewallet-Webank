from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def sanitize_filename(filename: str) -> str:
    stem = Path(filename or "upload").name
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._")
    return stem or "upload"


def upload_metadata(path: Path, original_name: str, content_type: str, enterprise_id: str) -> dict[str, Any]:
    kind = (
        "image" if content_type.startswith("image/")
        else "audio" if content_type.startswith("audio/")
        else "video" if content_type.startswith("video/")
        else "file"
    )
    return {
        "kind": kind,
        "name": original_name,
        "mime": content_type,
        "size": path.stat().st_size,
        "path": str(path),
        "url": f"/uploads/{enterprise_id}/{path.name}",
    }


def display_user_message(user_message: str, attachments: list[dict[str, Any]]) -> str:
    """Build the text that 小微 + the chat transcript will see.

    Audio attachments with a transcript are spliced into the message as
    "[语音] <transcript>" so the LLM sees the actual words the customer
    spoke, not an opaque placeholder.
    """
    parts: list[str] = []
    typed = user_message.strip()
    if typed:
        parts.append(typed)
    for item in attachments:
        if item.get("kind") == "audio":
            transcript = str(item.get("transcript") or "").strip()
            if transcript:
                parts.append(f"[语音] {transcript}")
    if parts:
        return "\n".join(parts)
    if any(item.get("kind") == "image" for item in attachments):
        return "[图片附件]"
    if any(item.get("kind") == "audio" for item in attachments):
        return "[语音附件，未能识别]"
    if any(item.get("kind") == "video" for item in attachments):
        return "[视频附件]"
    if attachments:
        return "[文件附件]"
    return "[附件]"

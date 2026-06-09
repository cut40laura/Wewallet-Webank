"""Per-enterprise image history KB.

Each enterprise has its own image KB at ``app_data/enterprises/<id>/image_kb/``.
The KB is *populated by ingest*, not by scanning a shared folder: whenever a
client uploads an image during a chat turn, we embed it after the LLM has
replied and append it to that enterprise's index. On the next turn we run a
similarity search against the customer's own history to detect "前后矛盾" —
same kind of document re-uploaded with different details.

Why a search returns nothing is just as important as why it returns something:
if max cosine < threshold we return ``[]`` so 小微's prompt sees "无相似图片
命中" and does not invent comparisons.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import requests

from config import (
    DASHSCOPE_API_KEY,
    DASHSCOPE_EMBED_MODEL,
    IMAGE_KB_IMG_THRESHOLD,
    IMAGE_KB_TOP_K,
    IMAGE_KB_TXT_THRESHOLD,
    enterprise_image_kb_dir,
)


EMBED_URL = "https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding"
EMBED_DIM = 2560
SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
SNIPPET_CHARS = 200
REQUEST_TIMEOUT_S = 60


@dataclass(frozen=True)
class ImageKnowledgeHit:
    source_path: str
    original_name: str
    captured_at: str
    score: float
    query_kind: str  # "image" or "text"

    def to_prompt_block(self, index: int) -> str:
        when = self.captured_at[:16].replace("T", " ") if self.captured_at else "未知时间"
        return (
            f"[图{index}] 客户于 {when} 上传的「{self.original_name[:60]}」\n"
            f"相似度: {self.score:.3f}（query: {self.query_kind}）"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "original_name": self.original_name,
            "captured_at": self.captured_at,
            "score": self.score,
            "query_kind": self.query_kind,
        }


class ImageKnowledgeBase:
    """Per-enterprise image KB. Cheap to construct — pass via factory."""

    def __init__(
        self,
        enterprise_id: str,
        kb_dir: Path,
        *,
        api_key: str = "",
        model: str = "qwen3-vl-embedding",
        img_threshold: float = 0.55,
        txt_threshold: float = 0.45,
    ) -> None:
        self.enterprise_id = enterprise_id
        self.kb_dir = kb_dir
        self.index_path = kb_dir / "index.npz"
        self.labels_path = kb_dir / "labels.json"
        self.api_key = api_key
        self.model = model
        self.img_threshold = img_threshold
        self.txt_threshold = txt_threshold

    # ---- public API -----------------------------------------------------

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def status(self) -> dict[str, Any]:
        items = 0
        if self.labels_path.exists():
            try:
                items = len(json.loads(self.labels_path.read_text()))
            except (OSError, json.JSONDecodeError):
                items = 0
        return {
            "enabled": self.enabled,
            "enterprise_id": self.enterprise_id,
            "model": self.model,
            "kb_dir": str(self.kb_dir),
            "items": items,
        }

    def ingest(self, image_paths: list[str | Path], original_names: list[str] | None = None) -> dict[str, Any]:
        """Embed and append client uploads to this enterprise's index.

        ``original_names`` parallels ``image_paths`` and is the filename the
        client picked (not the timestamped path on disk). Falls back to the
        filename on disk if not provided.
        """
        if not self.enabled or not image_paths:
            return {"ok": True, "ingested": 0}
        paths = [Path(p) for p in image_paths]
        names = original_names or [p.name for p in paths]
        if len(names) != len(paths):
            names = [p.name for p in paths]

        with _enterprise_lock(self.enterprise_id):
            mat, labels = self._load_or_empty()
            new_vecs: list[np.ndarray] = []
            new_labels: list[dict[str, Any]] = []
            existing = {entry["file"] for entry in labels}
            for path, name in zip(paths, names):
                if not path.exists() or path.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
                    continue
                resolved = str(path.resolve())
                if resolved in existing:
                    continue
                try:
                    vec = self._embed_image(path)
                except Exception:
                    continue
                new_vecs.append(_l2_normalize_vec(vec))
                new_labels.append(
                    {
                        "file": resolved,
                        "original_name": name,
                        "captured_at": _iso_now(),
                    }
                )
            if not new_vecs:
                return {"ok": True, "ingested": 0}
            self.kb_dir.mkdir(parents=True, exist_ok=True)
            new_mat = np.vstack(new_vecs).astype(np.float32)
            mat = np.vstack([mat, new_mat]) if mat.size else new_mat
            labels = labels + new_labels
            np.savez(self.index_path, embeddings=mat, files=np.array([l["file"] for l in labels]))
            self.labels_path.write_text(json.dumps(labels, ensure_ascii=False, indent=2))
        return {"ok": True, "ingested": len(new_vecs), "total": len(labels)}

    def search(
        self,
        *,
        text: str = "",
        image_paths: list[str] | None = None,
        top_k: int = IMAGE_KB_TOP_K,
        exclude_paths: list[str] | None = None,
    ) -> list[ImageKnowledgeHit]:
        """Return top-k history hits above threshold; empty list ⇒ no recall."""
        if not self.enabled:
            return []
        text = (text or "").strip()
        image_paths = [p for p in (image_paths or []) if p]
        if not text and not image_paths:
            return []
        try:
            mat, labels = self._load_or_empty()
        except (OSError, ValueError, json.JSONDecodeError):
            return []
        if mat.shape[0] == 0:
            return []

        exclude = {str(Path(p).resolve()) for p in (exclude_paths or [])}
        candidates: dict[str, ImageKnowledgeHit] = {}

        for path in image_paths:
            try:
                q = self._embed_image(Path(path))
            except Exception:
                continue
            self._merge_hits(q, mat, labels, self.img_threshold, "image", candidates, exclude)

        if text:
            try:
                q = self._embed_text(text)
            except Exception:
                pass
            else:
                self._merge_hits(q, mat, labels, self.txt_threshold, "text", candidates, exclude)

        return sorted(candidates.values(), key=lambda h: h.score, reverse=True)[:top_k]

    def rebuild_from_uploads(self, uploads_dir: Path) -> dict[str, Any]:
        """Re-embed every image currently in this enterprise's uploads folder.

        Escape hatch for when the index is lost or the embedding model changes.
        Old captured_at metadata is reset to the file's mtime if available.
        """
        if not self.enabled:
            return {"ok": False, "reason": "DASHSCOPE_API_KEY 未配置"}
        if not uploads_dir.exists():
            return {"ok": True, "items": 0}
        paths = sorted(p for p in uploads_dir.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES)
        if not paths:
            with _enterprise_lock(self.enterprise_id):
                if self.index_path.exists():
                    self.index_path.unlink()
                if self.labels_path.exists():
                    self.labels_path.unlink()
            return {"ok": True, "items": 0}

        vecs: list[np.ndarray] = []
        labels: list[dict[str, Any]] = []
        for path in paths:
            try:
                vec = self._embed_image(path)
            except Exception:
                continue
            vecs.append(_l2_normalize_vec(vec))
            labels.append(
                {
                    "file": str(path.resolve()),
                    "original_name": path.name,
                    "captured_at": _iso_from_mtime(path),
                }
            )
        with _enterprise_lock(self.enterprise_id):
            self.kb_dir.mkdir(parents=True, exist_ok=True)
            mat = np.vstack(vecs).astype(np.float32) if vecs else np.zeros((0, EMBED_DIM), dtype=np.float32)
            np.savez(self.index_path, embeddings=mat, files=np.array([l["file"] for l in labels]))
            self.labels_path.write_text(json.dumps(labels, ensure_ascii=False, indent=2))
        return {"ok": True, "items": len(labels)}

    # ---- internals ------------------------------------------------------

    def _merge_hits(
        self,
        q: np.ndarray,
        mat: np.ndarray,
        labels: list[dict[str, Any]],
        threshold: float,
        query_kind: str,
        sink: dict[str, ImageKnowledgeHit],
        exclude: set[str],
    ) -> None:
        q = _l2_normalize_vec(q)
        sims = mat @ q
        order = np.argsort(-sims)
        for i in order:
            score = float(sims[i])
            if score < threshold:
                break  # sorted desc; the rest are worse
            label = labels[i]
            file_key = label["file"]
            if file_key in exclude:
                continue
            current = sink.get(file_key)
            if current is None or score > current.score:
                sink[file_key] = ImageKnowledgeHit(
                    source_path=file_key,
                    original_name=str(label.get("original_name") or Path(file_key).name),
                    captured_at=str(label.get("captured_at") or ""),
                    score=score,
                    query_kind=query_kind,
                )

    def _load_or_empty(self) -> tuple[np.ndarray, list[dict[str, Any]]]:
        if not self.index_path.exists() or not self.labels_path.exists():
            return np.zeros((0, EMBED_DIM), dtype=np.float32), []
        data = np.load(self.index_path, allow_pickle=False)
        mat = data["embeddings"].astype(np.float32)
        labels = json.loads(self.labels_path.read_text())
        return mat, labels

    def _embed_image(self, path: Path) -> np.ndarray:
        return self._embed({"image": _image_to_data_uri(path)})

    def _embed_text(self, text: str) -> np.ndarray:
        return self._embed({"text": text})

    def _embed(self, content: dict, retries: int = 2) -> np.ndarray:
        payload = {"model": self.model, "input": {"contents": [content]}}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        last_err: Exception | None = None
        for attempt in range(retries + 1):
            try:
                r = requests.post(EMBED_URL, headers=headers, json=payload, timeout=REQUEST_TIMEOUT_S)
                r.raise_for_status()
                body = r.json()
                emb = body["output"]["embeddings"][0]["embedding"]
                return np.asarray(emb, dtype=np.float32)
            except Exception as exc:  # noqa: BLE001 — caller handles fallback
                last_err = exc
                time.sleep(0.4 * (attempt + 1))
        raise RuntimeError(f"image-kb embedding failed: {last_err}")


# ---- factory + locks -------------------------------------------------------


_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _enterprise_lock(enterprise_id: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(enterprise_id)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[enterprise_id] = lock
        return lock


def image_kb_for_enterprise(enterprise_id: str) -> ImageKnowledgeBase:
    return ImageKnowledgeBase(
        enterprise_id=enterprise_id,
        kb_dir=enterprise_image_kb_dir(enterprise_id),
        api_key=DASHSCOPE_API_KEY,
        model=DASHSCOPE_EMBED_MODEL,
        img_threshold=IMAGE_KB_IMG_THRESHOLD,
        txt_threshold=IMAGE_KB_TXT_THRESHOLD,
    )


# ---- module helpers --------------------------------------------------------


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _iso_from_mtime(path: Path) -> str:
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(path.stat().st_mtime))
    except OSError:
        return _iso_now()


def _image_to_data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def _l2_normalize_vec(vec: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(vec))
    return vec / (n if n > 1e-12 else 1.0)


def format_image_hits_for_prompt(hits: list[ImageKnowledgeHit]) -> str:
    if not hits:
        return "无相似图片命中。"
    return "\n\n".join(hit.to_prompt_block(i) for i, hit in enumerate(hits, 1))


def summarize_image_hits(hits: list[ImageKnowledgeHit]) -> str:
    if not hits:
        return "未匹配本企业历史图片"
    labels = []
    for hit in hits[:3]:
        labels.append(hit.original_name[:24])
    return f"命中本企业历史 {len(hits)} 张：{'；'.join(labels)}"


def image_kb_progress_events(hits: list[ImageKnowledgeHit], duration_s: float) -> list[dict[str, Any]]:
    return [
        {"type": "tool.start", "text": "started 客户历史图档", "name": "客户历史图档", "tool_id": "image-history"},
        {"type": "tool.progress", "text": summarize_image_hits(hits), "name": "客户历史图档"},
        {
            "type": "tool.complete",
            "text": f"complete 客户历史图档 {duration_s:.1f}s",
            "name": "客户历史图档",
            "status": "complete",
            "tool_id": "image-history",
        },
    ]

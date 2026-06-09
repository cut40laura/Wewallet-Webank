"""Persistence for video-call due-diligence records.

A video call is created (``start_call``) when the user connects, and filled in
(``complete_call``) when they hang up. Everything is scoped by ``enterprise_id``
so one enterprise can never read or mutate another's calls — mirroring the
``messages`` table access pattern in :mod:`enterprise`.

The AI/ML side (transcript text, structured vision observations, risk summary)
is produced upstream (browser + Doubao realtime proxy); this module only stores
and retrieves it. Variable-shape fields are kept as JSON text columns, the same
way chat messages store their payload.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

import db
from config import iso_now
from transcript_normalizer import normalize_call_payload


def _loads(value: Any) -> Any:
    if value is None or value == "":
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "enterprise_id": row["enterprise_id"],
        "user_id": row["user_id"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "status": row["status"],
        "transcript": _loads(row["transcript"]),
        "observations": _loads(row["observations"]),
        "risk": _loads(row["risk"]),
        "metadata": _loads(row["metadata"]),
        "created_ts": row["created_ts"],
    }


def start_call(enterprise_id: str, user_id: str | None) -> str:
    """Create an ``active`` call row and return its id."""
    call_id = uuid.uuid4().hex
    with db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO video_calls
                (id, enterprise_id, user_id, started_at, ended_at, status,
                 transcript, observations, risk, metadata, created_ts)
            VALUES (?, ?, ?, ?, NULL, 'active', NULL, NULL, NULL, NULL, ?)
            """,
            (call_id, enterprise_id, user_id, iso_now(), time.time()),
        )
    return call_id


def complete_call(
    call_id: str,
    enterprise_id: str,
    *,
    transcript: Any,
    observations: Any,
    risk: Any,
    metadata: Any,
) -> bool:
    """Fill in a call's results and mark it completed.

    Scoped to ``enterprise_id``; returns ``True`` if a row was updated. Safe to
    call more than once (overwrites). A wrong enterprise updates nothing.
    """
    transcript, observations, metadata = normalize_call_payload(transcript, observations, metadata)
    with db.transaction() as conn:
        cur = conn.execute(
            """
            UPDATE video_calls
               SET ended_at = ?, status = 'completed',
                   transcript = ?, observations = ?, risk = ?, metadata = ?
             WHERE id = ? AND enterprise_id = ?
            """,
            (
                iso_now(),
                json.dumps(transcript, ensure_ascii=False) if transcript is not None else None,
                json.dumps(observations, ensure_ascii=False) if observations is not None else None,
                json.dumps(risk, ensure_ascii=False) if risk is not None else None,
                json.dumps(metadata, ensure_ascii=False) if metadata is not None else None,
                call_id,
                enterprise_id,
            ),
        )
        return cur.rowcount > 0


def load_call(call_id: str, enterprise_id: str) -> dict[str, Any] | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM video_calls WHERE id = ? AND enterprise_id = ?",
            (call_id, enterprise_id),
        ).fetchone()
    return _row_to_dict(row) if row else None


def list_calls(enterprise_id: str, limit: int = 100) -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM video_calls WHERE enterprise_id = ? "
            "ORDER BY created_ts DESC LIMIT ?",
            (enterprise_id, limit),
        ).fetchall()
    return [_row_to_dict(row) for row in rows]

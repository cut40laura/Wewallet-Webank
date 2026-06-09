#!/usr/bin/env python3
"""One-shot migration: legacy JSON files → wewallet.sqlite.

Reads from ``$WEWALLET_APP_DATA_DIR`` (defaults to ``ROOT/app_data``) and
writes to ``$WEWALLET_DB`` (defaults to ``$WEWALLET_UI_DATA_DIR/wewallet.sqlite``).

Idempotent: rerunning is a no-op once every legacy file has been imported.
On success a sibling ``.migrated`` marker is written next to each JSON.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _marker(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".migrated")


def _mark_migrated(path: Path) -> None:
    if not path.exists():
        return
    marker = _marker(path)
    if not marker.exists():
        marker.write_text("ok\n", encoding="utf-8")


def _already_done(path: Path) -> bool:
    return _marker(path).exists()


def migrate(verbose: bool = True) -> dict[str, int]:
    HERE = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(HERE / "ui"))
    import config  # noqa: E402  pylint: disable=import-outside-toplevel
    import db  # noqa: E402  pylint: disable=import-outside-toplevel

    counts = {"users": 0, "enterprises": 0, "auth_sessions": 0, "sms_codes": 0, "messages": 0}

    users = _load_json(config.USERS_FILE, []) if not _already_done(config.USERS_FILE) else []
    if isinstance(users, list) and users:
        with db.transaction() as conn:
            for u in users:
                if not isinstance(u, dict) or not u.get("id") or not u.get("phone"):
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO users "
                    "(id, phone, password_hash, enterprise_id, created_at, last_login_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        u["id"],
                        u["phone"],
                        u.get("password_hash") or "",
                        u.get("enterprise_id"),
                        u.get("created_at") or "",
                        u.get("last_login_at") or u.get("created_at") or "",
                    ),
                )
                counts["users"] += 1
        _mark_migrated(config.USERS_FILE)

    enterprises = _load_json(config.ENTERPRISES_FILE, []) if not _already_done(config.ENTERPRISES_FILE) else []
    if isinstance(enterprises, list) and enterprises:
        with db.transaction() as conn:
            for e in enterprises:
                if not isinstance(e, dict) or not e.get("id"):
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO enterprises "
                    "(id, name, credit_code, owner_user_id, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        e["id"],
                        e.get("name") or "未命名企业",
                        e.get("credit_code") or "",
                        e.get("owner_user_id") or "",
                        e.get("created_at") or "",
                        e.get("updated_at"),
                    ),
                )
                counts["enterprises"] += 1
        _mark_migrated(config.ENTERPRISES_FILE)

    sessions = _load_json(config.AUTH_SESSIONS_FILE, []) if not _already_done(config.AUTH_SESSIONS_FILE) else []
    if isinstance(sessions, list) and sessions:
        with db.transaction() as conn:
            for s in sessions:
                if not isinstance(s, dict) or not s.get("token_hash"):
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO auth_sessions "
                    "(id, user_id, token_hash, created_at, expires_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        s.get("id") or f"sess_legacy_{counts['auth_sessions']}",
                        s.get("user_id") or "",
                        s["token_hash"],
                        s.get("created_at") or "",
                        int(s.get("expires_at") or 0),
                    ),
                )
                counts["auth_sessions"] += 1
        _mark_migrated(config.AUTH_SESSIONS_FILE)

    sms_codes = _load_json(config.SMS_CODES_FILE, []) if not _already_done(config.SMS_CODES_FILE) else []
    if isinstance(sms_codes, list) and sms_codes:
        with db.transaction() as conn:
            for c in sms_codes:
                if not isinstance(c, dict) or not c.get("phone") or not c.get("code_hash"):
                    continue
                conn.execute(
                    "INSERT INTO sms_codes "
                    "(phone, code_hash, created_at, created_ts, expires_at, attempt_count) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        c["phone"],
                        c["code_hash"],
                        c.get("created_at") or "",
                        int(c.get("created_ts") or 0),
                        int(c.get("expires_at") or 0),
                        int(c.get("attempt_count") or 0),
                    ),
                )
                counts["sms_codes"] += 1
        _mark_migrated(config.SMS_CODES_FILE)

    enterprises_dir = config.APP_DATA_DIR / "enterprises"
    if enterprises_dir.exists():
        for ent_dir in sorted(enterprises_dir.iterdir()):
            if not ent_dir.is_dir() or not ent_dir.name.startswith("ent_"):
                continue
            messages_file = ent_dir / "messages.json"
            if not messages_file.exists():
                continue
            marker = messages_file.with_suffix(messages_file.suffix + ".migrated")
            if marker.exists():
                continue
            messages = _load_json(messages_file, [])
            if not isinstance(messages, list):
                continue
            with db.transaction() as conn:
                existing = conn.execute(
                    "SELECT COUNT(*) AS n FROM messages WHERE enterprise_id = ?",
                    (ent_dir.name,),
                ).fetchone()["n"]
                if existing:
                    if verbose:
                        print(f"[skip] {ent_dir.name}: already has {existing} rows in DB")
                else:
                    rows = []
                    for offset, msg in enumerate(messages):
                        if not isinstance(msg, dict):
                            continue
                        rows.append((
                            ent_dir.name,
                            offset + 1,
                            json.dumps(msg, ensure_ascii=False),
                            0.0,
                        ))
                    if rows:
                        conn.executemany(
                            "INSERT INTO messages (enterprise_id, seq, payload, created_ts) "
                            "VALUES (?, ?, ?, ?)",
                            rows,
                        )
                        counts["messages"] += len(rows)
                        if verbose:
                            print(f"[ok]   {ent_dir.name}: {len(rows)} messages migrated")
            _mark_migrated(messages_file)

    if verbose:
        print("---")
        for k, v in counts.items():
            print(f"{k}: {v}")
    return counts


if __name__ == "__main__":
    migrate()

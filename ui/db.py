from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Iterator

from config import DATA_DIR


DB_PATH = Path(os.environ.get("WEWALLET_DB", DATA_DIR / "wewallet.sqlite")).expanduser()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    phone TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    enterprise_id TEXT,
    created_at TEXT NOT NULL,
    last_login_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS enterprises (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    credit_code TEXT NOT NULL DEFAULT '',
    owner_user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires ON auth_sessions(expires_at);

CREATE TABLE IF NOT EXISTS sms_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_ts INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sms_codes_phone ON sms_codes(phone, expires_at);

CREATE TABLE IF NOT EXISTS messages (
    enterprise_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    payload TEXT NOT NULL,
    created_ts REAL NOT NULL,
    PRIMARY KEY (enterprise_id, seq)
);

-- 视频通话尽调留痕（见 video_calls.py）：转写/画面观察/风控结论按 JSON 列存，
-- 风格沿用 messages 的 payload。risk 由挂断后的后台线程补写。
CREATE TABLE IF NOT EXISTS video_calls (
    id            TEXT PRIMARY KEY,
    enterprise_id TEXT NOT NULL,
    user_id       TEXT,
    started_at    TEXT,
    ended_at      TEXT NOT NULL,
    transcript    TEXT,
    observations  TEXT,
    risk          TEXT,
    metadata      TEXT,
    created_ts    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_video_calls_enterprise ON video_calls(enterprise_id, created_ts);
"""


_init_lock = Lock()
_initialized = False


def _ensure_initialized() -> None:
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), isolation_level=None, timeout=10.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript(SCHEMA)
        finally:
            conn.close()
        _initialized = True


def _open() -> sqlite3.Connection:
    _ensure_initialized()
    conn = sqlite3.connect(str(DB_PATH), isolation_level=None, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = _open()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    conn = _open()
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        conn.close()
        raise
    else:
        conn.execute("COMMIT")
        conn.close()

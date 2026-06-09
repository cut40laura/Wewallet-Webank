from __future__ import annotations

import hashlib
import os
import re
import secrets
import sqlite3
import sys
from typing import Any

from config import (
    APP_DATA_DIR,
    AUTH_SECRET_FILE,
    AUTH_SESSION_TTL_SECONDS,
    AuthError,
    SMS_CODE_TTL_SECONDS,
    iso_now,
    now_ts,
)
import db


SMS_RESEND_COOLDOWN_SECONDS = 60


def auth_secret() -> str:
    configured = os.environ.get("WEWALLET_AUTH_SECRET", "").strip()
    if configured:
        return configured
    if AUTH_SECRET_FILE.exists():
        return AUTH_SECRET_FILE.read_text(encoding="utf-8").strip()
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_urlsafe(48)
    AUTH_SECRET_FILE.write_text(secret, encoding="utf-8")
    try:
        AUTH_SECRET_FILE.chmod(0o600)
    except OSError:
        pass
    return secret


def hash_value(value: str) -> str:
    return hashlib.sha256(f"{auth_secret()}:{value}".encode("utf-8")).hexdigest()


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, salt, expected = stored_hash.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    actual = hash_password(password, salt).split("$", 2)[2]
    return secrets.compare_digest(actual, expected)


def validate_password(password: str) -> str:
    password = password or ""
    if len(password) < 8:
        raise ValueError("密码至少需要 8 位")
    if len(password) > 72:
        raise ValueError("密码过长")
    return password


def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D+", "", phone or "")
    if len(digits) != 11 or not digits.startswith("1"):
        raise ValueError("请输入有效的 11 位手机号")
    return digits


def mask_phone(phone: str) -> str:
    return f"{phone[:3]}****{phone[-4:]}" if len(phone) == 11 else phone


def _row_to_user(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "phone": row["phone"],
        "password_hash": row["password_hash"],
        "enterprise_id": row["enterprise_id"],
        "created_at": row["created_at"],
        "last_login_at": row["last_login_at"],
    }


def find_user_by_phone(phone: str) -> dict[str, Any] | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE phone = ?", (phone,)).fetchone()
    return _row_to_user(row) if row else None


def find_user_by_id(user_id: str) -> dict[str, Any] | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _row_to_user(row) if row else None


def create_user(phone: str, password: str) -> dict[str, Any]:
    password = validate_password(password)
    user = {
        "id": f"user_{secrets.token_hex(6)}",
        "phone": phone,
        "password_hash": hash_password(password),
        "enterprise_id": None,
        "created_at": iso_now(),
        "last_login_at": iso_now(),
    }
    try:
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO users (id, phone, password_hash, enterprise_id, created_at, last_login_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    user["id"],
                    user["phone"],
                    user["password_hash"],
                    user["enterprise_id"],
                    user["created_at"],
                    user["last_login_at"],
                ),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError("该手机号已注册，请直接登录") from exc
    return user


def mark_user_logged_in(user_id: str) -> dict[str, Any]:
    with db.transaction() as conn:
        cur = conn.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?",
            (iso_now(), user_id),
        )
        if cur.rowcount == 0:
            raise AuthError("账号不存在")
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _row_to_user(row)


def create_auth_session(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    session_id = f"sess_{secrets.token_hex(8)}"
    expires_at = now_ts() + AUTH_SESSION_TTL_SECONDS
    with db.transaction() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (now_ts(),))
        conn.execute(
            "INSERT INTO auth_sessions (id, user_id, token_hash, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, user_id, hash_value(token), iso_now(), expires_at),
        )
    return token


def verify_auth_token(token: str) -> dict[str, Any] | None:
    if not token:
        return None
    token_hash = hash_value(token)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT user_id FROM auth_sessions WHERE token_hash = ? AND expires_at > ?",
            (token_hash, now_ts()),
        ).fetchone()
    if not row:
        return None
    return find_user_by_id(str(row["user_id"]))


def revoke_auth_token(token: str) -> None:
    if not token:
        return
    with db.transaction() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (hash_value(token),))


def create_sms_code(phone: str) -> str | None:
    """Generate and store a new SMS code for `phone`.

    Returns the 6-digit code on success, or ``None`` if a code was issued
    within the last ``SMS_RESEND_COOLDOWN_SECONDS`` seconds.
    """
    code = f"{secrets.randbelow(1000000):06d}"
    now = now_ts()
    with db.transaction() as conn:
        conn.execute("DELETE FROM sms_codes WHERE expires_at <= ?", (now,))
        recent = conn.execute(
            "SELECT 1 FROM sms_codes WHERE phone = ? AND created_ts > ? LIMIT 1",
            (phone, now - SMS_RESEND_COOLDOWN_SECONDS),
        ).fetchone()
        if recent:
            return None
        conn.execute(
            "INSERT INTO sms_codes (phone, code_hash, created_at, created_ts, expires_at, attempt_count) "
            "VALUES (?, ?, ?, ?, ?, 0)",
            (
                phone,
                hash_value(f"{phone}:{code}"),
                iso_now(),
                now,
                now + SMS_CODE_TTL_SECONDS,
            ),
        )
    return code


def consume_sms_code(phone: str, code: str) -> bool:
    """Return True if `code` matches an unexpired record for `phone`, and delete it."""
    target_hash = hash_value(f"{phone}:{code}")
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT id FROM sms_codes WHERE phone = ? AND code_hash = ? AND expires_at > ? LIMIT 1",
            (phone, target_hash, now_ts()),
        ).fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM sms_codes WHERE id = ?", (row["id"],))
    return True


def send_sms_code(phone: str, code: str) -> None:
    print(f"[wewallet-sms] phone={mask_phone(phone)} code={code}", file=sys.stderr, flush=True)

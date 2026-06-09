from __future__ import annotations

import json
import secrets
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any

from config import (
    HERMES_HOME,
    TEMPLATE_FILE,
    enterprise_account_profile_file,
    enterprise_dir,
    enterprise_hermes_home,
    enterprise_hermes_template_file,
    enterprise_profile_file,
    enterprise_uploads_dir,
    enterprise_versions_dir,
    iso_now,
)
from auth import mask_phone
from storage import atomic_write_text, load_json_file, save_json_file
import db


ACCOUNT_PROFILE_FIELDS = {
    "name",
    "credit_code",
    "legal_representative",
    "city",
    "address",
    "industry",
    "main_business",
    "established_at",
    "business_years",
    "enterprise_type",
    "annual_revenue",
    "employee_count",
    "monthly_cashflow",
    "has_corporate_account",
    "payment_channels",
    "has_tax_record",
    "has_social_security",
    "funding_purpose",
    "expected_amount",
    "expected_term",
}


def ensure_enterprise_hermes_home(enterprise_id: str) -> Path:
    home = enterprise_hermes_home(enterprise_id)
    home.mkdir(parents=True, exist_ok=True)
    try:
        home.chmod(0o700)
    except OSError:
        pass
    for dirname in ("memories", "sessions", "logs", "cache", "skills", "templates"):
        (home / dirname).mkdir(parents=True, exist_ok=True)

    config_file = home / "config.yaml"
    source_config = HERMES_HOME / "config.yaml"
    if source_config.exists():
        shutil.copy2(source_config, config_file)

    source_soul = HERMES_HOME / "SOUL.md"
    if source_soul.exists():
        shutil.copy2(source_soul, home / "SOUL.md")

    for memory_file in (home / "memories" / "MEMORY.md", home / "memories" / "USER.md"):
        if not memory_file.exists():
            memory_file.write_text("", encoding="utf-8")

    if TEMPLATE_FILE.exists() and not enterprise_hermes_template_file(enterprise_id).exists():
        shutil.copy2(TEMPLATE_FILE, enterprise_hermes_template_file(enterprise_id))

    _sync_skill_if_newer(
        HERMES_HOME / "skills" / "loan-customer-manager",
        home / "skills" / "loan-customer-manager",
        substitutions={"__ENTERPRISE_PROFILE_FILE__": str(enterprise_profile_file(enterprise_id))},
    )
    _sync_skill_if_newer(
        HERMES_HOME / "skills" / "wallet-manager",
        home / "skills" / "wallet-manager",
    )
    return home


def _sync_skill_if_newer(
    source: Path,
    target: Path,
    *,
    substitutions: dict[str, str] | None = None,
) -> None:
    """Mirror ``source`` skill dir into ``target`` only when source is newer.

    Compares SKILL.md mtimes; equal/older means target is up to date and we
    skip the rmtree+copytree. New sources or edits to skill files still
    propagate automatically the next time the enterprise chats.

    When ``substitutions`` is given, applies token replacement on the copied
    SKILL.md so per-enterprise paths get baked in regardless of how the source
    was packaged (resolves the "Docker host path baked into skill text" trap).
    """
    src_skill = source / "SKILL.md"
    if not src_skill.exists():
        return
    dst_skill = target / "SKILL.md"
    if dst_skill.exists() and dst_skill.stat().st_mtime >= src_skill.stat().st_mtime:
        return
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    if substitutions:
        text = dst_skill.read_text(encoding="utf-8")
        for token, value in substitutions.items():
            text = text.replace(token, value)
        dst_skill.write_text(text, encoding="utf-8")


def _row_to_enterprise(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "credit_code": row["credit_code"],
        "owner_user_id": row["owner_user_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def new_enterprise_id() -> str:
    with db.connect() as conn:
        existing = {row["id"] for row in conn.execute("SELECT id FROM enterprises")}
    while True:
        enterprise_id = f"ent_{secrets.token_hex(6)}"
        if enterprise_id not in existing:
            return enterprise_id


def find_enterprise(enterprise_id: str) -> dict[str, Any] | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM enterprises WHERE id = ?", (enterprise_id,)).fetchone()
    return _row_to_enterprise(row) if row else None


def create_enterprise_for_user(user: dict[str, Any], name: str, credit_code: str = "") -> dict[str, Any]:
    name = (name or "").strip() or "未命名企业"
    credit_code = (credit_code or "").strip().upper()
    if user.get("enterprise_id"):
        raise ValueError("当前手机号已绑定企业，不能重复绑定")
    enterprise_id = new_enterprise_id()
    enterprise = {
        "id": enterprise_id,
        "name": name,
        "credit_code": credit_code,
        "owner_user_id": user["id"],
        "created_at": iso_now(),
        "updated_at": None,
    }
    try:
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO enterprises (id, name, credit_code, owner_user_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, NULL)",
                (
                    enterprise["id"],
                    enterprise["name"],
                    enterprise["credit_code"],
                    enterprise["owner_user_id"],
                    enterprise["created_at"],
                ),
            )
            cur = conn.execute(
                "UPDATE users SET enterprise_id = ? WHERE id = ? AND enterprise_id IS NULL",
                (enterprise_id, user["id"]),
            )
            if cur.rowcount == 0:
                raise ValueError("当前手机号已绑定企业，不能重复绑定")
    except sqlite3.IntegrityError as exc:
        raise ValueError("企业 ID 冲突，请重试") from exc

    user["enterprise_id"] = enterprise_id
    ent_dir = enterprise_dir(enterprise_id)
    ent_dir.mkdir(parents=True, exist_ok=True)
    enterprise_uploads_dir(enterprise_id).mkdir(parents=True, exist_ok=True)
    enterprise_versions_dir(enterprise_id).mkdir(parents=True, exist_ok=True)
    if not enterprise_profile_file(enterprise_id).exists():
        template = TEMPLATE_FILE.read_text(encoding="utf-8") if TEMPLATE_FILE.exists() else "# 企业风控画像\n"
        profile = template.replace("- 企业名称：", f"- 企业名称：{name}", 1)
        atomic_write_text(enterprise_profile_file(enterprise_id), profile.rstrip() + "\n")
    if not enterprise_account_profile_file(enterprise_id).exists():
        save_json_file(enterprise_account_profile_file(enterprise_id), default_account_profile(user, enterprise))
    ensure_enterprise_hermes_home(enterprise_id)
    return enterprise


def default_account_profile(user: dict[str, Any], enterprise: dict[str, Any]) -> dict[str, Any]:
    return {
        "avatar_url": "",
        "nickname": "",
        "role": "",
        "enterprise": {
            "name": enterprise.get("name") or "",
            "credit_code": enterprise.get("credit_code") or "",
            "legal_representative": "",
            "city": "",
            "address": "",
            "industry": "",
            "main_business": "",
            "established_at": "",
            "business_years": "",
            "enterprise_type": "",
            "annual_revenue": "",
            "employee_count": "",
            "monthly_cashflow": "",
            "has_corporate_account": "",
            "payment_channels": "",
            "has_tax_record": "",
            "has_social_security": "",
            "funding_purpose": "",
            "expected_amount": "",
            "expected_term": "",
        },
        "updated_at": "",
        "phone": mask_phone(str(user.get("phone") or "")),
    }


def load_account_profile(user: dict[str, Any], enterprise: dict[str, Any]) -> dict[str, Any]:
    profile = default_account_profile(user, enterprise)
    saved = load_json_file(enterprise_account_profile_file(str(enterprise["id"])), {})
    if isinstance(saved, dict):
        profile.update({key: value for key, value in saved.items() if key != "enterprise"})
        enterprise_saved = saved.get("enterprise")
        if isinstance(enterprise_saved, dict):
            profile["enterprise"].update(enterprise_saved)
    profile["phone"] = mask_phone(str(user.get("phone") or ""))
    profile["enterprise"]["name"] = profile["enterprise"].get("name") or enterprise.get("name") or ""
    profile["enterprise"]["credit_code"] = profile["enterprise"].get("credit_code") or enterprise.get("credit_code") or ""
    return profile


def save_account_profile(user: dict[str, Any], enterprise: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    profile = load_account_profile(user, enterprise)
    profile["nickname"] = str(payload.get("nickname", profile.get("nickname", "")) or "").strip()[:80]
    profile["role"] = str(payload.get("role", profile.get("role", "")) or "").strip()[:80]
    enterprise_payload = payload.get("enterprise") if isinstance(payload.get("enterprise"), dict) else {}
    for field in ACCOUNT_PROFILE_FIELDS:
        profile["enterprise"][field] = str(enterprise_payload.get(field, profile["enterprise"].get(field, "")) or "").strip()[:240]
    profile["updated_at"] = iso_now()
    save_json_file(enterprise_account_profile_file(str(enterprise["id"])), profile)

    name = str(profile["enterprise"].get("name") or "").strip() or "未命名企业"
    credit_code = str(profile["enterprise"].get("credit_code") or "").strip().upper()
    with db.transaction() as conn:
        conn.execute(
            "UPDATE enterprises SET name = ?, credit_code = ?, updated_at = ? WHERE id = ?",
            (name, credit_code, iso_now(), enterprise.get("id")),
        )
    enterprise["name"] = name
    enterprise["credit_code"] = credit_code
    return profile


def load_messages(enterprise_id: str) -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT payload FROM messages WHERE enterprise_id = ? ORDER BY seq",
            (enterprise_id,),
        ).fetchall()
    return [json.loads(row["payload"]) for row in rows]


def append_messages(enterprise_id: str, new_messages: list[dict[str, Any]]) -> None:
    if not new_messages:
        return
    with db.transaction() as conn:
        next_seq = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 AS next FROM messages WHERE enterprise_id = ?",
            (enterprise_id,),
        ).fetchone()["next"]
        ts = time.time()
        rows = [
            (
                enterprise_id,
                next_seq + offset,
                json.dumps(msg, ensure_ascii=False),
                ts,
            )
            for offset, msg in enumerate(new_messages)
        ]
        conn.executemany(
            "INSERT INTO messages (enterprise_id, seq, payload, created_ts) VALUES (?, ?, ?, ?)",
            rows,
        )


def replace_messages(enterprise_id: str, messages: list[dict[str, Any]]) -> None:
    with db.transaction() as conn:
        conn.execute("DELETE FROM messages WHERE enterprise_id = ?", (enterprise_id,))
        if not messages:
            return
        ts = time.time()
        rows = [
            (
                enterprise_id,
                offset + 1,
                json.dumps(msg, ensure_ascii=False),
                ts,
            )
            for offset, msg in enumerate(messages)
        ]
        conn.executemany(
            "INSERT INTO messages (enterprise_id, seq, payload, created_ts) VALUES (?, ?, ?, ?)",
            rows,
        )


def clear_messages(enterprise_id: str) -> None:
    with db.transaction() as conn:
        conn.execute("DELETE FROM messages WHERE enterprise_id = ?", (enterprise_id,))

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import secrets
import time
import uuid
from pathlib import Path
from typing import Any, Iterator

from config import (
    enterprise_wallet_audit_file,
    enterprise_wallet_file,
    enterprise_wallet_lock_file,
    enterprise_wallet_pending_file,
    iso_now,
)
from storage import load_json_file, save_json_file


@contextlib.contextmanager
def wallet_lock(enterprise_id: str) -> Iterator[None]:
    """Cross-process exclusive lock for any wallet read-modify-write."""
    lock_path = enterprise_wallet_lock_file(enterprise_id)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def load_pending(enterprise_id: str) -> list[dict[str, Any]]:
    items = load_json_file(enterprise_wallet_pending_file(enterprise_id), [])
    return [item for item in items if isinstance(item, dict)]


def save_pending(enterprise_id: str, pending: list[dict[str, Any]]) -> None:
    save_json_file(enterprise_wallet_pending_file(enterprise_id), pending)


def append_audit(enterprise_id: str, entry: dict[str, Any]) -> None:
    entry = dict(entry)
    entry.setdefault("ts", iso_now())
    path = enterprise_wallet_audit_file(enterprise_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line)


def normalize_wallet_type(value: str, amount: float) -> str:
    text = str(value or "").strip().lower()
    if text in {"income", "in", "收入", "收款", "入账"}:
        return "income"
    if text in {"expense", "out", "支出", "付款", "出账"}:
        return "expense"
    return "income" if amount >= 0 else "expense"


def normalize_money(value: Any) -> float:
    text = str(value or "0").replace(",", "").replace("¥", "").replace("￥", "").strip()
    try:
        return round(float(text), 2)
    except ValueError:
        return 0.0


def wallet_seed_transactions() -> list[dict[str, Any]]:
    return [
        {"id": "seed_1", "date": "2026-03-03", "description": "门店收款", "amount": 38600, "type": "income", "category": "营业收入"},
        {"id": "seed_2", "date": "2026-03-08", "description": "原材料采购", "amount": 12800, "type": "expense", "category": "采购"},
        {"id": "seed_3", "date": "2026-04-05", "description": "线上订单回款", "amount": 45200, "type": "income", "category": "营业收入"},
        {"id": "seed_4", "date": "2026-04-12", "description": "房租水电", "amount": 9800, "type": "expense", "category": "固定支出"},
        {"id": "seed_5", "date": "2026-05-02", "description": "批发客户回款", "amount": 52100, "type": "income", "category": "营业收入"},
        {"id": "seed_6", "date": "2026-05-10", "description": "员工工资", "amount": 18600, "type": "expense", "category": "人工"},
    ]


def load_wallet_transactions(enterprise_id: str) -> list[dict[str, Any]]:
    path = enterprise_wallet_file(enterprise_id)
    if not path.exists():
        save_json_file(path, wallet_seed_transactions())
    items = load_json_file(path, [])
    return [item for item in items if isinstance(item, dict)]


def save_wallet_transactions(enterprise_id: str, transactions: list[dict[str, Any]]) -> None:
    save_json_file(enterprise_wallet_file(enterprise_id), transactions[-500:])


def normalize_wallet_transaction(payload: dict[str, Any]) -> dict[str, Any]:
    amount = abs(normalize_money(payload.get("amount")))
    tx_type = normalize_wallet_type(str(payload.get("type", "")), normalize_money(payload.get("amount")))
    return {
        "id": str(payload.get("id") or f"tx_{secrets.token_hex(6)}"),
        "date": str(payload.get("date") or time.strftime("%Y-%m-%d")).strip()[:10],
        "description": str(payload.get("description") or payload.get("摘要") or "流水").strip()[:120],
        "amount": amount,
        "type": tx_type,
        "category": str(payload.get("category") or "未分类").strip()[:40],
        "created_at": str(payload.get("created_at") or iso_now()),
    }


def _pop_pending(enterprise_id: str, pending_id: str) -> dict[str, Any]:
    pending = load_pending(enterprise_id)
    remaining = [item for item in pending if item.get("id") != pending_id]
    if len(remaining) == len(pending):
        raise KeyError(pending_id)
    matched = next(item for item in pending if item.get("id") == pending_id)
    save_pending(enterprise_id, remaining)
    return matched


def apply_pending(enterprise_id: str, pending_id: str) -> dict[str, Any]:
    """Apply a pending proposal to the main transactions store.

    Caller must hold wallet_lock. Returns dict describing the applied change.
    """
    proposal = _pop_pending(enterprise_id, pending_id)
    action = str(proposal.get("action") or "")
    transactions = load_wallet_transactions(enterprise_id)
    result: dict[str, Any] = {"action": action, "pending_id": pending_id}

    if action == "add":
        payload = dict(proposal.get("payload") or {})
        payload.setdefault("id", f"tx_{secrets.token_hex(6)}")
        tx = normalize_wallet_transaction(payload)
        transactions.append(tx)
        result["tx"] = tx
    elif action == "update":
        target_id = str(proposal.get("target_id") or "")
        idx = next((i for i, item in enumerate(transactions) if item.get("id") == target_id), -1)
        if idx < 0:
            raise KeyError(f"target transaction {target_id} not found")
        merged = dict(transactions[idx])
        for key, value in (proposal.get("payload") or {}).items():
            if value is not None and value != "":
                merged[key] = value
        merged["id"] = target_id
        transactions[idx] = normalize_wallet_transaction(merged)
        result["before"] = dict(transactions[idx])
        result["tx"] = transactions[idx]
    elif action == "delete":
        target_id = str(proposal.get("target_id") or "")
        idx = next((i for i, item in enumerate(transactions) if item.get("id") == target_id), -1)
        if idx < 0:
            raise KeyError(f"target transaction {target_id} not found")
        result["tx"] = transactions.pop(idx)
    else:
        raise ValueError(f"unknown pending action: {action}")

    save_wallet_transactions(enterprise_id, transactions)
    append_audit(enterprise_id, {
        "action": "user.confirm",
        "pending_id": pending_id,
        "proposal_action": action,
        "tx": result.get("tx"),
        "explanation": proposal.get("explanation") or "",
    })
    return result


def reject_pending(enterprise_id: str, pending_id: str) -> dict[str, Any]:
    proposal = _pop_pending(enterprise_id, pending_id)
    append_audit(enterprise_id, {
        "action": "user.reject",
        "pending_id": pending_id,
        "proposal_action": proposal.get("action"),
        "explanation": proposal.get("explanation") or "",
    })
    return {"pending_id": pending_id, "action": proposal.get("action")}


def wallet_summary(transactions: list[dict[str, Any]]) -> dict[str, Any]:
    income = sum(float(item.get("amount", 0) or 0) for item in transactions if item.get("type") == "income")
    expense = sum(float(item.get("amount", 0) or 0) for item in transactions if item.get("type") == "expense")
    monthly: dict[str, dict[str, float]] = {}
    for item in transactions:
        month = str(item.get("date") or "")[:7] or "未知"
        monthly.setdefault(month, {"income": 0.0, "expense": 0.0})
        key = "income" if item.get("type") == "income" else "expense"
        monthly[month][key] += float(item.get("amount", 0) or 0)
    months = [
        {"month": month, "income": round(data["income"], 2), "expense": round(data["expense"], 2), "net": round(data["income"] - data["expense"], 2)}
        for month, data in sorted(monthly.items())[-6:]
    ]
    avg_income = income / max(1, len(months))
    avg_expense = expense / max(1, len(months))
    return {
        "income": round(income, 2),
        "expense": round(expense, 2),
        "net": round(income - expense, 2),
        "transaction_count": len(transactions),
        "months": months,
        "plan": {
            "avg_monthly_income": round(avg_income, 2),
            "avg_monthly_expense": round(avg_expense, 2),
            "suggested_reserve": round(avg_expense * 3, 2),
            "suggested_reinvestment": round(max(avg_income - avg_expense, 0) * 0.35, 2),
        },
    }

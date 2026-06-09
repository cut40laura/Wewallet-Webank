from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
UI_DIR = ROOT / "ui"
STATIC_DIR = UI_DIR / "static"
DATA_DIR = Path(os.environ.get("WEWALLET_UI_DATA_DIR", UI_DIR / "data")).expanduser()
APP_DATA_DIR = Path(os.environ.get("WEWALLET_APP_DATA_DIR", ROOT / "app_data")).expanduser()
USERS_FILE = APP_DATA_DIR / "users.json"
ENTERPRISES_FILE = APP_DATA_DIR / "enterprises.json"
SMS_CODES_FILE = APP_DATA_DIR / "sms_codes.json"
AUTH_SESSIONS_FILE = APP_DATA_DIR / "auth_sessions.json"
AUTH_SECRET_FILE = APP_DATA_DIR / ".auth_secret"
AUTH_COOKIE_NAME = "wewallet_session"
SMS_CODE_TTL_SECONDS = 300
AUTH_SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
HERMES_HOME = Path(os.environ.get("HERMES_HOME", ROOT / ".hermes-customer-manager")).expanduser()
HERMES_AGENT_DIR = Path(os.environ.get("HERMES_AGENT_DIR", Path.home() / ".hermes" / "hermes-agent")).expanduser()
ENTERPRISE_HERMES_ROOT = Path(os.environ.get("WEWALLET_ENTERPRISE_HERMES_ROOT", APP_DATA_DIR / "hermes_homes")).expanduser()
PROFILE_FILE = Path(os.environ.get("WEWALLET_PROFILE_FILE", ROOT / "customer-risk-profile.md")).expanduser()
CASE_FILE = PROFILE_FILE
LEGACY_CASE_FILE = HERMES_HOME / "case-files" / "test-customer-001.md"
LEGACY_PROFILE_FILE = ROOT / "客户风险画像.md"
TEMPLATE_FILE = HERMES_HOME / "templates" / "customer-risk-profile.md"
KNOWLEDGE_RAW_DIR = Path(os.environ.get("CUSTOMER_MANAGER_KB_DIR", ROOT / "knowledge" / "raw")).expanduser()
KNOWLEDGE_DB_FILE = Path(os.environ.get("CUSTOMER_MANAGER_KB_DB", DATA_DIR / "knowledge.sqlite")).expanduser()
KNOWLEDGE_TOP_K = int(os.environ.get("CUSTOMER_MANAGER_KB_TOP_K", "5"))
IMAGE_KB_TOP_K = int(os.environ.get("CUSTOMER_MANAGER_IMG_KB_TOP_K", "3"))
IMAGE_KB_IMG_THRESHOLD = float(os.environ.get("CUSTOMER_MANAGER_IMG_KB_IMG_THRESHOLD", "0.55"))
IMAGE_KB_TXT_THRESHOLD = float(os.environ.get("CUSTOMER_MANAGER_IMG_KB_TXT_THRESHOLD", "0.45"))
DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "").strip()
DASHSCOPE_EMBED_MODEL = os.environ.get("DASHSCOPE_EMBED_MODEL", "qwen3-vl-embedding").strip()
DASHSCOPE_ASR_MODEL = os.environ.get("DASHSCOPE_ASR_MODEL", "qwen3-asr-flash").strip()
ASR_MAX_AUDIO_BYTES = int(os.environ.get("CUSTOMER_MANAGER_ASR_MAX_BYTES", str(8 * 1024 * 1024)))
REASONING_TAGS = ("think", "reasoning", "thinking", "thought", "REASONING_SCRATCHPAD")
GATEWAY_REQUEST_TIMEOUT = 180.0
GATEWAY_TURN_TIMEOUT = 300.0
AUTO_PROFILE_INTERVAL = 10
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
GATEWAY_IDLE_TIMEOUT_SECONDS = int(os.environ.get("WEWALLET_GATEWAY_IDLE_S", str(30 * 60)))
GATEWAY_SWEEP_INTERVAL_SECONDS = int(os.environ.get("WEWALLET_GATEWAY_SWEEP_S", str(5 * 60)))
# 小微自己连续多少轮没做贷款工作（只共情/闲聊）后，提示她温和拉回主航道。
# 度量的是 assistant 的回复而非客户消息，所以阈值比"看客户关键词"时低。
OFFTOPIC_STEER_TURNS = int(os.environ.get("WEWALLET_OFFTOPIC_STEER_TURNS", "4"))
# 注入聊天 prompt 的风控画像最大字数（防止 prompt 过长）。
PROFILE_DIGEST_MAX_CHARS = int(os.environ.get("WEWALLET_PROFILE_DIGEST_MAX_CHARS", "3000"))


class AuthError(Exception):
    pass


class EnterpriseRequired(AuthError):
    pass


def now_ts() -> int:
    return int(time.time())


def is_truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def enterprise_dir(enterprise_id: str) -> Path:
    if not re.fullmatch(r"ent_[a-f0-9]{12}", enterprise_id or ""):
        raise ValueError("企业 ID 无效")
    return APP_DATA_DIR / "enterprises" / enterprise_id


def enterprise_profile_file(enterprise_id: str) -> Path:
    return enterprise_dir(enterprise_id) / "profile.md"


def enterprise_profile_state_file(enterprise_id: str) -> Path:
    return enterprise_dir(enterprise_id) / "profile_state.json"


def enterprise_wallet_file(enterprise_id: str) -> Path:
    return enterprise_dir(enterprise_id) / "wallet_transactions.json"


def enterprise_wallet_pending_file(enterprise_id: str) -> Path:
    return enterprise_dir(enterprise_id) / "wallet_pending.json"


def enterprise_wallet_audit_file(enterprise_id: str) -> Path:
    return enterprise_dir(enterprise_id) / "wallet_audit.jsonl"


def enterprise_wallet_lock_file(enterprise_id: str) -> Path:
    return enterprise_dir(enterprise_id) / "wallet.lock"


def enterprise_account_profile_file(enterprise_id: str) -> Path:
    return enterprise_dir(enterprise_id) / "account_profile.json"


def enterprise_loan_estimate_file(enterprise_id: str) -> Path:
    return enterprise_dir(enterprise_id) / "loan_estimate.json"


def enterprise_uploads_dir(enterprise_id: str) -> Path:
    return enterprise_dir(enterprise_id) / "uploads"


def enterprise_image_kb_dir(enterprise_id: str) -> Path:
    return enterprise_dir(enterprise_id) / "image_kb"


def enterprise_versions_dir(enterprise_id: str) -> Path:
    return enterprise_dir(enterprise_id) / "versions"


def enterprise_hermes_home(enterprise_id: str) -> Path:
    if not re.fullmatch(r"ent_[a-f0-9]{12}", enterprise_id or ""):
        raise ValueError("企业 ID 无效")
    return ENTERPRISE_HERMES_ROOT / enterprise_id


def enterprise_hermes_template_file(enterprise_id: str) -> Path:
    return enterprise_hermes_home(enterprise_id) / "templates" / "customer-risk-profile.md"

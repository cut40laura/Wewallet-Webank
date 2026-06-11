from __future__ import annotations

import os
import re
import secrets
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _load_dotenv(path: Path) -> None:
    """Fill *missing* env vars from a ``.env`` file (never overrides real env).

    The project historically read everything from ``os.environ`` but never
    actually loaded ``.env``. This minimal loader makes ``.env`` work without
    pulling in python-dotenv; existing exported vars always win.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(ROOT / ".env")
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
# 视频通话模块：火山方舟(Ark) Doubao 多模态模型，既当大脑又看摄像头帧。
ARK_API_KEY = os.environ.get("ARK_API_KEY", "").strip()
ARK_BASE_URL = os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").strip()
VOICECALL_MODEL = os.environ.get("WEWALLET_VOICECALL_MODEL", "doubao-seed-2-0-pro-260215").strip()
# 看摄像头帧的视觉模型（describe_frame 用）：Doubao 多模态，走 Ark /chat/completions。
ARK_VISION_MODEL = os.environ.get("WEWALLET_ARK_VISION_MODEL", "doubao-1.6-vision").strip()
# 看画面用哪家：ark（Doubao doubao-1.6-vision）| stepfun（step-3.7-flash）。
VOICECALL_VISION_PROVIDER = os.environ.get("WEWALLET_VOICECALL_VISION_PROVIDER", "ark").strip().lower()
# StepFun(阶跃星辰)：另一套 OpenAI 兼容的通话大脑，可整体平替 Ark。
#   - step-3.7-flash：旗舰多模态推理模型，原生支持图片，能看摄像头帧 → 当大脑。
#   - stepaudio-2.5-realtime：端到端实时语音模型（WebSocket），是日后替换浏览器
#     占位 STT/TTS 的目标，本轮仅登记凭证、暂未接线。
STEP_API_KEY = os.environ.get("STEP_API_KEY", "").strip()
STEP_BASE_URL = os.environ.get("STEP_BASE_URL", "https://api.stepfun.com/step_plan/v1").strip()
STEP_VOICECALL_MODEL = os.environ.get("WEWALLET_STEP_VOICECALL_MODEL", "step-3.7-flash").strip()
STEP_REALTIME_MODEL = os.environ.get("WEWALLET_STEP_REALTIME_MODEL", "stepaudio-2.5-realtime").strip()
# 实时语音音色（session.update 里用）。默认 jingdiannvsheng=经典女声，可换/复刻。
STEP_REALTIME_VOICE = os.environ.get("WEWALLET_STEP_REALTIME_VOICE", "jingdiannvsheng").strip()
# 通话大脑用哪家：ark（火山方舟 Doubao）| stepfun（阶跃 step-3.7-flash）。
VOICECALL_PROVIDER = os.environ.get("WEWALLET_VOICECALL_PROVIDER", "ark").strip().lower()
# 端到端实时语音中继：浏览器 WebSocket 设不了请求头，且凭证不能进前端，所以本地起一个
# asyncio WS 中继（voicecall_relay.py）：浏览器 ⇄ 中继(注入凭证) ⇄ 上游(豆包/StepFun)。
# 中继和 server.py 同进程跑在独立线程，监听独立端口。
STEP_REALTIME_WSS = os.environ.get(
    "WEWALLET_STEP_REALTIME_WSS",
    "wss://api.stepfun.com/step_plan/v1/realtime?model=" + STEP_REALTIME_MODEL,
).strip()
VOICECALL_RELAY_HOST = os.environ.get("WEWALLET_VOICECALL_RELAY_HOST", "127.0.0.1").strip()
VOICECALL_RELAY_PORT = int(os.environ.get("WEWALLET_VOICECALL_RELAY_PORT", "8789"))
# 前端连中继用的 ws 地址，三选一（按优先级）：
#   1) PUBLIC_URL：完整地址，如 wss://host/relay（跨域/特殊场景才用）。
#   2) RELAY_PATH：同源路径，如 /voicecall-relay —— 生产推荐：nginx 把这个路径反代到
#      中继，前端按当前页协议自动 ws/wss（http→ws、https→wss），免去硬编码域名。
#   3) 都不设：本地开发，前端按 ws://<当前主机名>:<RELAY_PORT> 直连。
VOICECALL_RELAY_PUBLIC_URL = os.environ.get("WEWALLET_VOICECALL_RELAY_PUBLIC_URL", "").strip()
VOICECALL_RELAY_PATH = os.environ.get("WEWALLET_VOICECALL_RELAY_PATH", "").strip()
# ── 端到端实时语音·豆包 openspeech 实时对话（volc.speech.dialog）──
# 字节跳动 openspeech 的「实时对话大模型」：ASR+LLM+TTS 一体，二进制帧协议（非 OpenAI
# 兼容），由 voicecall_doubao.py 编解码、voicecall_relay.py 桥接。鉴权用 App ID + Access
# Key（控制台「实时对话」开通后获取）；也兼容只填 X-Api-Key 的新版鉴权。
DOUBAO_REALTIME_WS_URL = os.environ.get(
    "WEWALLET_DOUBAO_REALTIME_WS_URL",
    "wss://openspeech.bytedance.com/api/v3/realtime/dialogue",
).strip()
DOUBAO_REALTIME_APP_ID = os.environ.get("DOUBAO_REALTIME_APP_ID", "").strip()
DOUBAO_REALTIME_ACCESS_KEY = os.environ.get("DOUBAO_REALTIME_ACCESS_KEY", "").strip()
DOUBAO_REALTIME_API_KEY = os.environ.get("DOUBAO_REALTIME_API_KEY", "").strip()
DOUBAO_REALTIME_APP_KEY = os.environ.get("DOUBAO_REALTIME_APP_KEY", "PlgvMymc7f3tQnJ6").strip()
DOUBAO_REALTIME_RESOURCE_ID = os.environ.get("DOUBAO_REALTIME_RESOURCE_ID", "volc.speech.dialog").strip()
DOUBAO_REALTIME_MODEL_VERSION = os.environ.get("WEWALLET_DOUBAO_REALTIME_MODEL_VERSION", "1.2.1.1").strip()
# TTS 音色（speaker）。zh_female_vv_jupiter_bigtts=自然女声；可换其它 bigtts 音色。
DOUBAO_REALTIME_TTS_SPEAKER = os.environ.get("WEWALLET_DOUBAO_REALTIME_TTS_SPEAKER", "zh_female_vv_jupiter_bigtts").strip()
# 降延迟两项（见 voicecall_doubao.build_session_config）：判定"说完"的静音窗口 ms（600 默认偏慢，
# 400 更快接话）；ASR 两遍（更准但更慢，默认关）。停顿被抢话就把窗口调大、转写变糙就开 twopass。
DOUBAO_REALTIME_END_WINDOW_MS = int(os.environ.get("WEWALLET_DOUBAO_REALTIME_END_WINDOW_MS", "400"))
DOUBAO_REALTIME_ASR_TWOPASS = os.environ.get("WEWALLET_DOUBAO_REALTIME_ASR_TWOPASS", "0").strip() in {"1", "true", "True"}
# 实时语音用哪家：doubao（openspeech 实时对话）| stepfun（stepaudio-2.5-realtime）。
VOICECALL_REALTIME_PROVIDER = os.environ.get("WEWALLET_VOICECALL_REALTIME_PROVIDER", "doubao").strip().lower()


def doubao_realtime_ready() -> bool:
    """豆包实时对话凭证是否齐全（App ID+Access Key，或新版 X-Api-Key）。"""
    return bool((DOUBAO_REALTIME_APP_ID and DOUBAO_REALTIME_ACCESS_KEY) or DOUBAO_REALTIME_API_KEY)


def realtime_voice_ready() -> bool:
    """当前所选实时语音 provider 的凭证是否齐全（决定 realtime 后端能否启用）。"""
    if VOICECALL_REALTIME_PROVIDER == "stepfun":
        return bool(STEP_API_KEY)
    return doubao_realtime_ready()


# 通话语音后端：realtime（端到端实时语音）| placeholder（浏览器原生 STT/TTS 占位）。
# realtime 需要所选 provider 的凭证；缺凭证时前端自动回落 placeholder。
VOICECALL_VOICE_BACKEND = os.environ.get("WEWALLET_VOICECALL_VOICE_BACKEND", "realtime").strip().lower()
# 中继访问令牌：中继本身不带鉴权，公网暴露时谁连上都能用你的 STEP_API_KEY。所以要求
# 连接带对 token——登录后的前端从 /api/voicecall/realtime-config（需登录）领，中继校验。
# 不设则每次启动随机生成（前端每次加载现取，够用）；要固定可用环境变量。
VOICECALL_RELAY_TOKEN = os.environ.get("WEWALLET_VOICECALL_RELAY_TOKEN", "").strip() or secrets.token_urlsafe(24)
ASR_MAX_AUDIO_BYTES = int(os.environ.get("CUSTOMER_MANAGER_ASR_MAX_BYTES", str(8 * 1024 * 1024)))
REASONING_TAGS = ("think", "reasoning", "thinking", "thought", "REASONING_SCRATCHPAD")
GATEWAY_REQUEST_TIMEOUT = 180.0
GATEWAY_TURN_TIMEOUT = 300.0
AUTO_PROFILE_INTERVAL = int(os.environ.get("WEWALLET_AUTO_PROFILE_INTERVAL", "20"))
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

#!/usr/bin/env python3
from __future__ import annotations

import csv
import errno
import io
import json
import mimetypes
import os
import re
import secrets
import sys
import time
import traceback
import uuid
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote

from config import (
    AUTH_COOKIE_NAME,
    AUTH_SESSION_TTL_SECONDS,
    AUTO_PROFILE_INTERVAL,
    MAX_UPLOAD_BYTES,
    SMS_CODE_TTL_SECONDS,
    STATIC_DIR,
    AuthError,
    EnterpriseRequired,
    enterprise_account_profile_file,
    enterprise_uploads_dir,
    is_truthy,
    iso_now,
    now_ts,
)
from auth import (
    consume_sms_code,
    create_auth_session,
    create_sms_code,
    create_user,
    find_user_by_phone,
    mark_user_logged_in,
    mask_phone,
    normalize_phone,
    revoke_auth_token,
    send_sms_code,
    validate_password,
    verify_auth_token,
    verify_password,
)
from enterprise import (
    append_messages,
    clear_messages,
    create_enterprise_for_user,
    find_enterprise,
    load_account_profile,
    load_messages,
    replace_messages,
    save_account_profile,
)
from gateway import gateway_for_enterprise, start_gateway_sweeper
from security import bucket_for_path, check_csrf, check_rate_limit
from profile_service import (
    KNOWLEDGE,
    KNOWLEDGE_TOP_K,
    build_call_memory_context,
    build_gateway_chat_turn,
    extract_upload_request,
    knowledge_progress_events,
    load_profile_markdown,
    load_profile_state,
    load_loan_estimate,
    maybe_schedule_auto_profile_update,
    rule_based_suggestions,
    run_loan_estimate,
    summarize_knowledge_hits,
    user_turn_count,
)
from image_knowledge import (
    image_kb_for_enterprise,
    image_kb_progress_events,
    summarize_image_hits,
)
from config import IMAGE_KB_TOP_K
from storage import save_json_file
from uploads import display_user_message, sanitize_filename, upload_metadata
from asr import transcribe_audio
from voicecall import call_xiaowei, mint_call_token
from transcript_normalizer import normalize_transcript
import video_calls
from config import (
    VOICECALL_RELAY_HOST,
    VOICECALL_RELAY_PORT,
    VOICECALL_RELAY_PUBLIC_URL,
    VOICECALL_RELAY_PATH,
    VOICECALL_RELAY_TOKEN,
    VOICECALL_VOICE_BACKEND,
    realtime_voice_ready,
)
from wallet import (
    apply_pending,
    load_pending,
    load_wallet_transactions,
    normalize_wallet_transaction,
    reject_pending,
    save_wallet_transactions,
    wallet_lock,
    wallet_summary,
)
import threading


EmitFn = Callable[[str, dict[str, Any]], None]


def _asr_progress_events(attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Surface ASR only when it failed.

    Transcription happened inside ``read_multipart_chat`` (synchronously, so
    the transcript could land in the prompt). Successful ASR is visible as
    user text already, so reporting it again in progress makes the chat noisy.
    """
    events: list[dict[str, Any]] = []
    for item in attachments:
        if item.get("kind") != "audio":
            continue
        transcript = str(item.get("transcript") or "").strip()
        error = str(item.get("transcript_error") or "").strip()
        if transcript:
            continue
        elif error:
            status_text = "未能识别语音"
        else:
            continue
        events.extend([
            {"type": "tool.start", "text": "started 语音识别", "name": "语音识别", "tool_id": "asr"},
            {"type": "tool.progress", "text": status_text, "name": "语音识别"},
            {
                "type": "tool.complete",
                "text": "complete 语音识别",
                "name": "语音识别",
                "status": "complete" if transcript else "error",
                "tool_id": "asr",
            },
        ])
    return events


def _schedule_image_ingest(enterprise_id: str, image_attachments: list[dict[str, Any]]) -> None:
    """Embed and append client-uploaded images to this enterprise's image KB.

    Runs in a daemon thread so chat latency is unaffected. Errors are
    swallowed — a failed ingest just means the next turn won't see this
    image in history, which is acceptable.
    """
    if not image_attachments:
        return
    paths = [str(item["path"]) for item in image_attachments if item.get("path")]
    names = [str(item.get("name") or "") for item in image_attachments]

    def worker() -> None:
        try:
            image_kb_for_enterprise(enterprise_id).ingest(paths, names)
        except Exception:
            pass

    threading.Thread(target=worker, name=f"image-ingest-{enterprise_id}", daemon=True).start()


def _stream_text_chunks(text: str, emit: EmitFn, *, delay_s: float = 0.012) -> None:
    """Fallback visual streaming for providers that only return final text."""
    for char in text:
        emit("message.delta", {"text": char})
        if delay_s > 0:
            time.sleep(delay_s)


def _generate_suggestions(
    enterprise_id: str,
    messages: list[dict[str, Any]],
    user_message: str,
    assistant_content: str,
    enterprise: dict[str, Any],
) -> list[str]:
    """Quick follow-up chips, generated by local rules (no model call).

    Previously this fired a second gateway/LLM call per turn, roughly doubling
    perceived latency. The chips are simple canned follow-ups, so a keyword
    ruleset produces them instantly and keeps the chat turn to a single model
    call.
    """
    return rule_based_suggestions(messages, user_message, assistant_content, enterprise)


def _ensure_latest_suggestions(
    enterprise_id: str,
    messages: list[dict[str, Any]],
    enterprise: dict[str, Any],
) -> list[str]:
    """Backfill chips for the latest completed assistant message."""
    assistant_index = -1
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get("role") == "assistant" and str(message.get("content") or "").strip():
            assistant_index = index
            break
    if assistant_index < 0:
        return []
    assistant_message = messages[assistant_index]
    if assistant_message.get("suggestions"):
        return []

    user_message = ""
    for index in range(assistant_index - 1, -1, -1):
        message = messages[index]
        if message.get("role") == "user":
            user_message = str(message.get("content") or "")
            break

    suggestions = _generate_suggestions(
        enterprise_id,
        messages[:assistant_index],
        user_message,
        str(assistant_message.get("content") or ""),
        enterprise,
    )
    if suggestions:
        assistant_message["suggestions"] = suggestions
        replace_messages(enterprise_id, messages)
    return suggestions


def run_chat_turn(
    enterprise_id: str,
    enterprise: dict[str, Any],
    user_message: str,
    attachments: list[dict[str, Any]],
    *,
    emit: EmitFn | None = None,
) -> dict[str, Any]:
    """One chat turn: knowledge search → image KB → gateway → suggestions → persist.

    Shared by ``/api/chat`` (emit=None) and ``/api/chat/stream`` (emit writes
    NDJSON events). Keeping a single pipeline means a behavior fix in one
    endpoint can't silently miss the other.

    Returns the payload both endpoints hand back to the client:
    ``{"messages", "auto_profile", "wallet_pending"}``.
    """
    messages = load_messages(enterprise_id)
    display_message = display_user_message(user_message, attachments)
    image_attachments = [item for item in attachments if item.get("kind") == "image"]
    image_paths = [str(item["path"]) for item in image_attachments]

    asr_events = _asr_progress_events(attachments)
    if emit:
        for ev in asr_events:
            emit(ev["type"], {"name": ev.get("name"), "tool_id": ev.get("tool_id"), "preview": ev.get("text")})

    if emit:
        emit("tool.start", {"name": "本地知识库", "tool_id": "local-knowledge"})
    knowledge_started_at = time.monotonic()
    try:
        knowledge_hits = KNOWLEDGE.search(display_message, top_k=KNOWLEDGE_TOP_K)
    except Exception as exc:
        if emit:
            emit("tool.complete", {
                "name": "本地知识库",
                "tool_id": "local-knowledge",
                "duration_s": time.monotonic() - knowledge_started_at,
                "error": str(exc),
            })
        raise
    knowledge_duration = time.monotonic() - knowledge_started_at
    if emit:
        emit("tool.progress", {"name": "本地知识库", "preview": summarize_knowledge_hits(knowledge_hits)})
        emit("tool.complete", {
            "name": "本地知识库",
            "tool_id": "local-knowledge",
            "duration_s": knowledge_duration,
        })
    local_progress = asr_events + knowledge_progress_events(knowledge_hits, knowledge_duration)

    image_kb = image_kb_for_enterprise(enterprise_id)
    if emit:
        emit("tool.start", {"name": "客户历史图档", "tool_id": "image-history"})
    image_kb_started_at = time.monotonic()
    try:
        image_hits = image_kb.search(
            text=display_message,
            image_paths=image_paths,
            top_k=IMAGE_KB_TOP_K,
            exclude_paths=image_paths,
        )
    except Exception as exc:
        # 图档检索失败不致命：跳过图档继续走纯文本/知识库流程。
        image_hits = []
        if emit:
            emit("tool.complete", {
                "name": "客户历史图档",
                "tool_id": "image-history",
                "duration_s": time.monotonic() - image_kb_started_at,
                "error": str(exc),
            })
    else:
        image_kb_duration = time.monotonic() - image_kb_started_at
        if emit:
            emit("tool.progress", {"name": "客户历史图档", "preview": summarize_image_hits(image_hits)})
            emit("tool.complete", {
                "name": "客户历史图档",
                "tool_id": "image-history",
                "duration_s": image_kb_duration,
            })
        local_progress = local_progress + image_kb_progress_events(image_hits, image_kb_duration)

    gateway_delta_count = 0
    gateway_emit: EmitFn | None = None
    if emit:
        def gateway_emit(event_type: str, payload: dict[str, Any]) -> None:
            nonlocal gateway_delta_count
            if event_type == "message.delta":
                gateway_delta_count += 1
            emit(event_type, payload)

    result = gateway_for_enterprise(enterprise_id).submit(
        f"chat:{enterprise_id}",
        build_gateway_chat_turn(messages, display_message, enterprise, knowledge_hits, image_hits, attachments),
        image_paths=image_paths,
        event_callback=gateway_emit,
    )
    cleaned_content, upload_request = extract_upload_request(result["content"])
    if emit and gateway_delta_count == 0 and cleaned_content.strip():
        _stream_text_chunks(cleaned_content, emit)
    assistant_message: dict[str, Any] = {
        "role": "assistant",
        "content": cleaned_content,
        "thinking": result["thinking"],
        "progress": local_progress + result["progress"],
        "inline_diffs": result["inline_diffs"],
    }
    if upload_request:
        assistant_message["upload_request"] = upload_request
    suggestions = _generate_suggestions(
        enterprise_id,
        messages,
        display_message,
        cleaned_content,
        enterprise,
    )
    if suggestions:
        assistant_message["suggestions"] = suggestions
    new_messages = [
        {"role": "user", "content": display_message, "attachments": attachments},
        assistant_message,
    ]
    append_messages(enterprise_id, new_messages)
    messages.extend(new_messages)
    if image_attachments:
        _schedule_image_ingest(enterprise_id, image_attachments)
    auto_profile = maybe_schedule_auto_profile_update(enterprise_id, enterprise, messages)
    return {
        "messages": messages,
        "auto_profile": auto_profile,
        "wallet_pending": load_pending(enterprise_id),
    }


class Handler(BaseHTTPRequestHandler):
    # ── 路由表 ────────────────────────────────────────────────────────────
    # path -> (handler 方法名, 认证级别)。认证级别声明式地写在路由上，
    # dispatcher 统一校验，handler 拿到的就是已验证的 user/enterprise——
    # 不会再出现"新端点忘了加 current_context()"的漏洞。
    #   public:     无需登录（handler 收到 user=None, enterprise=None）
    #   user:       需登录（enterprise 可能为 None）
    #   enterprise: 需登录且已绑定企业
    GET_ROUTES: dict[str, tuple[str, str]] = {
        "/healthz": ("get_healthz", "public"),
        "/api/voicecall/realtime-config": ("get_voicecall_realtime_config", "public"),
        "/api/auth/me": ("get_auth_me", "public"),
        "/api/messages": ("get_messages", "enterprise"),
        "/api/profile": ("get_profile", "enterprise"),
        "/api/loan/estimate": ("get_loan_estimate", "enterprise"),
        "/api/account/profile": ("get_account_profile", "enterprise"),
        "/api/wallet": ("get_wallet", "enterprise"),
        "/api/wallet/pending": ("get_wallet_pending", "enterprise"),
        "/api/knowledge/status": ("get_knowledge_status", "user"),
        "/api/image-knowledge/status": ("get_image_knowledge_status", "enterprise"),
        "/api/video-calls": ("get_video_calls", "enterprise"),
    }
    POST_ROUTES: dict[str, tuple[str, str]] = {
        "/api/auth/sms/send": ("post_auth_sms_send", "public"),
        "/api/auth/sms/verify": ("post_auth_sms_verify", "public"),
        "/api/auth/password/login": ("post_auth_password_login", "public"),
        "/api/auth/register": ("post_auth_register", "public"),
        "/api/auth/logout": ("post_auth_logout", "public"),
        "/api/messages/suggestions": ("post_messages_suggestions", "enterprise"),
        "/api/voicecall": ("post_voicecall", "enterprise"),
        "/api/voicecall/end": ("post_voicecall_end", "enterprise"),
        "/api/account/profile": ("post_account_profile", "enterprise"),
        "/api/account/avatar": ("post_account_avatar", "enterprise"),
        "/api/wallet/transaction": ("post_wallet_transaction", "enterprise"),
        "/api/wallet/import": ("post_wallet_import", "enterprise"),
        "/api/enterprise/create": ("post_enterprise_create", "user"),
        "/api/chat": ("post_chat", "enterprise"),
        "/api/chat/stream": ("post_chat_stream", "enterprise"),
        # 重建索引是重操作（全量 embedding），必须登录才能触发。
        "/api/knowledge/reindex": ("post_knowledge_reindex", "user"),
        "/api/image-knowledge/reindex": ("post_image_knowledge_reindex", "enterprise"),
        "/api/reset": ("post_reset", "enterprise"),
        "/api/loan/estimate": ("post_loan_estimate", "enterprise"),
        "/api/profile/refresh": ("post_profile_refresh", "enterprise"),
    }

    # ── 认证 / 公共上下文 ─────────────────────────────────────────────────
    def cookie_value(self, name: str) -> str:
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            key, _, value = part.strip().partition("=")
            if key == name:
                return value
        return ""

    def current_user(self) -> dict[str, Any]:
        user = verify_auth_token(self.cookie_value(AUTH_COOKIE_NAME))
        if not user:
            raise AuthError("请先登录")
        return user

    def current_context(self) -> tuple[dict[str, Any], dict[str, Any]]:
        user = self.current_user()
        enterprise_id = str(user.get("enterprise_id") or "")
        if not enterprise_id:
            raise EnterpriseRequired("请先绑定企业")
        enterprise = find_enterprise(enterprise_id)
        if not enterprise:
            raise EnterpriseRequired("企业信息不存在，请重新绑定")
        return user, enterprise

    def auth_payload(self) -> dict[str, Any]:
        user = verify_auth_token(self.cookie_value(AUTH_COOKIE_NAME))
        if not user:
            return {"authenticated": False}
        return self.auth_payload_for_user(user)

    def auth_payload_for_user(self, user: dict[str, Any]) -> dict[str, Any]:
        enterprise = find_enterprise(str(user.get("enterprise_id") or "")) if user.get("enterprise_id") else None
        return {
            "authenticated": True,
            "user": {
                "id": user.get("id"),
                "phone": mask_phone(str(user.get("phone") or "")),
                "has_enterprise": bool(user.get("enterprise_id")),
            },
            "enterprise": enterprise,
            "needs_enterprise": enterprise is None,
        }

    # ── 分发 ──────────────────────────────────────────────────────────────
    def _dispatch(self, routes: dict[str, tuple[str, str]], path: str) -> bool:
        """Look up ``path`` in the route table; resolve auth, then call the handler.

        Returns False when the path is not in the table (caller falls through
        to prefix routes / 404).
        """
        entry = routes.get(path)
        if not entry:
            return False
        handler_name, auth_level = entry
        user: dict[str, Any] | None = None
        enterprise: dict[str, Any] | None = None
        if auth_level == "user":
            user = self.current_user()
        elif auth_level == "enterprise":
            user, enterprise = self.current_context()
        getattr(self, handler_name)(user, enterprise)
        return True

    # ── 前端分端（desktop / mobile）─────────────────────────────────────────
    # 优先级：?ua= 强制参数（写 cookie 记住）> ui_variant cookie > User-Agent 嗅探。
    # 开发调试用 /chat?ua=mobile / /chat?ua=desktop 即可在桌面浏览器看另一端。
    UI_VARIANT_COOKIE = "ui_variant"

    def detect_ui_variant(self) -> tuple[str, bool]:
        """返回 (variant, 是否需要写 cookie)。variant ∈ {"desktop", "mobile"}。"""
        query = parse_qs(self.path.partition("?")[2])
        forced = (query.get("ua") or [""])[0].strip().lower()
        if forced in ("desktop", "mobile"):
            return forced, True
        remembered = self.cookie_value(self.UI_VARIANT_COOKIE)
        if remembered in ("desktop", "mobile"):
            return remembered, False
        agent = self.headers.get("User-Agent", "")
        is_mobile = bool(re.search(r"Mobi|Android|iPhone|iPod|Windows Phone", agent, re.IGNORECASE))
        return ("mobile" if is_mobile else "desktop"), False

    def send_chat_page(self) -> None:
        variant, remember = self.detect_ui_variant()
        page = STATIC_DIR / variant / "chat.html"
        if not page.exists() or not page.is_file():
            self.send_error(404)
            return
        body = page.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        # 同一 URL 按 UA/cookie 返回不同内容，提示缓存层据此区分
        self.send_header("Vary", "User-Agent, Cookie")
        if remember:
            self.send_header(
                "Set-Cookie",
                f"{self.UI_VARIANT_COOKIE}={variant}; Path=/; Max-Age=2592000; SameSite=Lax",
            )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        try:
            path = unquote(self.path.split("?", 1)[0])
            if path in ("", "/", "/chat"):
                self.send_chat_page()
                return
            if self._dispatch(self.GET_ROUTES, path):
                return
            if path.startswith("/static/"):
                self.get_static(path)
                return
            if path.startswith("/uploads/"):
                self.get_upload(path)
                return
            self.send_error(404)
        except EnterpriseRequired as exc:
            self.send_json({"error": str(exc), "needs_enterprise": True}, status=403)
        except AuthError as exc:
            self.send_json({"error": str(exc), "authenticated": False}, status=401)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=400)
        except Exception as exc:
            self.send_internal_error(exc)

    def do_POST(self) -> None:
        try:
            if not check_csrf(
                self.headers.get("Origin", ""),
                self.headers.get("Referer", ""),
                self.headers.get("Host", ""),
            ):
                self.send_json({"error": "请求来源校验失败"}, status=403)
                return
            bucket = bucket_for_path(self.path)
            if bucket:
                client_ip = self.client_address[0] if self.client_address else ""
                if not check_rate_limit(client_ip, bucket):
                    self.send_json({"error": "请求过于频繁，请稍后再试"}, status=429)
                    return
            if self._dispatch(self.POST_ROUTES, self.path):
                return
            if self.path.startswith("/api/wallet/pending/"):
                self.post_wallet_pending_action()
                return
            self.send_error(404)
        except EnterpriseRequired as exc:
            self.send_json({"error": str(exc), "needs_enterprise": True}, status=403)
        except AuthError as exc:
            self.send_json({"error": str(exc), "authenticated": False}, status=401)
        except ValueError as exc:
            # ValueError 携带的是面向用户的中文提示（手机号格式、上传过大等）。
            self.send_json({"error": str(exc)}, status=400)
        except Exception as exc:
            self.send_internal_error(exc)

    INTERNAL_ERROR_MESSAGE = "服务器开小差了，请稍后再试"

    def send_internal_error(self, exc: Exception) -> None:
        """500: log the real exception server-side, return a generic message.

        Raw exception text can carry internal details (gateway stderr tail,
        file paths, provider config), none of which belongs in a client
        response.
        """
        self.log_exception(exc)
        self.send_json({"error": self.INTERNAL_ERROR_MESSAGE}, status=500)

    def log_exception(self, exc: Exception) -> None:
        print(f"[wewallet] unhandled error on {self.command} {self.path}: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)

    # ── GET handlers ─────────────────────────────────────────────────────
    def get_healthz(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        self.send_json({"ok": True})

    def get_voicecall_realtime_config(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        # 告诉前端通话语音走哪条路 + 实时中继地址 + 访问令牌（仅发给已登录用户）。
        # 令牌现在**绑定该用户的 enterprise_id 并带时效**：既防公网盗用，又让中继
        # 认得出是哪个企业在通话，从而注入与主聊天共享的客户记忆（见 voicecall.mint_call_token）。
        auth_user = verify_auth_token(self.cookie_value(AUTH_COOKIE_NAME))
        enterprise_id = str((auth_user or {}).get("enterprise_id") or "")
        # 必须已登录、已绑企业，才能拿到带记忆的令牌（无企业则没有可共享的记忆）。
        enabled = bool(enterprise_id) and VOICECALL_VOICE_BACKEND == "realtime" and realtime_voice_ready()
        self.send_json({
            "backend": "realtime" if enabled else "placeholder",
            "enabled": enabled,
            "relay_port": VOICECALL_RELAY_PORT,
            # ws_url(完整) > relay_path(同源路径) > 按 host:relay_port 自拼（本地）。
            "ws_url": VOICECALL_RELAY_PUBLIC_URL,
            "relay_path": VOICECALL_RELAY_PATH,
            "token": mint_call_token(enterprise_id) if enabled else "",
        })

    def get_auth_me(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        self.send_json(self.auth_payload())

    def get_messages(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        self.send_json({"messages": load_messages(str(enterprise["id"]))})

    def get_profile(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        enterprise_id = str(enterprise["id"])
        profile_path, markdown = load_profile_markdown(enterprise_id)
        state = load_profile_state(enterprise_id)
        self.send_json({
            "path": str(profile_path),
            "markdown": markdown,
            "state": {
                "in_progress": bool(state.get("in_progress")),
                "last_profile_updated_at": state.get("last_profile_updated_at") or "",
                "last_profile_trigger": state.get("last_profile_trigger") or "",
                "last_profile_changed": bool(state.get("last_profile_changed")),
                "last_error": state.get("last_error") or "",
            },
        })

    def get_loan_estimate(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        self.send_json({"estimate": load_loan_estimate(str(enterprise["id"]))})

    def get_account_profile(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        self.send_json({"profile": load_account_profile(user, enterprise)})

    def get_wallet(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        transactions = load_wallet_transactions(str(enterprise["id"]))
        self.send_json({"transactions": transactions, "summary": wallet_summary(transactions)})

    def get_wallet_pending(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        self.send_json({"pending": load_pending(str(enterprise["id"]))})

    def get_knowledge_status(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        self.send_json(KNOWLEDGE.status())

    def get_video_calls(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        # 视频通话尽调留痕列表（本期"先只存不展示"，此端点供验证/调试/后续历史页）。
        self.send_json({"calls": video_calls.list_calls(str(enterprise["id"]))})

    def get_image_knowledge_status(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        self.send_json(image_kb_for_enterprise(str(enterprise["id"])).status())

    def get_static(self, path: str) -> None:
        target = (STATIC_DIR / path.removeprefix("/static/")).resolve()
        try:
            target.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self.send_error(403)
            return
        self.send_file(target, self.content_type(target))

    def get_upload(self, path: str) -> None:
        _user, enterprise = self.current_context()
        enterprise_id = str(enterprise["id"])
        upload_path = path.removeprefix("/uploads/")
        if not upload_path.startswith(f"{enterprise_id}/"):
            self.send_error(403)
            return
        target = (enterprise_uploads_dir(enterprise_id) / upload_path.removeprefix(f"{enterprise_id}/")).resolve()
        try:
            target.relative_to(enterprise_uploads_dir(enterprise_id).resolve())
        except ValueError:
            self.send_error(403)
            return
        self.send_file(target, self.content_type(target))

    # ── POST handlers：认证 ───────────────────────────────────────────────
    def post_auth_sms_send(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        payload = self.read_json()
        phone = normalize_phone(str(payload.get("phone", "")))
        code = create_sms_code(phone)
        if code is None:
            self.send_json({"error": "验证码发送过于频繁，请稍后再试"}, status=429)
            return
        send_sms_code(phone, code)
        payload = {"ok": True, "expires_in": SMS_CODE_TTL_SECONDS}
        # 默认关：验证码绝不能进 API 响应，否则任何人都能登录任意手机号。
        # 本地演示要在页面上直接看到验证码时，显式设 WEWALLET_SMS_DEBUG=1。
        if is_truthy(os.environ.get("WEWALLET_SMS_DEBUG", "0")):
            payload["debug_code"] = code
        self.send_json(payload)

    def post_auth_sms_verify(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        payload = self.read_json()
        phone = normalize_phone(str(payload.get("phone", "")))
        code = re.sub(r"\D+", "", str(payload.get("code", "")))
        if len(code) != 6:
            self.send_json({"error": "请输入 6 位验证码"}, status=400)
            return
        if not consume_sms_code(phone, code):
            self.send_json({"error": "验证码错误或已过期"}, status=400)
            return
        found = find_user_by_phone(phone)
        if not found:
            self.send_json({"error": "该手机号未注册，请先注册"}, status=404)
            return
        found = mark_user_logged_in(str(found["id"]))
        token = create_auth_session(str(found["id"]))
        self.send_json_with_cookie(self.auth_payload_for_user(found), token=token)

    def post_auth_password_login(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        payload = self.read_json()
        phone = normalize_phone(str(payload.get("phone", "")))
        password = str(payload.get("password", ""))
        found = find_user_by_phone(phone)
        if not found or not verify_password(password, str(found.get("password_hash") or "")):
            self.send_json({"error": "手机号或密码错误"}, status=400)
            return
        found = mark_user_logged_in(str(found["id"]))
        token = create_auth_session(str(found["id"]))
        self.send_json_with_cookie(self.auth_payload_for_user(found), token=token)

    def post_auth_register(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        payload = self.read_json()
        phone = normalize_phone(str(payload.get("phone", "")))
        password = validate_password(str(payload.get("password", "")))
        code = re.sub(r"\D+", "", str(payload.get("code", "")))
        if len(code) != 6:
            self.send_json({"error": "请输入 6 位验证码"}, status=400)
            return
        if not consume_sms_code(phone, code):
            self.send_json({"error": "验证码错误或已过期"}, status=400)
            return
        created = create_user(phone, password)
        token = create_auth_session(str(created["id"]))
        self.send_json_with_cookie(self.auth_payload_for_user(created), token=token)

    def post_auth_logout(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        revoke_auth_token(self.cookie_value(AUTH_COOKIE_NAME))
        self.send_json_with_cookie({"ok": True}, token="")

    # ── POST handlers：聊天 / 通话 ────────────────────────────────────────
    def post_messages_suggestions(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        enterprise_id = str(enterprise["id"])
        messages = load_messages(enterprise_id)
        suggestions = _ensure_latest_suggestions(enterprise_id, messages, enterprise)
        self.send_json({"ok": True, "messages": messages, "suggestions": suggestions})

    def post_voicecall(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        # 视频通话模块（通话版小微）。与主聊天共享同一份记忆：按 enterprise_id
        # 取画像+近期对话当"开场记忆"注入，让通话小微一接通就认得这位客户。
        enterprise_id = str(enterprise["id"])
        payload = self.read_json()
        transcript = str(payload.get("transcript", "")).strip()
        frame = str(payload.get("frame", "")).strip()  # data:image/...;base64,
        history = payload.get("history") if isinstance(payload.get("history"), list) else []
        if not transcript and not frame:
            self.send_json({"error": "transcript 不能为空"}, status=400)
            return
        memory_context = build_call_memory_context(enterprise_id, load_messages(enterprise_id))
        reply = call_xiaowei(transcript, history, frame, memory_context)
        self.send_json({"ok": True, "reply": reply})

    def post_voicecall_end(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        # 挂断回流：把这通通话的对话清洗后并入主聊天时间线（channel:voice），
        # 再触发画像更新——于是通话里说过的事，回到文字聊天小微也"记得"。
        enterprise_id = str(enterprise["id"])
        payload = self.read_json()
        turns = payload.get("transcript") if isinstance(payload.get("transcript"), list) else []
        normalized, stats = normalize_transcript(turns)
        voice_messages = []
        for turn in normalized or []:
            role = "assistant" if turn.get("role") == "ai" else "user"
            content = str(turn.get("content") or turn.get("text") or "").strip()
            if content:
                voice_messages.append({"role": role, "content": content, "channel": "voice"})
        auto_profile = None
        if voice_messages:
            append_messages(enterprise_id, voice_messages)
            messages = load_messages(enterprise_id)
            auto_profile = maybe_schedule_auto_profile_update(enterprise_id, enterprise, messages)

        # 尽调留痕：整通通话（转写 + relay 累积的画面观察）落库一行，风控总结
        # 在后台线程补写——这条 INSERT 是毫秒级的，不拖慢挂断响应。
        call_id = ""
        observations = video_calls.drain_observations(enterprise_id)
        contradictions = video_calls.drain_contradictions(enterprise_id)
        if voice_messages or observations or contradictions:
            metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
            metadata = {**metadata, "channel": "video", "turn_count": len(voice_messages)}
            if contradictions:
                metadata["contradictions"] = contradictions  # 实时检测明细随通话留痕
            call_id = video_calls.record_call(
                enterprise_id,
                str((user or {}).get("id") or "") or None,
                transcript=voice_messages,
                observations=observations,
                metadata=metadata,
            )
            video_calls.schedule_risk_review(
                call_id, enterprise_id, voice_messages, observations, contradictions)
        self.send_json({
            "ok": True,
            "saved": len(voice_messages),
            "auto_profile": auto_profile,
            "call_id": call_id,
        })

    def post_chat(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        enterprise_id = str(enterprise["id"])
        user_message, attachments = self.read_chat_submission(enterprise_id)
        if not user_message and not attachments:
            self.send_json({"error": "message 不能为空"}, status=400)
            return
        self.send_json(run_chat_turn(enterprise_id, enterprise, user_message, attachments))

    def post_chat_stream(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        enterprise_id = str(enterprise["id"])
        user_message, attachments = self.read_chat_submission(enterprise_id)
        if not user_message and not attachments:
            self.send_json({"error": "message 不能为空"}, status=400)
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        def emit(event_type: str, payload: dict[str, Any]) -> None:
            body = json.dumps(
                {"type": event_type, "payload": payload},
                ensure_ascii=False,
            ).encode("utf-8") + b"\n"
            self.wfile.write(body)
            self.wfile.flush()

        try:
            emit("assistant.start", {"content": "正在分析客户需求..."})
            result = run_chat_turn(enterprise_id, enterprise, user_message, attachments, emit=emit)
            emit("message.complete", result)
        except ValueError as exc:
            emit("error", {"error": str(exc)})
        except Exception as exc:
            self.log_exception(exc)
            emit("error", {"error": self.INTERNAL_ERROR_MESSAGE})

    def post_reset(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        enterprise_id = str(enterprise["id"])
        clear_messages(enterprise_id)
        gateway_for_enterprise(enterprise_id).reset_session(f"chat:{enterprise_id}")
        self.send_json({"ok": True})

    # ── POST handlers：账户 / 企业 ────────────────────────────────────────
    def post_account_profile(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        profile = save_account_profile(user, enterprise, self.read_json())
        self.send_json({"ok": True, "profile": profile, "auth": self.auth_payload_for_user(user)})

    def post_account_avatar(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        profile = self.save_account_avatar(user, enterprise)
        self.send_json({"ok": True, "profile": profile, "auth": self.auth_payload_for_user(user)})

    def post_enterprise_create(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        payload = self.read_json()
        created = create_enterprise_for_user(
            user,
            str(payload.get("name", "")),
            str(payload.get("credit_code", "")),
        )
        self.send_json({"ok": True, "enterprise": created, "auth": self.auth_payload()})

    # ── POST handlers：钱包 ───────────────────────────────────────────────
    def post_wallet_transaction(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        enterprise_id = str(enterprise["id"])
        payload = self.read_json()
        with wallet_lock(enterprise_id):
            transactions = load_wallet_transactions(enterprise_id)
            transactions.append(normalize_wallet_transaction(payload))
            save_wallet_transactions(enterprise_id, transactions)
        self.send_json({"ok": True, "transactions": transactions, "summary": wallet_summary(transactions)})

    def post_wallet_import(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        enterprise_id = str(enterprise["id"])
        with wallet_lock(enterprise_id):
            transactions = self.import_wallet_csv(enterprise_id)
        self.send_json({"ok": True, "transactions": transactions, "summary": wallet_summary(transactions)})

    def post_wallet_pending_action(self) -> None:
        tail = self.path[len("/api/wallet/pending/"):]
        pending_id, _, action = tail.partition("/")
        if action not in {"confirm", "reject"} or not pending_id:
            self.send_json({"error": "无效的 pending 操作路径"}, status=400)
            return
        _user, enterprise = self.current_context()
        enterprise_id = str(enterprise["id"])
        try:
            with wallet_lock(enterprise_id):
                if action == "confirm":
                    result = apply_pending(enterprise_id, pending_id)
                else:
                    result = reject_pending(enterprise_id, pending_id)
        except KeyError:
            self.send_json({"error": "该提案已被处理或不存在"}, status=404)
            return
        except (ValueError, RuntimeError) as exc:
            self.send_json({"error": str(exc)}, status=400)
            return
        transactions = load_wallet_transactions(enterprise_id)
        self.send_json({
            "ok": True,
            "action": action,
            "result": result,
            "pending": load_pending(enterprise_id),
            "transactions": transactions,
            "summary": wallet_summary(transactions),
        })

    # ── POST handlers：知识库 / 画像 ──────────────────────────────────────
    def post_knowledge_reindex(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        self.send_json(KNOWLEDGE.rebuild())

    def post_image_knowledge_reindex(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        enterprise_id = str(enterprise["id"])
        self.send_json(
            image_kb_for_enterprise(enterprise_id).rebuild_from_uploads(
                enterprise_uploads_dir(enterprise_id)
            )
        )

    def post_loan_estimate(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        estimate = run_loan_estimate(str(enterprise["id"]), enterprise)
        self.send_json({"estimate": estimate})

    def post_profile_refresh(self, user: dict[str, Any] | None, enterprise: dict[str, Any] | None) -> None:
        enterprise_id = str(enterprise["id"])
        messages = load_messages(enterprise_id)
        turn_count = user_turn_count(messages)
        state = load_profile_state(enterprise_id)
        last_done = int(state.get("last_profile_user_turn_count", 0) or 0)
        last_updated_at = state.get("last_profile_updated_at") or ""
        snapshot = {
            "in_progress": bool(state.get("in_progress")),
            "last_profile_updated_at": last_updated_at,
            "last_profile_trigger": state.get("last_profile_trigger") or "",
            "last_profile_changed": bool(state.get("last_profile_changed")),
            "last_error": state.get("last_error") or "",
        }

        if turn_count <= 0:
            self.send_json({
                "status": "no_messages",
                "message": "还没有对话内容，画像会在你和小微聊到第 10 轮时自动生成。",
                "state": snapshot,
            })
            return
        if state.get("in_progress"):
            self.send_json({
                "status": "in_progress",
                "message": "画像正在后台自动更新，稍候自动刷新...",
                "state": snapshot,
                "user_turn_count": turn_count,
            })
            return
        if last_done >= turn_count and last_done > 0:
            self.send_json({
                "status": "up_to_date",
                "message": f"画像已是最新（基于前 {last_done} 轮对话，于 {last_updated_at or '上次'} 生成）。",
                "state": snapshot,
                "user_turn_count": turn_count,
            })
            return
        next_auto = ((turn_count // AUTO_PROFILE_INTERVAL) + 1) * AUTO_PROFILE_INTERVAL
        if last_done <= 0:
            msg = f"画像尚未生成，当前已聊 {turn_count} 轮，第 {next_auto} 轮时会自动生成。"
        else:
            msg = (
                f"画像基于前 {last_done} 轮对话；当前已聊到第 {turn_count} 轮，"
                f"新增对话将在第 {next_auto} 轮时自动并入。"
            )
        self.send_json({
            "status": "stale",
            "message": msg,
            "state": snapshot,
            "user_turn_count": turn_count,
            "next_auto_turn": next_auto,
        })

    # ── 请求体解析 ────────────────────────────────────────────────────────
    # JSON 请求体上限：最大的合法负载是 /api/voicecall 的 base64 摄像头帧
    # （JPEG 一帧 base64 后通常 <1MB），4MB 留足余量。multipart 走
    # MAX_UPLOAD_BYTES，这里只管 JSON——没有上限就是一个内存耗尽入口。
    MAX_JSON_BYTES = 4 * 1024 * 1024

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length > self.MAX_JSON_BYTES:
            raise ValueError("请求体过大")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def read_chat_submission(self, enterprise_id: str) -> tuple[str, list[dict[str, Any]]]:
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("multipart/form-data"):
            return self.read_multipart_chat(content_type, enterprise_id)
        payload = self.read_json()
        return str(payload.get("message", "")).strip(), []

    def read_multipart_chat(self, content_type: str, enterprise_id: str) -> tuple[str, list[dict[str, Any]]]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length > MAX_UPLOAD_BYTES:
            raise ValueError("上传文件过大")
        raw = self.rfile.read(length) if length else b""
        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + raw
        )
        fields: dict[str, str] = {}
        attachments: list[dict[str, Any]] = []
        if not message.is_multipart():
            return "", []
        for part in message.iter_parts():
            disposition = part.get_content_disposition()
            if disposition != "form-data":
                continue
            name = part.get_param("name", header="content-disposition") or ""
            filename = part.get_filename()
            payload = part.get_payload(decode=True) or b""
            if filename:
                content_type_part = part.get_content_type() or mimetypes.guess_type(filename)[0] or "application/octet-stream"
                if len(payload) > MAX_UPLOAD_BYTES:
                    raise ValueError(f"{filename} 超过上传大小限制")
                upload_dir = enterprise_uploads_dir(enterprise_id)
                upload_dir.mkdir(parents=True, exist_ok=True)
                clean_name = sanitize_filename(filename)
                suffix = Path(clean_name).suffix or mimetypes.guess_extension(content_type_part) or ".bin"
                target = upload_dir / f"{int(time.time())}-{uuid.uuid4().hex}{suffix}"
                target.write_bytes(payload)
                meta = upload_metadata(target, clean_name, content_type_part, enterprise_id)
                if meta.get("kind") == "audio":
                    asr = transcribe_audio(target)
                    if asr.get("text"):
                        meta["transcript"] = asr["text"]
                    if asr.get("emotion"):
                        meta["transcript_emotion"] = asr["emotion"]
                    if asr.get("language"):
                        meta["transcript_language"] = asr["language"]
                    if asr.get("error"):
                        meta["transcript_error"] = asr["error"]
                attachments.append(meta)
            elif name:
                fields[name] = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        return fields.get("message", "").strip(), attachments

    def save_account_avatar(self, user: dict[str, Any], enterprise: dict[str, Any]) -> dict[str, Any]:
        enterprise_id = str(enterprise["id"])
        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("multipart/form-data"):
            raise ValueError("请上传头像图片")
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length > 5 * 1024 * 1024:
            raise ValueError("头像文件不能超过 5MB")
        raw = self.rfile.read(length) if length else b""
        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + raw
        )
        if not message.is_multipart():
            raise ValueError("请上传头像图片")
        saved_url = ""
        for part in message.iter_parts():
            if part.get_content_disposition() != "form-data":
                continue
            if (part.get_param("name", header="content-disposition") or "") != "avatar":
                continue
            filename = part.get_filename() or "avatar.png"
            payload = part.get_payload(decode=True) or b""
            content_type_part = part.get_content_type() or mimetypes.guess_type(filename)[0] or "application/octet-stream"
            if not content_type_part.startswith("image/"):
                raise ValueError("头像只支持图片")
            if not payload:
                raise ValueError("头像文件为空")
            suffix = Path(sanitize_filename(filename)).suffix or mimetypes.guess_extension(content_type_part) or ".png"
            upload_dir = enterprise_uploads_dir(enterprise_id)
            upload_dir.mkdir(parents=True, exist_ok=True)
            target = upload_dir / f"account-avatar-{int(time.time())}-{uuid.uuid4().hex}{suffix}"
            target.write_bytes(payload)
            saved_url = f"/uploads/{enterprise_id}/{target.name}"
            break
        if not saved_url:
            raise ValueError("请上传头像图片")
        profile = load_account_profile(user, enterprise)
        profile["avatar_url"] = saved_url
        profile["updated_at"] = iso_now()
        save_json_file(enterprise_account_profile_file(enterprise_id), profile)
        return profile

    def import_wallet_csv(self, enterprise_id: str) -> list[dict[str, Any]]:
        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("multipart/form-data"):
            raise ValueError("请上传 CSV 流水文件")
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length > 5 * 1024 * 1024:
            raise ValueError("流水文件不能超过 5MB")
        raw = self.rfile.read(length) if length else b""
        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + raw
        )
        csv_bytes = b""
        if message.is_multipart():
            for part in message.iter_parts():
                if part.get_content_disposition() == "form-data" and (part.get_param("name", header="content-disposition") or "") == "file":
                    csv_bytes = part.get_payload(decode=True) or b""
                    break
        if not csv_bytes:
            raise ValueError("请上传 CSV 流水文件")
        text = csv_bytes.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        imported: list[dict[str, Any]] = []
        for row in reader:
            amount = row.get("amount") or row.get("金额") or row.get("交易金额") or row.get("收支金额")
            imported.append(normalize_wallet_transaction({
                "date": row.get("date") or row.get("日期") or row.get("交易日期"),
                "description": row.get("description") or row.get("摘要") or row.get("交易摘要") or row.get("备注"),
                "amount": amount,
                "type": row.get("type") or row.get("类型") or row.get("收支类型"),
                "category": row.get("category") or row.get("分类") or row.get("用途"),
            }))
        transactions = load_wallet_transactions(enterprise_id) + imported
        save_wallet_transactions(enterprise_id, transactions)
        return transactions

    # ── 响应输出 ──────────────────────────────────────────────────────────
    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json_with_cookie(self, payload: dict, status: int = 200, *, token: str | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if token is not None:
            if token:
                cookie = (
                    f"{AUTH_COOKIE_NAME}={token}; HttpOnly; SameSite=Lax; "
                    f"Path=/; Max-Age={AUTH_SESSION_TTL_SECONDS}"
                )
            else:
                cookie = f"{AUTH_COOKIE_NAME}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0"
            if is_truthy(os.environ.get("WEWALLET_COOKIE_SECURE", "0")):
                cookie += "; Secure"
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, content_type: str) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def content_type(path: Path) -> str:
        suffix = path.suffix.lower()
        return {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".m4a": "audio/mp4",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".ogg": "audio/ogg",
            ".webm": "video/webm",
            ".mp4": "video/mp4",
            ".mov": "video/quicktime",
            ".pdf": "application/pdf",
            ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xls": "application/vnd.ms-excel",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".csv": "text/csv; charset=utf-8",
            ".txt": "text/plain; charset=utf-8",
            ".svg": "image/svg+xml",
        }.get(suffix, "application/octet-stream")

    def log_message(self, fmt: str, *args) -> None:
        return


def main() -> None:
    host = os.environ.get("CUSTOMER_MANAGER_UI_HOST", "127.0.0.1")
    preferred_port = int(os.environ.get("CUSTOMER_MANAGER_UI_PORT", "8787"))
    server = None
    port = preferred_port
    for candidate in range(preferred_port, preferred_port + 20):
        try:
            server = ThreadingHTTPServer((host, candidate), Handler)
            port = candidate
            break
        except OSError as exc:
            if exc.errno not in {errno.EADDRINUSE, 48, 98}:
                raise
    if server is None:
        raise OSError(f"No available port in range {preferred_port}-{preferred_port + 19}")
    start_gateway_sweeper()
    # 端到端实时语音中继（缺所选 provider 凭证则不启，前端自动回落占位语音）。
    try:
        from voicecall_relay import start_relay_thread
        if start_relay_thread():
            print(f"Voicecall realtime relay: ws://{VOICECALL_RELAY_HOST}:{VOICECALL_RELAY_PORT}", flush=True)
    except Exception as exc:
        print(f"[voicecall_relay] not started: {exc}", flush=True)
    print(f"Customer manager UI: http://{host}:{port}/chat", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

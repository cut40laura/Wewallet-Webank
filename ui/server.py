#!/usr/bin/env python3
from __future__ import annotations

import base64
import csv
import errno
import io
import json
import mimetypes
import os
import re
import secrets
import tempfile
import time
import uuid
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote

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
    add_open_verifications,
    build_call_memory,
    build_gateway_chat_turn,
    build_suggestions_prompt,
    extract_upload_request,
    knowledge_progress_events,
    load_profile_markdown,
    load_profile_state,
    load_loan_estimate,
    maybe_schedule_auto_profile_update,
    parse_suggestions,
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
from knowledge import format_hits_for_prompt
from storage import save_json_file
from uploads import display_user_message, sanitize_filename, upload_metadata
from asr import transcribe_audio
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
import video_calls
import threading


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


def _verifications_from_risk(risk: Any, *, channel_label: str = "视频通话") -> list[dict[str, Any]]:
    """Turn a call's risk.contradictions into cross-channel verification items.

    ``channel_label`` names the channel the疑点 surfaced in (e.g. "视频通话" /
    "语音通话") so the回写 summary reads naturally for either call type.
    """
    if not isinstance(risk, dict):
        return []
    contradictions = risk.get("contradictions")
    if not isinstance(contradictions, list):
        return []
    items: list[dict[str, Any]] = []
    for c in contradictions:
        if not isinstance(c, dict):
            continue
        field = str(c.get("field") or "").strip()
        stated = str(c.get("stated") or "").strip()
        known = str(c.get("known") or "").strip()
        if not (field or stated or known):
            continue
        summary = (
            f"{field or '某项信息'}：{channel_label}中“{stated or '—'}”，与既有记录“{known or '—'}”不一致，待核实"
        )
        items.append({"field": field, "stated": stated, "known": known, "summary": summary})
    return items


def _video_image_history_hits(enterprise_id: str, image_data_url: str) -> list[dict[str, Any]]:
    """Cross-reference a live video frame against the enterprise's historical
    image KB (materials the client uploaded in past chats).

    Returns recall hits (name/time/similarity) so the call can surface
    "客户历史上传过类似材料" for cross-checking. Empty when the KB is disabled
    (no DASHSCOPE_API_KEY), empty, or the frame isn't a usable image.
    """
    if not isinstance(image_data_url, str) or not image_data_url.startswith("data:image"):
        return []
    image_kb = image_kb_for_enterprise(enterprise_id)
    if not image_kb.enabled:
        return []
    try:
        b64 = image_data_url.split("base64,", 1)[1] if "base64," in image_data_url else ""
        raw = base64.b64decode(b64) if b64 else b""
    except Exception:
        return []
    if not raw:
        return []
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(prefix="vc-frame-", suffix=".jpg", delete=False) as fh:
            fh.write(raw)
            tmp_path = fh.name
        hits = image_kb.search(image_paths=[tmp_path], top_k=IMAGE_KB_TOP_K)
        return [h.to_dict() for h in hits]
    except Exception:
        return []
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _persist_observation_frames(
    enterprise_id: str, call_id: str, observations: Any
) -> Any:
    """Persist the actual camera frame attached to each observation as a file
    and replace the inline base64 ``image`` with a served ``image_url``.

    Keeps the DB row small (no base64 blobs) while letting the call record show
    each captured frame next to its structured text. Frames land under the
    enterprise uploads dir so the existing ``/uploads/`` route serves them.
    """
    if not isinstance(observations, list):
        return observations
    safe_call = re.sub(r"[^A-Za-z0-9_-]", "", str(call_id or ""))[:64] or "call"
    frame_dir = enterprise_uploads_dir(enterprise_id) / "video-calls" / safe_call
    made_dir = False
    for idx, obs in enumerate(observations):
        if not isinstance(obs, dict):
            continue
        image = obs.pop("image", None)  # 不把 base64 大字段写进 DB，只留 image_url
        if not isinstance(image, str) or not image:
            continue
        try:
            b64 = image.split("base64,", 1)[1] if "base64," in image else image
            raw = base64.b64decode(b64, validate=False)
        except Exception:
            continue
        if not raw or len(raw) > MAX_UPLOAD_BYTES:
            continue
        if not made_dir:
            frame_dir.mkdir(parents=True, exist_ok=True)
            made_dir = True
        try:
            ts = int(float(obs.get("ts") or time.time()))
        except (TypeError, ValueError):
            ts = int(time.time())
        name = f"frame-{idx:03d}-{ts}.jpg"
        try:
            (frame_dir / name).write_bytes(raw)
        except OSError:
            continue
        obs["image_url"] = f"/uploads/{enterprise_id}/video-calls/{safe_call}/{name}"
    return observations


def _stream_text_chunks(text: str, emit: Any, *, delay_s: float = 0.012) -> None:
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
    """Generate quick follow-up chips in an isolated gateway session."""
    try:
        result = gateway_for_enterprise(enterprise_id).submit(
            f"suggestions:{enterprise_id}",
            build_suggestions_prompt(messages, user_message, assistant_content, enterprise),
            timeout=20.0,
        )
    except Exception:
        return []
    return parse_suggestions(str(result.get("content") or ""))


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


class Handler(BaseHTTPRequestHandler):
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

    def do_GET(self) -> None:
        try:
            path = unquote(self.path.split("?", 1)[0])
            if path in ("", "/", "/chat"):
                self.send_file(STATIC_DIR / "chat.html", "text/html; charset=utf-8")
                return
            if path == "/healthz":
                self.send_json({"ok": True})
                return
            if path == "/api/auth/me":
                self.send_json(self.auth_payload())
                return
            if path == "/api/messages":
                _user, enterprise = self.current_context()
                self.send_json({"messages": load_messages(str(enterprise["id"]))})
                return
            if path == "/api/profile":
                _user, enterprise = self.current_context()
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
                return
            if path == "/api/loan/estimate":
                _user, enterprise = self.current_context()
                self.send_json({"estimate": load_loan_estimate(str(enterprise["id"]))})
                return
            if path == "/api/account/profile":
                user, enterprise = self.current_context()
                self.send_json({"profile": load_account_profile(user, enterprise)})
                return
            if path == "/api/wallet":
                _user, enterprise = self.current_context()
                transactions = load_wallet_transactions(str(enterprise["id"]))
                self.send_json({"transactions": transactions, "summary": wallet_summary(transactions)})
                return
            if path == "/api/wallet/pending":
                _user, enterprise = self.current_context()
                self.send_json({"pending": load_pending(str(enterprise["id"]))})
                return
            if path == "/api/knowledge/status":
                self.send_json(KNOWLEDGE.status())
                return
            if path == "/api/image-knowledge/status":
                _user, enterprise = self.current_context()
                self.send_json(image_kb_for_enterprise(str(enterprise["id"])).status())
                return
            if path == "/api/video-call":
                _user, enterprise = self.current_context()
                self.send_json({"calls": video_calls.list_calls(str(enterprise["id"]))})
                return
            if path.startswith("/api/video-call/"):
                _user, enterprise = self.current_context()
                call_id = path[len("/api/video-call/"):]
                call = video_calls.load_call(call_id, str(enterprise["id"]))
                if call is None:
                    self.send_json({"error": "通话记录不存在"}, status=404)
                    return
                self.send_json({"call": call})
                return
            if path.startswith("/static/"):
                target = (STATIC_DIR / path.removeprefix("/static/")).resolve()
                try:
                    target.relative_to(STATIC_DIR.resolve())
                except ValueError:
                    self.send_error(403)
                    return
                self.send_file(target, self.content_type(target))
                return
            if path.startswith("/uploads/"):
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
                return
            self.send_error(404)
        except EnterpriseRequired as exc:
            self.send_json({"error": str(exc), "needs_enterprise": True}, status=403)
        except AuthError as exc:
            self.send_json({"error": str(exc), "authenticated": False}, status=401)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)

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
            if self.path == "/api/auth/sms/send":
                payload = self.read_json()
                phone = normalize_phone(str(payload.get("phone", "")))
                code = create_sms_code(phone)
                if code is None:
                    self.send_json({"error": "验证码发送过于频繁，请稍后再试"}, status=429)
                    return
                send_sms_code(phone, code)
                payload = {"ok": True, "expires_in": SMS_CODE_TTL_SECONDS}
                if is_truthy(os.environ.get("WEWALLET_SMS_DEBUG", "1")):
                    payload["debug_code"] = code
                self.send_json(payload)
                return
            if self.path == "/api/auth/sms/verify":
                payload = self.read_json()
                phone = normalize_phone(str(payload.get("phone", "")))
                code = re.sub(r"\D+", "", str(payload.get("code", "")))
                if len(code) != 6:
                    self.send_json({"error": "请输入 6 位验证码"}, status=400)
                    return
                if not consume_sms_code(phone, code):
                    self.send_json({"error": "验证码错误或已过期"}, status=400)
                    return
                user = find_user_by_phone(phone)
                if not user:
                    self.send_json({"error": "该手机号未注册，请先注册"}, status=404)
                    return
                user = mark_user_logged_in(str(user["id"]))
                token = create_auth_session(str(user["id"]))
                self.send_json_with_cookie(self.auth_payload_for_user(user), token=token)
                return
            if self.path == "/api/auth/password/login":
                payload = self.read_json()
                phone = normalize_phone(str(payload.get("phone", "")))
                password = str(payload.get("password", ""))
                user = find_user_by_phone(phone)
                if not user or not verify_password(password, str(user.get("password_hash") or "")):
                    self.send_json({"error": "手机号或密码错误"}, status=400)
                    return
                user = mark_user_logged_in(str(user["id"]))
                token = create_auth_session(str(user["id"]))
                self.send_json_with_cookie(self.auth_payload_for_user(user), token=token)
                return
            if self.path == "/api/auth/register":
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
                user = create_user(phone, password)
                token = create_auth_session(str(user["id"]))
                self.send_json_with_cookie(self.auth_payload_for_user(user), token=token)
                return
            if self.path == "/api/auth/logout":
                revoke_auth_token(self.cookie_value(AUTH_COOKIE_NAME))
                self.send_json_with_cookie({"ok": True}, token="")
                return
            if self.path == "/api/messages/suggestions":
                _user, enterprise = self.current_context()
                enterprise_id = str(enterprise["id"])
                messages = load_messages(enterprise_id)
                suggestions = _ensure_latest_suggestions(enterprise_id, messages, enterprise)
                self.send_json({"ok": True, "messages": messages, "suggestions": suggestions})
                return
            if self.path == "/api/account/profile":
                user, enterprise = self.current_context()
                profile = save_account_profile(user, enterprise, self.read_json())
                self.send_json({"ok": True, "profile": profile, "auth": self.auth_payload_for_user(user)})
                return
            if self.path == "/api/account/avatar":
                user, enterprise = self.current_context()
                profile = self.save_account_avatar(user, enterprise)
                self.send_json({"ok": True, "profile": profile, "auth": self.auth_payload_for_user(user)})
                return
            if self.path == "/api/wallet/transaction":
                _user, enterprise = self.current_context()
                enterprise_id = str(enterprise["id"])
                payload = self.read_json()
                with wallet_lock(enterprise_id):
                    transactions = load_wallet_transactions(enterprise_id)
                    transactions.append(normalize_wallet_transaction(payload))
                    save_wallet_transactions(enterprise_id, transactions)
                self.send_json({"ok": True, "transactions": transactions, "summary": wallet_summary(transactions)})
                return
            if self.path == "/api/wallet/import":
                _user, enterprise = self.current_context()
                enterprise_id = str(enterprise["id"])
                with wallet_lock(enterprise_id):
                    transactions = self.import_wallet_csv(enterprise_id)
                self.send_json({"ok": True, "transactions": transactions, "summary": wallet_summary(transactions)})
                return
            if self.path == "/api/enterprise/create":
                user = self.current_user()
                payload = self.read_json()
                enterprise = create_enterprise_for_user(
                    user,
                    str(payload.get("name", "")),
                    str(payload.get("credit_code", "")),
                )
                self.send_json({"ok": True, "enterprise": enterprise, "auth": self.auth_payload()})
                return
            if self.path == "/api/chat":
                _user, enterprise = self.current_context()
                enterprise_id = str(enterprise["id"])
                user_message, attachments = self.read_chat_submission(enterprise_id)
                if not user_message and not attachments:
                    self.send_json({"error": "message 不能为空"}, status=400)
                    return
                display_message = display_user_message(user_message, attachments)
                image_attachments = [item for item in attachments if item.get("kind") == "image"]
                image_paths = [str(item["path"]) for item in image_attachments]
                messages = load_messages(enterprise_id)
                local_progress = _asr_progress_events(attachments)
                knowledge_started_at = time.monotonic()
                knowledge_hits = KNOWLEDGE.search(display_message, top_k=KNOWLEDGE_TOP_K)
                local_progress.extend(knowledge_progress_events(knowledge_hits, time.monotonic() - knowledge_started_at))
                image_kb = image_kb_for_enterprise(enterprise_id)
                image_kb_started_at = time.monotonic()
                try:
                    image_hits = image_kb.search(
                        text=display_message,
                        image_paths=image_paths,
                        top_k=IMAGE_KB_TOP_K,
                        exclude_paths=image_paths,
                    )
                except Exception:
                    image_hits = []
                local_progress.extend(
                    image_kb_progress_events(image_hits, time.monotonic() - image_kb_started_at)
                )
                result = gateway_for_enterprise(enterprise_id).submit(
                    f"chat:{enterprise_id}",
                    build_gateway_chat_turn(messages, display_message, enterprise, knowledge_hits, image_hits, attachments),
                    image_paths=image_paths,
                )
                cleaned_content, upload_request = extract_upload_request(result["content"])
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
                self.send_json({
                    "messages": messages,
                    "auto_profile": auto_profile,
                    "wallet_pending": load_pending(enterprise_id),
                })
                return
            if self.path == "/api/chat/stream":
                self.handle_chat_stream()
                return
            if self.path == "/api/knowledge/reindex":
                self.send_json(KNOWLEDGE.rebuild())
                return
            if self.path == "/api/image-knowledge/reindex":
                _user, enterprise = self.current_context()
                enterprise_id = str(enterprise["id"])
                self.send_json(
                    image_kb_for_enterprise(enterprise_id).rebuild_from_uploads(
                        enterprise_uploads_dir(enterprise_id)
                    )
                )
                return
            if self.path.startswith("/api/wallet/pending/"):
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
                return
            if self.path == "/api/video-call/start":
                user, enterprise = self.current_context()
                enterprise_id = str(enterprise["id"])
                call_id = video_calls.start_call(enterprise_id, str(user.get("id") or ""))
                memory = build_call_memory(enterprise_id, enterprise)
                self.send_json({"ok": True, "call_id": call_id, "memory": memory})
                return
            if self.path == "/api/video-call/knowledge":
                _user, enterprise = self.current_context()
                payload = self.read_json()
                query = str(payload.get("query") or "").strip()
                if not query:
                    self.send_json({"block": "", "count": 0})
                    return
                hits = KNOWLEDGE.search(query, top_k=KNOWLEDGE_TOP_K)
                self.send_json({"block": format_hits_for_prompt(hits) if hits else "", "count": len(hits)})
                return
            if self.path == "/api/video-call/image-check":
                _user, enterprise = self.current_context()
                payload = self.read_json()
                hits = _video_image_history_hits(str(enterprise["id"]), str(payload.get("image") or ""))
                self.send_json({"hits": hits})
                return
            if self.path.startswith("/api/video-call/") and self.path.endswith("/complete"):
                _user, enterprise = self.current_context()
                call_id = self.path[len("/api/video-call/"):-len("/complete")]
                payload = self.read_json()
                observations = _persist_observation_frames(
                    str(enterprise["id"]), call_id, payload.get("observations")
                )
                updated = video_calls.complete_call(
                    call_id,
                    str(enterprise["id"]),
                    transcript=payload.get("transcript"),
                    observations=observations,
                    risk=payload.get("risk"),
                    metadata=payload.get("metadata"),
                )
                if not updated:
                    self.send_json({"error": "通话记录不存在"}, status=404)
                    return
                # 回写来源：视频/语音通话共用此端点，由前端声明来源（默认视频，保持后向兼容）。
                source = str(payload.get("source") or "视频通话").strip() or "视频通话"
                # 把通话中发现的矛盾/疑点回写为跨渠道"待核验点"，让文字与视频/语音各端继续咬住。
                written = add_open_verifications(
                    str(enterprise["id"]),
                    _verifications_from_risk(payload.get("risk"), channel_label=source),
                    source=source,
                )
                self.send_json({"ok": True, "verifications_added": written})
                return
            if self.path == "/api/reset":
                _user, enterprise = self.current_context()
                enterprise_id = str(enterprise["id"])
                clear_messages(enterprise_id)
                gateway_for_enterprise(enterprise_id).reset_session(f"chat:{enterprise_id}")
                self.send_json({"ok": True})
                return
            if self.path == "/api/loan/estimate":
                _user, enterprise = self.current_context()
                estimate = run_loan_estimate(str(enterprise["id"]), enterprise)
                self.send_json({"estimate": estimate})
                return
            if self.path == "/api/profile/refresh":
                _user, enterprise = self.current_context()
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
                return
            self.send_error(404)
        except EnterpriseRequired as exc:
            self.send_json({"error": str(exc), "needs_enterprise": True}, status=403)
        except AuthError as exc:
            self.send_json({"error": str(exc), "authenticated": False}, status=401)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)

    def handle_chat_stream(self) -> None:
        _user, enterprise = self.current_context()
        enterprise_id = str(enterprise["id"])
        user_message, attachments = self.read_chat_submission(enterprise_id)
        if not user_message and not attachments:
            self.send_json({"error": "message 不能为空"}, status=400)
            return

        messages = load_messages(enterprise_id)
        display_message = display_user_message(user_message, attachments)
        image_attachments = [item for item in attachments if item.get("kind") == "image"]
        image_paths = [str(item["path"]) for item in image_attachments]
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

            asr_events = _asr_progress_events(attachments)
            for ev in asr_events:
                emit(ev["type"], {"name": ev.get("name"), "tool_id": ev.get("tool_id"), "preview": ev.get("text")})

            emit("tool.start", {"name": "本地知识库", "tool_id": "local-knowledge"})
            knowledge_started_at = time.monotonic()
            try:
                knowledge_hits = KNOWLEDGE.search(display_message, top_k=KNOWLEDGE_TOP_K)
            except Exception as exc:
                emit("tool.complete", {
                    "name": "本地知识库",
                    "tool_id": "local-knowledge",
                    "duration_s": time.monotonic() - knowledge_started_at,
                    "error": str(exc),
                })
                raise
            knowledge_duration = time.monotonic() - knowledge_started_at
            emit("tool.progress", {"name": "本地知识库", "preview": summarize_knowledge_hits(knowledge_hits)})
            emit("tool.complete", {
                "name": "本地知识库",
                "tool_id": "local-knowledge",
                "duration_s": knowledge_duration,
            })
            local_progress = asr_events + knowledge_progress_events(knowledge_hits, knowledge_duration)

            image_kb = image_kb_for_enterprise(enterprise_id)
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
                image_hits = []
                emit("tool.complete", {
                    "name": "客户历史图档",
                    "tool_id": "image-history",
                    "duration_s": time.monotonic() - image_kb_started_at,
                    "error": str(exc),
                })
            else:
                image_kb_duration = time.monotonic() - image_kb_started_at
                emit("tool.progress", {"name": "客户历史图档", "preview": summarize_image_hits(image_hits)})
                emit("tool.complete", {
                    "name": "客户历史图档",
                    "tool_id": "image-history",
                    "duration_s": image_kb_duration,
                })
                local_progress = local_progress + image_kb_progress_events(image_hits, image_kb_duration)

            gateway_delta_count = 0

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
            if gateway_delta_count == 0 and cleaned_content.strip():
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
            emit("message.complete", {
                "messages": messages,
                "auto_profile": auto_profile,
                "wallet_pending": load_pending(enterprise_id),
            })
        except Exception as exc:
            emit("error", {"error": str(exc)})

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
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
    print(f"Customer manager UI: http://{host}:{port}/chat", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

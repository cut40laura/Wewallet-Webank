from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from config import (
    APP_DATA_DIR,
    GATEWAY_IDLE_TIMEOUT_SECONDS,
    GATEWAY_REQUEST_TIMEOUT,
    GATEWAY_SWEEP_INTERVAL_SECONDS,
    GATEWAY_TURN_TIMEOUT,
    HERMES_AGENT_DIR,
    REASONING_TAGS,
    ROOT,
)
from enterprise import ensure_enterprise_hermes_home
from storage import DATA_LOCK


GATEWAY_LOCK = threading.RLock()
GATEWAYS: dict[str, "HermesTuiGateway"] = {}
PROFILE_UPDATE_LOCKS: dict[str, threading.Lock] = {}


def split_reasoning(text: str) -> tuple[str, str]:
    visible = text or ""
    reasoning: list[str] = []
    for tag in REASONING_TAGS:
        paired = re.compile(rf"<{tag}>([\s\S]*?)</{tag}>\s*", re.IGNORECASE)
        visible = paired.sub(lambda match: _collect_reasoning(match, reasoning), visible)
        unclosed = re.compile(rf"<{tag}>([\s\S]*)$", re.IGNORECASE)
        visible = unclosed.sub(lambda match: _collect_reasoning(match, reasoning), visible)
    return visible.strip(), "\n\n".join(reasoning).strip()


def _collect_reasoning(match: re.Match[str], reasoning: list[str]) -> str:
    inner = match.group(1).strip()
    if inner:
        reasoning.append(inner)
    return ""


def split_reply_and_reasoning_summary(text: str) -> tuple[str, str]:
    markers = (
        "风控分析摘要：",
        "风控分析摘要:",
        "【风控分析摘要】",
        "分析摘要：",
        "分析摘要:",
    )
    for marker in markers:
        if marker in text:
            reply, summary = text.split(marker, 1)
            reply = (
                reply.replace("客户回复：", "")
                .replace("客户回复:", "")
                .replace("【客户回复】", "")
                .strip()
            )
            return reply.strip(), summary.strip()
    return text.strip(), ""


def sanitize_model_output(text: str) -> str:
    """Remove model reasoning traces before content reaches the web UI."""
    cleaned = text.strip()
    while "<think>" in cleaned and "</think>" in cleaned:
        before, rest = cleaned.split("<think>", 1)
        _, after = rest.split("</think>", 1)
        cleaned = (before + after).strip()

    banned_prefixes = ("<analysis>", "</analysis>", "Chain of thought", "Thought process")
    lines = cleaned.splitlines()
    filtered: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if any(stripped.startswith(prefix) for prefix in banned_prefixes):
            skipping = True
            continue
        if skipping and (not stripped or stripped.startswith(("最终", "回复", "答案", "客户经理", "小微"))):
            skipping = False
            stripped = stripped.removeprefix("最终回复：").removeprefix("回复：").removeprefix("答案：").strip()
            if stripped:
                filtered.append(stripped)
            continue
        if not skipping:
            filtered.append(line)
    return "\n".join(filtered).strip()


def is_thinking_status(text: str) -> bool:
    value = str(text or "").strip()
    return bool(value) and len(value) <= 80 and "\n" not in value


class HermesTuiGateway:
    def __init__(self, hermes_home: Path, enterprise_id: str = "") -> None:
        self.hermes_home = hermes_home
        self.enterprise_id = enterprise_id
        self._proc: subprocess.Popen[str] | None = None
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self._lock = threading.RLock()
        self._request_id = 0
        self._pending: dict[str, queue.Queue[dict[str, Any]]] = {}
        self._events: dict[str, queue.Queue[dict[str, Any]]] = {}
        self._sessions: dict[str, str] = {}
        self._stderr_tail: list[str] = []
        self._last_used_at = time.monotonic()

    def submit(
        self,
        session_name: str,
        prompt: str,
        *,
        image_paths: list[str] | None = None,
        event_callback: Any = None,
        timeout: float = GATEWAY_TURN_TIMEOUT,
    ) -> dict[str, Any]:
        self._last_used_at = time.monotonic()
        sid = self._ensure_session(session_name)
        self._drain_events(sid)
        for image_path in image_paths or []:
            try:
                self._request("image.attach", {"session_id": sid, "path": image_path}, timeout=10.0)
            except Exception:
                # Keep the chat turn usable even if this gateway build rejects
                # native image attachment for a saved upload.
                pass
        self._request("prompt.submit", {"session_id": sid, "text": prompt})
        return self._collect_turn(sid, event_callback=event_callback, timeout=timeout)

    def reset_session(self, session_name: str) -> None:
        with self._lock:
            sid = self._sessions.pop(session_name, None)
        if sid:
            try:
                self._request("session.close", {"session_id": sid}, timeout=5.0)
            except Exception:
                pass

    def _ensure_session(self, session_name: str) -> str:
        with self._lock:
            sid = self._sessions.get(session_name)
            if sid:
                return sid
            self._ensure_process()
        result = self._request("session.create", {"cols": 96})
        sid = str(result.get("session_id") or "").strip()
        if not sid:
            raise RuntimeError("智能体网关未返回会话 ID")
        with self._lock:
            self._sessions[session_name] = sid
            self._events.setdefault(sid, queue.Queue())
        return sid

    def _ensure_process(self) -> None:
        if self._proc and self._proc.poll() is None:
            return

        env = os.environ.copy()
        env["HERMES_HOME"] = str(self.hermes_home)
        env["TERMINAL_CWD"] = str(ROOT)
        env["HERMES_CWD"] = str(ROOT)
        if self.enterprise_id:
            env["WEWALLET_ENTERPRISE_ID"] = self.enterprise_id
        env["WEWALLET_APP_DATA_DIR"] = str(APP_DATA_DIR)
        pythonpath = env.get("PYTHONPATH", "")
        hermes_path = str(HERMES_AGENT_DIR)
        env["PYTHONPATH"] = hermes_path if not pythonpath else f"{hermes_path}{os.pathsep}{pythonpath}"
        python = env.get("HERMES_PYTHON") or sys.executable or "python3"

        self._proc = subprocess.Popen(
            [python, "-m", "tui_gateway.entry"],
            cwd=str(ROOT),
            env=env,
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
        )
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._stderr_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self._reader.start()
        self._stderr_reader.start()

    def _read_stdout(self) -> None:
        proc = self._proc
        if not proc or not proc.stdout:
            return
        for line in proc.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            request_id = str(message.get("id") or "")
            if request_id:
                q = self._pending.get(request_id)
                if q:
                    q.put(message)
                continue
            if message.get("method") == "event":
                event = message.get("params")
                if not isinstance(event, dict):
                    continue
                sid = str(event.get("session_id") or "")
                if sid:
                    self._events.setdefault(sid, queue.Queue()).put(event)

    def _read_stderr(self) -> None:
        proc = self._proc
        if not proc or not proc.stderr:
            return
        for raw in proc.stderr:
            line = raw.strip()
            if line:
                self._stderr_tail = (self._stderr_tail + [line])[-40:]

    def _request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = GATEWAY_REQUEST_TIMEOUT,
    ) -> dict[str, Any]:
        with self._lock:
            self._ensure_process()
            proc = self._proc
            if not proc or not proc.stdin or proc.poll() is not None:
                raise RuntimeError(self._gateway_error("智能体网关未运行"))
            self._request_id += 1
            request_id = f"web-{self._request_id}"
            q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            self._pending[request_id] = q
            request = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params or {},
            }
            proc.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            proc.stdin.flush()

        try:
            response = q.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(self._gateway_error(f"智能体网关请求超时：{method}"))
        finally:
            self._pending.pop(request_id, None)

        if response.get("error"):
            error = response["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise RuntimeError(self._gateway_error(str(message or "智能体网关请求失败")))
        result = response.get("result")
        return result if isinstance(result, dict) else {}

    def _collect_turn(self, sid: str, *, event_callback: Any, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        content_parts: list[str] = []
        thinking_parts: list[str] = []
        progress: list[dict[str, Any] | str] = []
        inline_diffs: list[str] = []
        final_text = ""
        final_reasoning = ""
        events = self._events.setdefault(sid, queue.Queue())

        while time.monotonic() < deadline:
            try:
                event = events.get(timeout=0.2)
            except queue.Empty:
                proc = self._proc
                if proc and proc.poll() is not None:
                    raise RuntimeError(self._gateway_error(f"智能体网关已退出，状态码 {proc.returncode}"))
                continue

            event_type = str(event.get("type") or "")
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            if event_callback:
                event_callback(event_type, payload)

            if event_type in {"thinking.delta", "reasoning.delta"}:
                text = str(payload.get("text") or "")
                if text:
                    thinking_parts.append(text)
                    if is_thinking_status(text):
                        progress.append({"type": event_type, "text": text, "name": "Hermes"})
            elif event_type == "message.delta":
                text = str(payload.get("text") or "")
                if text:
                    content_parts.append(text)
            elif event_type in {
                "tool.generating",
                "tool.progress",
                "tool.start",
                "tool.complete",
                "status.update",
                "reasoning.available",
            }:
                normalized = self._progress_payload(event_type, payload)
                if normalized:
                    progress.append(normalized)
                inline_diff = str(payload.get("inline_diff") or "")
                if inline_diff:
                    inline_diffs.append(inline_diff)
            elif event_type == "message.complete":
                final_text = str(payload.get("text") or "")
                final_reasoning = str(payload.get("reasoning") or "")
                break
            elif event_type == "error":
                raise RuntimeError(str(payload.get("message") or "智能体网关错误"))

        else:
            raise TimeoutError(self._gateway_error("智能体回复超时"))

        visible = final_text or "".join(content_parts)
        visible, inline_thinking = split_reasoning(visible)
        if inline_thinking:
            thinking_parts.append(inline_thinking)
        if final_reasoning:
            thinking_parts.append(final_reasoning)
        return {
            "content": sanitize_model_output(visible),
            "thinking": "\n\n".join(part.strip() for part in thinking_parts if part and part.strip()).strip(),
            "progress": progress[-120:],
            "inline_diffs": inline_diffs[-20:],
            "raw": {"session_id": sid},
        }

    def _progress_payload(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any] | str:
        name = str(payload.get("name") or "").strip()
        preview = str(payload.get("preview") or payload.get("summary") or payload.get("text") or "").strip()
        if event_type == "tool.generating":
            return {"type": event_type, "text": f"preparing {name or 'tool'}...", "name": name}
        if event_type == "tool.start":
            return {"type": event_type, "text": f"started {name or 'tool'}", "name": name, "tool_id": payload.get("tool_id")}
        if event_type == "tool.complete":
            duration = payload.get("duration_s")
            suffix = f" {float(duration):.1f}s" if isinstance(duration, (int, float)) else ""
            error = str(payload.get("error") or "").strip()
            status = "error" if error else "complete"
            text = f"{status} {name or 'tool'}{suffix}"
            if error:
                text = f"{text}: {error[:180]}"
            return {
                "type": event_type,
                "text": text,
                "name": name,
                "status": status,
                "tool_id": payload.get("tool_id"),
                "inline_diff": payload.get("inline_diff"),
            }
        if event_type == "tool.progress":
            return {"type": event_type, "text": preview or name, "name": name}
        if event_type == "reasoning.available":
            return ""
        if event_type == "status.update":
            return {"type": event_type, "text": preview, "status": payload.get("kind")}
        return preview

    def _drain_events(self, sid: str) -> None:
        events = self._events.setdefault(sid, queue.Queue())
        while True:
            try:
                events.get_nowait()
            except queue.Empty:
                return

    def _gateway_error(self, message: str) -> str:
        tail = "\n".join(self._stderr_tail[-8:])
        return f"{message}\n{tail}" if tail else message

    def is_idle(self, threshold_seconds: float) -> bool:
        if self._pending:
            return False
        return (time.monotonic() - self._last_used_at) > threshold_seconds

    def shutdown(self) -> None:
        with self._lock:
            proc = self._proc
            self._proc = None
            self._sessions.clear()
            self._events.clear()
            self._pending.clear()
        if not proc:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            try:
                proc.kill()
            except OSError:
                pass


def gateway_for_enterprise(enterprise_id: str) -> HermesTuiGateway:
    home = ensure_enterprise_hermes_home(enterprise_id)
    with GATEWAY_LOCK:
        gateway = GATEWAYS.get(enterprise_id)
        if gateway is None:
            gateway = HermesTuiGateway(home, enterprise_id=enterprise_id)
            GATEWAYS[enterprise_id] = gateway
        return gateway


def profile_update_lock(enterprise_id: str) -> threading.Lock:
    with DATA_LOCK:
        lock = PROFILE_UPDATE_LOCKS.get(enterprise_id)
        if lock is None:
            lock = threading.Lock()
            PROFILE_UPDATE_LOCKS[enterprise_id] = lock
        return lock


def sweep_idle_gateways(idle_seconds: float = GATEWAY_IDLE_TIMEOUT_SECONDS) -> list[str]:
    closed: list[str] = []
    with GATEWAY_LOCK:
        idle_ids = [
            enterprise_id for enterprise_id, gateway in GATEWAYS.items()
            if gateway.is_idle(idle_seconds)
        ]
        for enterprise_id in idle_ids:
            gateway = GATEWAYS.pop(enterprise_id, None)
            if gateway is None:
                continue
            try:
                gateway.shutdown()
            except Exception as exc:
                print(f"[wewallet] gateway shutdown failed for {enterprise_id}: {exc}", file=sys.stderr)
            closed.append(enterprise_id)
    if closed:
        with DATA_LOCK:
            for enterprise_id in closed:
                lock = PROFILE_UPDATE_LOCKS.get(enterprise_id)
                if lock is not None and lock.acquire(blocking=False):
                    try:
                        PROFILE_UPDATE_LOCKS.pop(enterprise_id, None)
                    finally:
                        lock.release()
    return closed


def start_gateway_sweeper() -> threading.Thread:
    def sweeper() -> None:
        while True:
            time.sleep(GATEWAY_SWEEP_INTERVAL_SECONDS)
            try:
                sweep_idle_gateways()
            except Exception as exc:
                print(f"[wewallet] gateway sweeper error: {exc}", file=sys.stderr)

    thread = threading.Thread(target=sweeper, name="gateway-sweeper", daemon=True)
    thread.start()
    return thread

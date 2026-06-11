"""视频通话尽调留痕：挂断落库 + 画面观察登记簿 + 后台风控总结。

此前通话内容、画面观察、反欺诈判断**全程零持久化**，挂断即丢、无尽调留痕。
本模块补上这一层，但刻意贴着本项目的现有形态来做（与姊妹仓的三端点两步提交
方案不同）：

- **单次提交**：挂断时前端本来就 keepalive POST /api/voicecall/end 回流转写，
  落库直接搭这趟车（一条 INSERT），不新增任何客户端往返。
- **观察登记簿**：实时画面观察产生在 relay（与 server 同进程的线程），浏览器
  从头到尾见不到结构化观察。所以观察在进程内按企业累积（note_observation，
  纯内存 append、不碰通话热路径），挂断时 drain 随转写一起落库。
- **风控总结后台跑**：规则聚合 + LLM 总结（best-effort）放守护线程，挂断
  响应不等它；算完 UPDATE 补写 risk 列，并把疑点回写客户档案的待核实项
  （profile_service.add_open_verifications），主聊天小微据此跨渠道跟进。

按 enterprise_id 隔离：跨企业读不到、写不动（与 messages 表一致）。
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any

import requests

import db
from config import iso_now

# ── 画面观察登记簿（进程内，relay 线程写、server 线程读）────────────────────
# 容量与时效都设上限：防长通话/忘挂断把内存吃穿，也防上一通的陈旧观察串到下一通。
_OBS_LOCK = threading.Lock()
_OBS_BUFFER: dict[str, list[dict[str, Any]]] = {}
_OBS_MAX_PER_ENTERPRISE = 240
_OBS_TTL_S = 2 * 3600


def note_observation(enterprise_id: str, observation: dict[str, Any] | None) -> None:
    """relay 每解析出一帧结构化观察就登记一条。绝不抛错（通话热路径旁路）。"""
    if not enterprise_id or not isinstance(observation, dict):
        return
    try:
        entry = dict(observation)
        entry["ts"] = iso_now()
        entry["_mono"] = time.monotonic()
        with _OBS_LOCK:
            bucket = _OBS_BUFFER.setdefault(enterprise_id, [])
            bucket.append(entry)
            if len(bucket) > _OBS_MAX_PER_ENTERPRISE:
                del bucket[: len(bucket) - _OBS_MAX_PER_ENTERPRISE]
    except Exception:
        pass


def drain_observations(enterprise_id: str) -> list[dict[str, Any]]:
    """取走并清空该企业累积的观察（挂断时调用）；过期条目直接丢弃。"""
    return _drain(_OBS_BUFFER, enterprise_id)


def _drain(buffer: dict[str, list[dict[str, Any]]], enterprise_id: str) -> list[dict[str, Any]]:
    if not enterprise_id:
        return []
    with _OBS_LOCK:
        bucket = buffer.pop(enterprise_id, [])
    cutoff = time.monotonic() - _OBS_TTL_S
    drained = []
    for entry in bucket:
        if entry.get("_mono", 0.0) >= cutoff:
            entry = dict(entry)
            entry.pop("_mono", None)
            drained.append(entry)
    return drained


# ── 口述矛盾登记簿（与观察同一套机制）────────────────────────────────────────
# relay 的实时矛盾检测（口述 vs 档案）命中一条登记一条；挂断时 drain，合入风控
# 判级（强信号）并直接回写为跨渠道待核实项。
_CONTRA_BUFFER: dict[str, list[dict[str, Any]]] = {}


def note_contradiction(enterprise_id: str, item: dict[str, Any] | None) -> None:
    """relay 命中一处"口述与档案不符"就登记一条。绝不抛错（通话旁路）。"""
    if not enterprise_id or not isinstance(item, dict):
        return
    try:
        entry = dict(item)
        entry["ts"] = iso_now()
        entry["_mono"] = time.monotonic()
        with _OBS_LOCK:
            bucket = _CONTRA_BUFFER.setdefault(enterprise_id, [])
            bucket.append(entry)
            if len(bucket) > _OBS_MAX_PER_ENTERPRISE:
                del bucket[: len(bucket) - _OBS_MAX_PER_ENTERPRISE]
    except Exception:
        pass


def drain_contradictions(enterprise_id: str) -> list[dict[str, Any]]:
    """取走并清空该企业累积的矛盾（挂断时调用）。"""
    return _drain(_CONTRA_BUFFER, enterprise_id)


# ── 落库 ─────────────────────────────────────────────────────────────────────
def _loads(value: Any) -> Any:
    if value is None or value == "":
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "enterprise_id": row["enterprise_id"],
        "user_id": row["user_id"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "transcript": _loads(row["transcript"]),
        "observations": _loads(row["observations"]),
        "risk": _loads(row["risk"]),
        "metadata": _loads(row["metadata"]),
        "created_ts": row["created_ts"],
    }


def record_call(
    enterprise_id: str,
    user_id: str | None,
    *,
    transcript: list[dict[str, Any]] | None,
    observations: list[dict[str, Any]] | None,
    metadata: dict[str, Any] | None,
) -> str:
    """挂断时一次性写入整通记录，返回 call_id。risk 留空，由后台线程补写。"""
    call_id = uuid.uuid4().hex
    started_at = str((metadata or {}).get("started_at") or "")
    with db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO video_calls
                (id, enterprise_id, user_id, started_at, ended_at,
                 transcript, observations, risk, metadata, created_ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (
                call_id,
                enterprise_id,
                user_id,
                started_at or None,
                iso_now(),
                json.dumps(transcript, ensure_ascii=False) if transcript else None,
                json.dumps(observations, ensure_ascii=False) if observations else None,
                json.dumps(metadata, ensure_ascii=False) if metadata else None,
                time.time(),
            ),
        )
    return call_id


def set_call_risk(call_id: str, enterprise_id: str, risk: dict[str, Any]) -> bool:
    """后台风控总结算完后补写。按企业隔离；幂等覆盖。返回是否真的更新了行。"""
    with db.transaction() as conn:
        cur = conn.execute(
            "UPDATE video_calls SET risk = ? WHERE id = ? AND enterprise_id = ?",
            (json.dumps(risk, ensure_ascii=False), call_id, enterprise_id),
        )
        return cur.rowcount > 0


def load_call(call_id: str, enterprise_id: str) -> dict[str, Any] | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM video_calls WHERE id = ? AND enterprise_id = ?",
            (call_id, enterprise_id),
        ).fetchone()
    return _row_to_dict(row) if row else None


def list_calls(enterprise_id: str, limit: int = 50) -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM video_calls WHERE enterprise_id = ? "
            "ORDER BY created_ts DESC LIMIT ?",
            (enterprise_id, limit),
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


# ── 风控总结（规则聚合 + LLM，best-effort）──────────────────────────────────
RISK_SUMMARY_PROMPT = (
    "你是微众银行小微信贷的风控审核助手。下面给你一段 AI 客户经理与用户的视频尽调"
    "通话：包含逐句对话转写，以及系统逐帧的客观画面观察。\n"
    "请基于这些材料，判断本次通话是否存在欺诈、冒用或经营造假的风险迹象，给出克制、"
    "就事论事的结论。只依据材料，绝不臆测材料里没有的内容。\n"
    '严格输出 JSON：{"level":"low|medium|high","reasons":["简短中文要点，最多5条，'
    '没有就空数组"]}。\n'
    "判级参考：前后说法矛盾、有人提词念稿、本人对自己店名/证件不熟、画面与口述对不上、"
    "回避正脸或证件等，属于升级信号；材料正常则 low。"
)


def aggregate_risk_signals(observations: list[dict[str, Any]] | None) -> dict[str, Any]:
    """从逐帧观察聚合硬信号（纯规则，零成本）。字段名沿用 describe_frame 的观察结构。"""
    items = observations if isinstance(observations, list) else []
    anomaly_count = 0
    off_screen_count = 0
    person_absent_count = 0
    documents: list[str] = []
    for obs in items:
        if not isinstance(obs, dict):
            continue
        anomalies = obs.get("anomalies")
        if isinstance(anomalies, list):
            anomaly_count += sum(1 for a in anomalies if a)
        if obs.get("looking_off_screen") is True:
            off_screen_count += 1
        if obs.get("person_present") is False:
            person_absent_count += 1
        docs = obs.get("visible_documents")
        if isinstance(docs, list):
            for doc in docs:
                if doc and str(doc) not in documents:
                    documents.append(str(doc))
    return {
        "frame_count": len(items),
        "anomaly_count": anomaly_count,
        "off_screen_count": off_screen_count,
        "person_absent_count": person_absent_count,
        "documents_seen": documents,
    }


def rule_level(signals: dict[str, Any]) -> str:
    """仅凭硬信号给保守初始等级；LLM 总结可在其上调整。"""
    if signals.get("anomaly_count", 0) > 0:
        return "medium"
    frames = signals.get("frame_count", 0)
    if frames > 0 and signals.get("off_screen_count", 0) > frames / 2:
        return "medium"
    return "low"


def _transcript_to_text(transcript: list[dict[str, Any]] | None) -> str:
    if not isinstance(transcript, list):
        return ""
    lines = []
    for turn in transcript:
        if not isinstance(turn, dict):
            continue
        text = str(turn.get("text") or turn.get("content") or "").strip()
        if not text:
            continue
        role = "客户经理" if turn.get("role") in ("ai", "assistant") else "用户"
        lines.append(f"{role}：{text}")
    return "\n".join(lines)[:8000]


def _observations_to_text(observations: list[dict[str, Any]] | None) -> str:
    if not isinstance(observations, list):
        return ""
    captions = [str(o.get("caption") or "") for o in observations if isinstance(o, dict)]
    return "\n".join(c for c in captions if c)[:4000]


def _llm_risk_review(
    transcript_text: str, observations_text: str, contradiction_text: str = "",
) -> dict[str, Any] | None:
    """跑一次 LLM 风控总结。任何失败（缺凭证/网络/解析）都返回 None，绝不抛错。"""
    try:
        # 延迟导入：voicecall 顶层有较重的提示词常量，且 _resolve_provider 缺凭证会抛。
        from voicecall import _extract_json, _resolve_provider

        _label, api_key, base_url, model, extra = _resolve_provider()
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": RISK_SUMMARY_PROMPT},
                {"role": "user", "content": (
                    f"对话转写：\n{transcript_text}\n\n画面观察：\n{observations_text or '（无）'}"
                    + (f"\n\n通话中已实时检测到的与历史档案不符之处：\n{contradiction_text}"
                       if contradiction_text else "")
                )},
            ],
            "temperature": 0.2,
            **extra,
        }
        if _label == "Ark":
            payload["thinking"] = {"type": "disabled"}  # 离线总结要的是 JSON，不要思考流
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        raw = str(resp.json()["choices"][0]["message"]["content"] or "")
        parsed = json.loads(_extract_json(raw) or "{}")
        if not isinstance(parsed, dict):
            return None
        result: dict[str, Any] = {}
        if parsed.get("level") in ("low", "medium", "high"):
            result["level"] = parsed["level"]
        reasons = parsed.get("reasons")
        if isinstance(reasons, list):
            result["reasons"] = [str(r) for r in reasons if r and isinstance(r, str)][:5]
        return result or None
    except Exception:
        return None


def _contradictions_to_text(contradictions: list[dict[str, Any]] | None) -> str:
    if not isinstance(contradictions, list):
        return ""
    lines = []
    for c in contradictions:
        if isinstance(c, dict) and (c.get("stated") or c.get("known")):
            lines.append(f"- {c.get('field') or '某项信息'}：用户说\"{c.get('stated', '')}\"，档案为\"{c.get('known', '')}\"")
    return "\n".join(lines)[:2000]


def build_risk_summary(
    transcript: list[dict[str, Any]] | None,
    observations: list[dict[str, Any]] | None,
    contradictions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """规则聚合永远有结果；LLM 总结 best-effort，失败就退回纯规则结论。

    通话中实时检测到的"与档案不符"明细是强信号：计入 signals 并至少抬到 medium，
    无论 LLM 是否可用。
    """
    signals = aggregate_risk_signals(observations)
    result: dict[str, Any] = {"level": rule_level(signals), "reasons": [], "signals": signals}
    contradiction_text = _contradictions_to_text(contradictions)
    if contradiction_text:
        signals["contradiction_count"] = len(contradictions or [])
        if result["level"] == "low":
            result["level"] = "medium"
    transcript_text = _transcript_to_text(transcript)
    if transcript_text:
        reviewed = _llm_risk_review(
            transcript_text, _observations_to_text(observations), contradiction_text)
        if reviewed:
            result.update(reviewed)
            result.setdefault("reasons", [])
            if contradiction_text and result["level"] == "low":
                result["level"] = "medium"  # 实时矛盾是硬证据，LLM 不能往下豁免
    return result


def schedule_risk_review(
    call_id: str,
    enterprise_id: str,
    transcript: list[dict[str, Any]] | None,
    observations: list[dict[str, Any]] | None,
    contradictions: list[dict[str, Any]] | None = None,
) -> None:
    """挂断响应返回后，守护线程里跑风控总结：补写 risk 列 + 疑点回写待核实项。"""

    def worker() -> None:
        try:
            risk = build_risk_summary(transcript, observations, contradictions)
            set_call_risk(call_id, enterprise_id, risk)
            # 延迟导入避免环（profile_service 不依赖本模块，但启动开销大）。
            from profile_service import add_open_verifications

            items = []
            # 实时检测到的矛盾是硬证据，无论判级一律回写待核实。
            for c in contradictions or []:
                if isinstance(c, dict) and (c.get("stated") or c.get("known")):
                    items.append({
                        "text": f"{c.get('field') or '某项信息'}：通话中说\"{c.get('stated', '')}\"，档案为\"{c.get('known', '')}\"",
                        "source": f"视频通话 {call_id[:8]}",
                        "level": risk.get("level", ""),
                    })
            if risk.get("level") in ("medium", "high"):
                items.extend(
                    {"text": reason, "source": f"视频通话 {call_id[:8]}", "level": risk["level"]}
                    for reason in risk.get("reasons") or []
                )
            if items:
                add_open_verifications(enterprise_id, items)
        except Exception as exc:
            print(f"[video_calls] risk review failed for {call_id}: {exc}")

    threading.Thread(target=worker, name=f"risk-review-{call_id[:8]}", daemon=True).start()

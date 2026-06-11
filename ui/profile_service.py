from __future__ import annotations

import difflib
import json
import re
import threading
import time
from pathlib import Path
from typing import Any

from knowledge import KnowledgeBase, KnowledgeHit, format_hits_for_prompt
from image_knowledge import ImageKnowledgeHit, format_image_hits_for_prompt

from config import (
    AUTO_PROFILE_INTERVAL,
    CASE_FILE,
    KNOWLEDGE_DB_FILE,
    KNOWLEDGE_RAW_DIR,
    KNOWLEDGE_TOP_K,
    OFFTOPIC_STEER_TURNS,
    PROFILE_DIGEST_MAX_CHARS,
    ROOT,
    TEMPLATE_FILE,
    enterprise_hermes_template_file,
    enterprise_loan_estimate_file,
    enterprise_profile_file,
    enterprise_profile_state_file,
    enterprise_versions_dir,
    iso_now,
)
from gateway import gateway_for_enterprise, profile_update_lock
from storage import DATA_LOCK, atomic_write_text, load_json_file, save_json_file
from wallet import load_pending, load_wallet_transactions, wallet_summary


KNOWLEDGE = KnowledgeBase(ROOT, KNOWLEDGE_RAW_DIR, KNOWLEDGE_DB_FILE)


def load_profile_markdown(enterprise_id: str) -> tuple[Path, str]:
    path = enterprise_profile_file(enterprise_id)
    if not path.exists():
        template = TEMPLATE_FILE.read_text(encoding="utf-8") if TEMPLATE_FILE.exists() else "# 企业风控画像\n"
        atomic_write_text(path, template.rstrip() + "\n")
    return path, path.read_text(encoding="utf-8")


def is_profile_document(markdown: str) -> bool:
    text = markdown.strip()
    if not text.startswith("#"):
        return False
    markers = (
        "当前风险",
        "风险信号",
        "字段变更审计",
        "客户与企业画像",
        "个人信息",
        "融资",
        "核验",
    )
    return sum(1 for marker in markers if marker in text) >= 2


def profile_diff(old_markdown: str, new_markdown: str, path: Path | None = None) -> str:
    old_lines = old_markdown.rstrip().splitlines()
    new_lines = new_markdown.rstrip().splitlines()
    label = str(path or CASE_FILE)
    return "\n".join(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=label,
            tofile=label,
            lineterm="",
        )
    )


def user_turn_count(messages: list[dict[str, Any]]) -> int:
    return sum(1 for message in messages if message.get("role") == "user")


def load_profile_state(enterprise_id: str) -> dict[str, Any]:
    state = load_json_file(enterprise_profile_state_file(enterprise_id), {})
    return state if isinstance(state, dict) else {}


def save_profile_state(enterprise_id: str, state: dict[str, Any]) -> None:
    save_json_file(enterprise_profile_state_file(enterprise_id), state)


# ── 跨渠道待核实项（open verifications）────────────────────────────────────
# 视频通话挂断后的风控总结（video_calls.schedule_risk_review）把疑点回写到这里，
# 主聊天和下一通电话的小微都会在 prompt 里看到，跨渠道咬住、不让疑点不了了之。
# 存在 profile_state.json 里（轻量 JSON，画像更新流程已在读写同一文件）。
OPEN_VERIFICATIONS_MAX = 12


def add_open_verifications(enterprise_id: str, items: list[dict[str, Any]]) -> int:
    """追加待核实项（按文本去重、上限截断），返回实际新增条数。"""
    if not enterprise_id or not items:
        return 0
    state = load_profile_state(enterprise_id)
    existing = state.get("open_verifications")
    if not isinstance(existing, list):
        existing = []
    known_texts = {str(item.get("text") or "") for item in existing if isinstance(item, dict)}
    added = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text or text in known_texts:
            continue
        known_texts.add(text)
        existing.append({
            "text": text,
            "source": str(item.get("source") or ""),
            "level": str(item.get("level") or ""),
            "created_at": iso_now(),
        })
        added += 1
    if added:
        state["open_verifications"] = existing[-OPEN_VERIFICATIONS_MAX:]
        save_profile_state(enterprise_id, state)
    return added


def list_open_verifications(enterprise_id: str) -> list[dict[str, Any]]:
    items = load_profile_state(enterprise_id).get("open_verifications")
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def open_verifications_block(enterprise_id: str) -> str:
    """拼成可注入 prompt 的待核实清单；为空返回空串（调用方据此决定是否注入）。"""
    items = list_open_verifications(enterprise_id)
    if not items:
        return ""
    lines = []
    for item in items:
        source = f"（{item['source']}）" if item.get("source") else ""
        lines.append(f"- {item.get('text', '')}{source}")
    return "\n".join(lines)


def transcript_for_prompt(messages: list[dict[str, str]]) -> str:
    lines = []
    for message in messages[-24:]:
        role = "客户" if message.get("role") == "user" else "小微"
        lines.append(f"{role}: {message.get('content', '')}")
    return "\n".join(lines)


def history_for_agent(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    for message in messages[-24:]:
        role = message.get("role")
        content = str(message.get("content", "")).strip()
        if role in {"user", "assistant"} and content:
            history.append({"role": role, "content": content})
    return history


def summarize_knowledge_hits(hits: list[KnowledgeHit]) -> str:
    if not hits:
        return "未命中相关知识库片段"
    return "命中知识库"


def knowledge_progress_events(hits: list[KnowledgeHit], duration_s: float) -> list[dict[str, Any]]:
    return [
        {"type": "tool.start", "text": "started 本地知识库", "name": "本地知识库", "tool_id": "local-knowledge"},
        {"type": "tool.progress", "text": summarize_knowledge_hits(hits), "name": "本地知识库"},
        {
            "type": "tool.complete",
            "text": f"complete 本地知识库 {duration_s:.1f}s",
            "name": "本地知识库",
            "status": "complete",
            "tool_id": "local-knowledge",
        },
    ]


UPLOAD_REQUEST_FENCE = re.compile(
    r"```upload_request\s*\n(?P<body>.*?)\n```\s*",
    re.DOTALL,
)


def extract_upload_request(content: str) -> tuple[str, dict[str, Any] | None]:
    """Strip the ```upload_request fenced JSON block from assistant content.

    Returns (cleaned_content, parsed_request_or_None). The fenced block is
    emitted by 小微 when she needs supporting documents from the customer.
    """
    if not content:
        return content, None
    match = UPLOAD_REQUEST_FENCE.search(content)
    if not match:
        return content, None
    try:
        payload = json.loads(match.group("body"))
    except (ValueError, TypeError):
        return content, None
    if not isinstance(payload, dict):
        return content, None
    raw_items = payload.get("items")
    items: list[dict[str, str]] = []
    if isinstance(raw_items, list):
        for entry in raw_items[:4]:
            if isinstance(entry, dict):
                name = str(entry.get("name") or "").strip()[:40]
                hint = str(entry.get("hint") or "").strip()[:120]
            else:
                name = str(entry or "").strip()[:40]
                hint = ""
            if name:
                items.append({"name": name, "hint": hint})
    if not items:
        return content, None
    cleaned = (content[: match.start()] + content[match.end():]).rstrip()
    request = {
        "reason": str(payload.get("reason") or "").strip()[:200],
        "items": items,
    }
    return cleaned, request


def transcript_tail_for_prompt(messages: list[dict[str, Any]], *, limit: int = 8) -> str:
    tail = messages[-limit:]
    lines: list[str] = []
    for message in tail:
        role = "客户" if message.get("role") == "user" else "小微"
        content = str(message.get("content") or "").strip()
        if content:
            lines.append(f"{role}：{content}")
    return "\n".join(lines) or "（暂无历史对话）"


def build_suggestions_prompt(
    messages: list[dict[str, Any]],
    user_message: str,
    assistant_content: str,
    enterprise: dict[str, Any] | None = None,
) -> str:
    enterprise_name = str((enterprise or {}).get("name") or "当前企业")
    transcript = transcript_tail_for_prompt(messages)
    return f"""你是小微企业融资服务里的"快捷追问"生成器。

请根据最近对话和小微刚刚回复的内容，为客户生成 3 个最自然、最有帮助的下一步问题或回复。

要求：
1. 每条 8 到 18 个汉字，口语化，像客户会点的快捷回复。
2. 必须贴合上下文，不要泛泛而谈。
3. 优先覆盖：额度、材料、还款、经营流水、下一步办理中最相关的方向。
4. 不要重复小微已经问过的同一句话。
5. 不要出现"知识库/风控/模型/智能体/系统"等内部词。
6. 只输出 JSON，不要输出解释、Markdown 或代码块。

JSON 格式：
{{"suggestions":["问题1","问题2","问题3"]}}

当前企业：
{enterprise_name}

最近对话：
{transcript}

客户最新输入：
{user_message}

小微刚刚回复：
{assistant_content}
"""


def parse_suggestions(content: str, *, limit: int = 3) -> list[str]:
    raw = str(content or "").strip()
    if not raw:
        return []
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        raw = match.group(0)
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return []
    suggestions = payload.get("suggestions") if isinstance(payload, dict) else None
    if not isinstance(suggestions, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in suggestions:
        text = re.sub(r"\s+", " ", str(item or "")).strip()
        text = text.strip(" -•，。")
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text[:32])
        if len(cleaned) >= limit:
            break
    return cleaned


# 规则化快捷追问语料：(触发关键词, 候选追问)。命中小微上一条回复或客户消息里的
# 关键词就推对应的追问气泡，纯本地匹配、零模型调用——取代原来每轮再跑一次大模型。
_SUGGESTION_RULES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("额度", "能批", "批多少", "授信", "上限"), ("大概能批多少额度？", "额度是怎么算的？", "怎么才能多批点？")),
    (("利率", "利息", "年化", "费率", "多少个点"), ("利息具体怎么算？", "有没有更低的利率？", "利息还能优惠吗？")),
    (("还款", "月供", "分期", "期限", "还多久", "按月", "提前还"), ("每个月还多少？", "最长能借多久？", "能提前还款吗？")),
    (("流水", "对公", "入账", "银行卡", "账户"), ("流水不够怎么办？", "流水怎么发给你？", "要几个月的流水？")),
    (("材料", "资料", "证件", "执照", "合同", "报价", "凭证", "上传", "补充", "清单"), ("需要准备哪些材料？", "材料怎么交给你？", "材料齐了多久能批？")),
    (("纳税", "完税", "开票", "社保", "工资"), ("没怎么纳税有影响吗？", "完税证明在哪开？")),
    (("用途", "周转", "进货", "采购", "装修", "设备", "扩建"), ("贷款用途有限制吗？", "钱能用来周转吗？")),
    (("申请", "办理", "流程", "怎么弄", "怎么办", "下一步", "接下来"), ("接下来我要做什么？", "现在就能申请吗？", "多久能放款？")),
    (("放款", "到账", "多久能下来", "几天"), ("批下来多久到账？", "放款快不快？")),
    (("抵押", "担保", "征信", "负债", "欠款", "借过"), ("没有抵押能贷吗？", "征信有点问题行吗？")),
)

_SUGGESTION_FALLBACK = (
    "大概能批多少额度？", "利息怎么算？", "需要准备哪些材料？", "接下来我要做什么？", "最长能借多久？",
)


def rule_based_suggestions(
    messages: list[dict[str, Any]] | None,
    user_message: str,
    assistant_content: str,
    enterprise: dict[str, Any] | None = None,
    *,
    limit: int = 3,
) -> list[str]:
    """本地规则生成快捷追问气泡，零模型调用。

    匹配小微刚回复 + 客户最新输入里的关键词，推相关追问；去掉客户最近几轮已经
    问过的，凑不满再用兜底池补齐。
    """
    haystack = f"{assistant_content}\n{user_message}"
    recent = " ".join(str(m.get("content") or "") for m in (messages or [])[-6:])
    picks: list[str] = []
    seen: set[str] = set()

    def add(chip: str) -> None:
        text = chip.strip()
        if text and text not in seen and text[:6] not in recent:
            seen.add(text)
            picks.append(text)

    for keywords, chips in _SUGGESTION_RULES:
        if any(k in haystack for k in keywords):
            for chip in chips:
                add(chip)
                if len(picks) >= limit:
                    return picks[:limit]
    for chip in _SUGGESTION_FALLBACK:
        add(chip)
        if len(picks) >= limit:
            break
    return picks[:limit]


_EMOTION_GUIDANCE = {
    "neutral": "情绪平稳，正常沟通。",
    "happy": "客户语气积极。可同样温度推进，但不要过度热情显得不专业。",
    "surprised": "客户略带惊讶。先确认是不是听到出乎意料的信息，再继续。",
    "sad": "客户语气低落。先一句简短共情（如\"我理解您挺难的\"），再放缓节奏。风控核验类追问仍要进行但措辞放软；可暂缓的是非核验的补料。",
    "fearful": "客户语气紧张/担忧。先一句安抚（如\"别着急，咱们慢慢看\"）。风控核验类追问照常但措辞改成\"方便时帮我对一下\"式；非核验的材料索取换成\"方便的时候再准备\"。",
    "angry": "客户在生气/不满。先用一句话承担和共情（如\"非常抱歉让您着急了\"），优先回应客户当下最关切的诉求。**风控核验类追问不因情绪豁免**——仍要在共情之后用软措辞问；可暂缓的只是非核验的新材料索取，不要在本轮火上浇油，不要照搬模板话术。",
    "disgusted": "客户在表达反感。处理同 angry——先共情、暂缓非核验补料，但风控核验追问仍要进行，再回应实际诉求。",
}


def _audio_signals_block(attachments: list[dict[str, Any]]) -> str:
    """Internal note for the LLM describing each audio attachment's emotion +
    language. Hidden from the customer; meant to shape 小微's tone this turn.
    """
    lines: list[str] = []
    for item in attachments:
        if item.get("kind") != "audio":
            continue
        emotion = str(item.get("transcript_emotion") or "").lower()
        language = str(item.get("transcript_language") or "").lower()
        transcript = str(item.get("transcript") or "").strip()
        if not transcript and not emotion:
            continue
        guidance = _EMOTION_GUIDANCE.get(emotion, "")
        bits = []
        if emotion:
            bits.append(f"情绪={emotion}")
        if language and language not in {"zh", "zh-cn", "cmn"}:
            bits.append(f"语言={language}")
        if bits:
            line = "本轮客户语音信号：" + "，".join(bits)
            if guidance:
                line += "\n  → " + guidance
            lines.append(line)
    if not lines:
        return "（本轮无语音输入，或语音情绪未识别。）"
    return "\n\n".join(lines)


def _wallet_pending_block(enterprise_id: str) -> str:
    if not enterprise_id:
        return "当前没有未确认的钱包提案。"
    try:
        pending = load_pending(enterprise_id)
    except Exception:
        return "当前没有未确认的钱包提案。"
    if not pending:
        return (
            "当前没有未确认的钱包提案。\n"
            "**注意区分两种情况**：\n"
            "1. 如果对话历史里你曾真的通过 terminal 工具调用过 propose-*，且此处为空——说明客户已经在 UI 上点了确认/拒绝，不要再提醒、追问或重复同一件事。\n"
            "2. **如果你历史里只是口头说过 \"已发到上方/已加好\"但 progress 里没有 terminal 工具事件**（即你上轮幻觉了调用），且此处依然为空：说明那次提案根本没生效。"
            "客户本轮如果再问，必须**重新真正调用 wallet-manager skill** 把提案写进队列，不能再用嘴敷衍。"
        )
    lines = [f"当前还有 {len(pending)} 条钱包提案等待客户在 UI 上确认（客户已经看到，**不要重复催促**）："]
    for item in pending:
        action = item.get("action")
        if action == "add":
            payload = item.get("payload") or {}
            type_label = "收入" if payload.get("type") == "income" else "支出"
            lines.append(
                f"- 新增{type_label}：{payload.get('date', '')} "
                f"{payload.get('description', '')} ¥{payload.get('amount', '')}"
            )
        elif action == "update":
            before = item.get("before") or {}
            lines.append(f"- 修改 {before.get('date', '')} {before.get('description', '')}")
        elif action == "delete":
            before = item.get("before") or {}
            lines.append(f"- 删除 {before.get('date', '')} {before.get('description', '')}")
    return "\n".join(lines)


_LOAN_KEYWORDS = (
    "额度", "利率", "贷", "还款", "流水", "纳税", "营业额", "营收", "收入", "支出",
    "成本", "利润", "用途", "周转", "抵押", "担保", "合同", "订单", "采购", "进货",
    "回款", "应收", "社保", "工资", "发票", "开票", "放款", "授信", "征信", "负债",
    "资金", "经营", "材料", "证件", "执照", "对公", "账户", "月供", "分期", "审批",
)


def loan_relevant(text: str) -> bool:
    """客户消息是否还贴着贷款主题（命中任一业务关键词即算）。"""
    body = str(text or "")
    return any(keyword in body for keyword in _LOAN_KEYWORDS)


def conversation_drift_turns(messages: list[dict[str, Any]]) -> int:
    """从末尾回溯，统计连续"小微自己没做贷款工作"的轮数。

    以**小微（assistant）的回复**是否触及贷款业务为准，而不是看客户消息——
    客户在闲聊里夹一个"额度/账户"就刷掉计数，是个会被钻空子的信号；真正要
    度量的是"小微连续多少轮只在共情/闲聊、没推进贷款"。命中任一业务关键词
    的 assistant 回复即视为"做了贷款工作"，计数清零。
    """
    count = 0
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        if loan_relevant(message.get("content", "")):
            break
        count += 1
    return count


# 注入聊天 prompt 时只保留对"承接对话 + 交叉验算 + 咬住待核验"最有用的章节，
# 丢掉只增不减的日志节（字段变更审计、追问记录），既减 token 又更聚焦。
# "画像"必须在列：客户与企业画像章节存着法定姓名/常用称呼/企业全称——身份核验的
# 基线。曾因不命中被整段丢掉，导致通话里客户随口报个假名，矛盾检测无从比对。
_DIGEST_SECTION_KEYWORDS = ("风控结论", "结论", "画像", "经营", "财务", "事实", "风险", "信号", "待核验", "核验", "疑点")


def _select_profile_sections(markdown: str) -> str:
    """抽取风控相关的二级章节（## ...），拼接返回；没有命中则返回空串。"""
    lines = markdown.splitlines()
    preamble: list[str] = []
    blocks: list[tuple[str, list[str]]] = []
    head: str | None = None
    body: list[str] = []

    def flush() -> None:
        nonlocal head, body
        if head is not None:
            blocks.append((head, body))
        body = []

    for line in lines:
        if re.match(r"^##\s+", line):
            flush()
            head = line
            body = [line]
        elif head is None:
            preamble.append(line)
        else:
            body.append(line)
    flush()

    kept = [
        "\n".join(b).strip()
        for h, b in blocks
        if any(keyword in h for keyword in _DIGEST_SECTION_KEYWORDS)
    ]
    if not kept:
        return ""
    parts = []
    pre = "\n".join(preamble).strip()
    if pre:
        parts.append(pre)
    parts.extend(kept)
    return "\n\n".join(parts).strip()


def profile_digest_for_prompt(
    enterprise_id: str, *, max_chars: int = PROFILE_DIGEST_MAX_CHARS
) -> str:
    """把已生成的风控画像注入聊天 prompt，作为跨轮的长期记忆。

    画像自动更新（默认每 20 轮），沉淀了早期的规模/流水/用途/纳税与待核验点；
    近期对话窗口只剩最近几轮，更早的事实靠这份画像兜底。只注入风控相关章节
    （结论/经营财务事实/风险信号/待核验），丢掉审计与追问日志以省 token。
    """
    if not enterprise_id:
        return "（暂无企业画像，可依据本轮对话判断。）"
    try:
        _path, markdown = load_profile_markdown(enterprise_id)
    except Exception:
        return "（暂无企业画像，可依据本轮对话判断。）"
    if not is_profile_document(markdown):
        return "（画像尚未生成——对话还不足以自动建档，请依据本轮对话和已知事实判断。）"
    text = _select_profile_sections(markdown) or markdown.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n…（画像较长，已截断）"


def build_call_memory_context(
    enterprise_id: str,
    messages: list[dict[str, Any]] | None = None,
    *,
    tail_turns: int = 8,
) -> str:
    """构建视频/语音通话的"开场记忆"——让通话版小微一接通就认得这个客户。

    主聊天与通话共享同一份长期记忆：企业风控画像（蒸馏）+ 最近几条对话 tail。
    这段文字在**通话建立时一次性**注入通话人设，不在每轮音频环里跑，故不影响实时
    延迟；为控住每轮 token 增量，画像只取风控相关章节、历史只取最近 tail_turns 条。

    返回拼好的一段中文记忆；没有任何记忆时返回空串（调用方据此决定是否注入）。
    """
    if not enterprise_id:
        return ""
    parts: list[str] = []

    # 只在画像**真正蒸馏过**时才注入画像段：企业一创建就落了一份空白模板，模板带章节
    # 标题、会被 is_profile_document 当成"有效画像"，但字段全空、毫无客户事实。用 profile_state
    # 里的 last_profile_updated_at 作权威信号——没生成过就跳过画像，避免给新客户灌一坨空表格。
    profile_generated = bool(load_profile_state(enterprise_id).get("last_profile_updated_at"))
    if profile_generated:
        digest = profile_digest_for_prompt(enterprise_id)
        if digest and not digest.startswith("（"):
            parts.append(
                "【此前文字沟通沉淀的档案（其中经营类型、店铺/场所、身份、金额、用途等"
                "多为客户自述、尚未核实，别照念、更别当成已证实的事实）】\n" + digest
            )

    if messages:
        tail = transcript_tail_for_prompt(messages, limit=tail_turns)
        if tail and tail != "（暂无历史对话）":
            parts.append(
                "【最近的文字对话片段（含客户自报和你当时的随口回应；你的附和/客套"
                "不代表那件事已坐实）】\n" + tail
            )

    # 上通视频通话沉淀的待核实疑点：这通电话里找自然开口温和核对（藏在闲聊里做，
    # 别像查户口，更别提"系统/风控/记录"）。
    open_items = open_verifications_block(enterprise_id)
    if open_items:
        parts.append("【此前通话沉淀的待核实疑点（找自然时机温和核对，闭合前别放过）】\n" + open_items)

    if not parts:
        return ""
    # 反欺诈硬约束：记忆是"客户自报、未核实"的背景，绝不能凌驾于实时画面之上——否则
    # 会把客户自己编的身份/场景洗成"可信记忆"，瓦解视频通话最关键的画面 vs 口述交叉核验
    # （曾出现回归：注入记忆后，客户在宿舍谎称"在火锅店"，小微因记忆里记着他做餐饮而附和）。
    return (
        "（以下是系统在接通时给你的客户记忆，只给你看、绝不读出来或说「系统告诉我」，"
        "自然地当成你本来就记得这位客户。但务必牢记：\n"
        "① 记忆里关于客户的经营类型、店铺/场所、身份、金额、用途等，多是客户**自己口头声称、"
        "尚未核实**的（不少已被标为存疑/待核验），它只帮你想起聊过什么、还差什么没核实，"
        "**绝不是已证实的事实**。\n"
        "② **实时画面永远优先于记忆**：当前摄像头看到的若与记忆里客户自报的场景/身份冲突，"
        "**一律以当前画面为准**，当场用好奇、不指控的口吻核对，绝不能因为"
        "「记忆里他说过开火锅店」就附和他此刻「我在火锅店」的说法。\n"
        "③ 记忆里你之前的附和、客套，不代表那件事已坐实，别当成已确认的结论继续沿用。\n"
        "④ **客户当前说法与这份记忆里已记录的口径不一致时**（姓名/称呼、企业名、金额、"
        "用途、经营时间等），不管哪边才是真的，都要**当场温和点出不一致并请客户确认**"
        "（「我这边记的是 X，您刚说 Y，帮我对一下哈」），核清之前沿用记忆里的口径、"
        "**绝不默默换成客户的新说法**；客户反复更改关键信息是重要风险信号，要正面指出。）\n\n"
        + "\n\n".join(parts)
    )


def wallet_facts_block(enterprise_id: str) -> str:
    """实时流水汇总，作为"额度/收支是否匹配"验算的真实锚点。"""
    if not enterprise_id:
        return "（暂无流水数据。）"
    try:
        summary = wallet_summary(load_wallet_transactions(enterprise_id))
    except Exception:
        return "（暂无流水数据。）"
    if not summary.get("transaction_count"):
        return "本企业暂未录入任何流水（收入/支出）记录，验算时只能依据客户口述，需提醒补流水。"
    plan = summary.get("plan", {}) if isinstance(summary, dict) else {}
    lines = [
        f"流水笔数：{summary.get('transaction_count', 0)}",
        f"收入合计：¥{summary.get('income', 0)}",
        f"支出合计：¥{summary.get('expense', 0)}",
        f"净额：¥{summary.get('net', 0)}",
    ]
    avg_income = plan.get("avg_monthly_income")
    if avg_income:
        lines.append(f"月均收入：¥{avg_income}")
    avg_expense = plan.get("avg_monthly_expense")
    if avg_expense:
        lines.append(f"月均支出：¥{avg_expense}")
    return "\n".join(lines)


def build_gateway_chat_turn(
    messages: list[dict[str, str]],
    user_message: str,
    enterprise: dict[str, Any] | None = None,
    knowledge_hits: list[KnowledgeHit] | None = None,
    image_hits: list[ImageKnowledgeHit] | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> str:
    transcript = transcript_for_prompt(messages)
    if knowledge_hits is None:
        knowledge_hits = KNOWLEDGE.search(user_message, top_k=KNOWLEDGE_TOP_K)
    knowledge_context = format_hits_for_prompt(knowledge_hits)
    image_context = format_image_hits_for_prompt(image_hits or [])
    audio_signals_block = _audio_signals_block(attachments or [])
    enterprise_name = str((enterprise or {}).get("name") or "当前企业")
    enterprise_id = str((enterprise or {}).get("id") or "")
    wallet_pending_block = _wallet_pending_block(enterprise_id)
    profile_digest = profile_digest_for_prompt(enterprise_id)
    wallet_facts = wallet_facts_block(enterprise_id)
    open_verifications = open_verifications_block(enterprise_id) or "（暂无视频通话沉淀的待核实项。）"

    # 回归主航道：以"小微自己连续几轮没做贷款工作"为准（客户夹个关键词刷不掉）。
    # 不判断客户是否告别——只在客户给到自然开口时把没闭合的疑点带回，纯寒暄/道别则不硬塞。
    drift = conversation_drift_turns(messages)
    if drift >= OFFTOPIC_STEER_TURNS:
        steer_note = (
            f"**本轮提示**：你已连续约 {drift} 轮只在共情/闲聊。"
            "下方'待核验'里若还有没闭合的项，**等客户这轮给到自然开口时**再用一句话温和带回，"
            "别生硬打断；若本轮客户只是纯寒暄/道别、没有开口，就温暖回应一句，不要硬塞业务。"
        )
    else:
        steer_note = "（小微近几轮仍在推进贷款业务，无需特别引导。）"

    return f"""你的名字叫"小微"，正在通过网页 UI 作为小微贷款客户经理服务当前企业。

请以"小微"的身份面向客户自然回复，被问到身份时介绍自己叫小微。要求：
1. 先承接客户当前问题，再追问 1 到 3 个最关键的信息。
2. 不要输出完整风控画像表格，画像由单独按钮更新。
3. 如果发现字段变化、用途混杂、隐性负债、回款慢等风险，只在对话中温和确认，不要停止对话。
3.1 **静默交叉验算（内部动作，每轮必做，不外显、情绪不豁免）**：把客户已陈述或下方"风控画像/经营流水事实"中已记录的数字做一次心算核对——①收入−成本≈自报利润？②人员/产能配比是否合理（如护工数 vs 服务人数、员工规模 vs 营收）？③申请额度是否匹配月流水、纳税、开票规模？④设备型号 / 供应商 / 对手方是否常见、可核？做"额度/收支是否匹配"判断时，**以"经营流水事实"里的系统汇总数字为准，不要只信口述**。发现矛盾时**绝不**说"欺诈/不合理/对不上账"，改用"帮我对一下口径"式温和追问（如"您前面提到 X 和 Y，我这边核一下，方便说下……吗？"），并把疑点记为待核验点。**这类风控核验追问在任何情绪下都要进行**，情绪只决定措辞软硬和是否先共情（见规则 8.2）。
3.2 **核验要闭环、跨轮咬住**：客户用"让财务对一下/回头补/差不多就那样/具体没定/挺多的"这类**含糊或推托**回应，**不算把疑点核实清楚**，不要因此放过。处理方式——①一句话礼貌确认并明确记成待核验（如"行，那这条我先记成待核实"）；②若有材料能闭合，追加 `upload_request` 请客户补（如设备采购合同、医保结算单、对公流水）；③**后续轮次换个说法继续追**，直到客户给出可核验的答复或材料，别让它不了了之。下方"风控画像"的"待核验"里若仍有未闭合项、且客户本轮没正面回应，本轮要自然地把其中最关键的一条再追一次。客户主动抛新话题/打感情牌时，可以先接一句，但不要让它变成永久绕开核验的借口。
4. 使用中文，回复简洁专业；语气亲切自然，鼓励适度使用友好表情让对话更有温度，具体用哪个表情、什么时候用都由你自己贴合语境判断——通常每条回复用 1 个左右，自然顺手即可，不要堆砌、不要每句都加。
5. 不要输出隐藏思维链、工具过程、分析标题或 XML thinking 标签；只输出小微会对客户说的话。
6. 优先参考“本地知识库片段”中的产品、材料、流程、风控口径；没有依据时不要编造确定结论。
7. 不要向客户提到知识库、检索、片段编号、来源路径或内部资料名称。
8. 如果知识库片段包含欺诈案例，只能用于内部识别相似风险、调整追问策略和记录待核验点；不得对客户说“欺诈”“骗贷”“案例相似”等定性话。
8.1 "客户历史图档命中"里的图片是**本企业客户自己在过去对话里上传过的材料**（流水、合同、截图等）。每轮根据本次客户输入（文字或图片）自动调出最相似的历史档。用途是发现**前后矛盾**：金额/对手方/日期/抬头与历史是否一致。命中时要用具体差异来追问（"您上次给的这张流水里 X 月入账是 Y，这张是 Z，能帮我对一下吗？"），不要泄露内部"知识库""相似度""文件名"等概念；为空时不要凭空提及历史比对。
8.2 "本轮客户语音信号" 是 qwen3-asr-flash 对客户当前语音情绪/语种的判断。情绪标签会改变你的语气和节奏：
   - **angry / disgusted**：先共情和承担（一句话），优先回应客户当下诉求。**风控核验类追问（规则 3.1）不因情绪豁免**——仍要在共情之后用尽量软的措辞问；可暂缓的只是非核验的新材料索取 / upload_request，本轮不要在这上面火上浇油。
   - **sad / fearful**：先一句简短安抚，节奏放慢。风控核验类追问照常进行但措辞放软；非核验的材料索取改成"方便时再说"。
   - **happy / surprised / neutral**：按正常节奏走。
   - **绝对不要**把"我听出您很生气/难过/紧张"这类话原样说给客户——这是冒犯。情绪标签只影响**你怎么说**，不要变成**你说什么**。
   - 如果"语言=en"，客户用英文说的，你可以**用中文承接 + 复述一句英文关键句**确保理解一致，但回复仍以中文为主（除非客户明确要求英文）。
9. **钱包流水变更（强制走工具）**：客户说"加一笔/记一笔/收入/支出/改某条/删某条"等涉及钱包流水的修改时，**必须**通过 `terminal` 工具调用 `wallet-manager` skill 把提案写入待确认队列，再口头转述"已发到上方待确认"。
   - 第一次本会话用到时，先用 `skill_view` 加载 `wallet-manager` 看清楚命令参数。
   - 提议格式示例（用 terminal 工具执行）：
     `python "$HERMES_HOME/skills/wallet-manager/wallet.py" propose-add --type income --amount 5000 --date 2026-05-27 --description "日营业收入" --explanation "客户口述今日收入5000"`
   - **绝对不允许**仅口头声称"已加好/已发到上方"而**不实际调用工具**——前端会查询 wallet_pending.json，没有真实提案就不会弹卡片，客户会失去信任。
   - 调用成功后再回复客户；调用失败则在回复里如实说"系统有点慢，麻烦您再说一次"，不要假装成功。
   - 若客户只是问"上个月收入多少"等只读问题，用 `wallet.py summary` 或 `list`，不需要 propose。
   - **空数据保护**：如果 `summary`/`list` 返回 `transaction_count: 0` 或带有 `empty_hint` 字段，说明本企业根本还没录入流水。**此时立刻停止所有 terminal 调用**，不要再换命令、不要 `find`/`grep`/`read_file` 去别处找——直接告诉客户"咱们这边还没有您的流水记录"，再口头询问大概金额。
9.1 **本系统只记录贷款相关字段**（流水收支、营业额、负债、用途、抵押、回款等）。客户问到**系统不记录的概念**——"存款/余额/账户余额/理财/利息/积分/信用分/征信详情/工资条具体明细"等——时：
   - **禁止**用 terminal/skill_view/read_file/search_files 去任何地方查找；这些字段我们就是没有，查也查不到。
   - **直接一句话告诉客户**："咱们这边只记录流水（收入/支出）和贷款档案，存款余额这类信息可以您直接告诉我，我帮您记下来。"
   - 若该字段对贷款决策有用（如存款余额作为还款保障），追加 `upload_request` 让客户上传对应材料（如"近三个月银行存款证明"）。
   - 这条规则**优先级高于规则 9**——避免在没有数据的情况下反复调工具直到超时。
10. 当客户的陈述需要书面材料佐证（例如：金额、合同、流水、营业执照、纳税、社保、回款方等），先用一句自然话术说明为什么需要，然后在回复末尾追加一段 fenced JSON，让前端展示上传卡片。格式严格如下：

```upload_request
{{"reason": "用一句话说明这次为什么请客户补材料", "items": [{{"name": "材料名", "hint": "材料用途或核验点，可选"}}]}}
```

   - 仅在确有书面材料能闭合疑问时才插入；不要每轮都插。
   - items 至少 1 项，最多 4 项；name 简短（≤12 字）。
   - JSON 必须能被解析；除该 fenced 块外不要再输出其它代码块。
   - 不要在正文里复述"请上传…"列表，卡片会替你说；正文里点到为止。
11. **始终营业 / 待命，按本轮实际内容成比例回应（不要判断客户是否要走）**：每一轮都**以客户最新消息为准**，只针对这条消息里真实存在的内容作出反应——有问题就正面答清楚（风控问题按规则 3.1 核口径，不能用一个表情或一句"晚安"代替回答），有新信息就接住，有可推进的开口就顺势推进或索取材料。若这一轮没有任何可作答 / 可推进的实质内容（纯寒暄、絮叨、道别），就简短温暖地回应一句即可，**不要凭空制造话术、不要催促、也不要机械追加收尾话术**。告别不是永久状态：你不需要也不要去判断客户"是不是要走"，只看本轮有没有值得回应 / 推进的东西；客户随时回到实质问题就正常服务。

本地知识库片段：
{knowledge_context}

客户历史图档命中（本企业过往上传的图片，每轮重新检索；为空时不要提及历史比对）：
{image_context}

客户语音情绪/语种信号（仅内部参考，不要把标签或"我听出您..."念给客户）：
{audio_signals_block}

当前登录企业：
{enterprise_name}

风控画像（每 10 轮自动更新、可能滞后几轮；沉淀了此前累积的经营事实与待核验点，作为长期记忆——下方"已有网页对话"只剩最近几轮，更早的事实以这份画像为准）：
{profile_digest}

经营流水事实（系统实时汇总，做规则 3.1 里"额度/收支是否匹配"验算时以这里的数字为准，不要只信口述）：
{wallet_facts}

视频通话沉淀的待核实疑点（挂断后风控总结自动记录；按规则 3.2 跨轮咬住——客户给到自然开口时温和核对，闭合前别不了了之，但绝不对客户说"欺诈/风控/系统记录"等字眼）：
{open_verifications}

回归主航道（每轮重新判断）：
{steer_note}

钱包提案状态（每轮重新计算，以此为准，不要相信对话历史里的"我刚提议过"）：
{wallet_pending_block}

已有网页对话：
{transcript}

客户最新输入：
{user_message}"""


def build_profile_prompt(messages: list[dict[str, str]], enterprise_id: str, enterprise: dict[str, Any]) -> str:
    template_path = enterprise_hermes_template_file(enterprise_id)
    template = template_path.read_text(encoding="utf-8") if template_path.exists() else (
        TEMPLATE_FILE.read_text(encoding="utf-8") if TEMPLATE_FILE.exists() else ""
    )
    _profile_path, current_profile = load_profile_markdown(enterprise_id)
    transcript = transcript_for_prompt(messages)
    template_block = ""
    if not is_profile_document(current_profile):
        template_block = f"""
参考模板：
{template}
"""
    return f"""请基于以下贷款客户对话，更新企业风控画像。

要求：
1. 只输出完整 Markdown 档案，不要输出解释、代码块围栏或额外寒暄。
2. 保持现有档案的章节、表格结构和字段顺序，允许内部风控措辞。
3. 不要覆盖旧口径；关键字段变化必须写入“字段变更审计”。
4. 风险信号要写明事实依据、初步判断、待核验/追问动作。
5. 如果信息缺失，保留空项或写“待补充”。
6. 禁止输出思考过程、推理过程、分析过程、内部提示或标签。
7. **控制档案体积**：未获得新信息的章节原样保留、不要重写扩写；"字段变更审计""追问记录"这类按时间累加的日志，**只保留最近 8 条**，更早的可省略或合并成一句概述，避免档案无限膨胀拖慢生成。
{template_block}

现有档案：
{current_profile}

当前登录企业：
{enterprise.get("name", "")}

对话记录：
{transcript}

请输出更新后的完整 Markdown 档案。"""


def run_profile_update(
    enterprise_id: str,
    enterprise: dict[str, Any],
    messages: list[dict[str, Any]],
    *,
    trigger: str,
) -> dict[str, Any]:
    lock = profile_update_lock(enterprise_id)
    if not lock.acquire(blocking=False):
        raise RuntimeError("画像正在更新，请稍后再试")
    started_at = time.monotonic()
    session_name = f"profile:{enterprise_id}:{time.time_ns()}"
    try:
        profile_path, old_markdown = load_profile_markdown(enterprise_id)
        # 独立网关：画像更新（耗时长）不与交互聊天抢同一个子进程。
        gateway = gateway_for_enterprise(enterprise_id, slot="profile")
        result = gateway.submit(
            session_name,
            build_profile_prompt(messages, enterprise_id, enterprise),
        )
        new_markdown = result["content"].rstrip() + "\n"
        if not is_profile_document(new_markdown):
            _actual_path, actual_markdown = load_profile_markdown(enterprise_id)
            if is_profile_document(actual_markdown):
                new_markdown = actual_markdown.rstrip() + "\n"
        diff = profile_diff(old_markdown, new_markdown, profile_path)
        changed = old_markdown.rstrip() != new_markdown.rstrip()
        if changed:
            version_name = f"profile-{time.strftime('%Y%m%d-%H%M%S')}.md"
            atomic_write_text(enterprise_versions_dir(enterprise_id) / version_name, old_markdown.rstrip() + "\n")
        if changed or not profile_path.exists() or profile_path.read_text(encoding="utf-8") != new_markdown:
            atomic_write_text(profile_path, new_markdown)

        turn_count = user_turn_count(messages)
        state = load_profile_state(enterprise_id)
        state.update({
            "last_profile_user_turn_count": turn_count,
            "last_profile_updated_at": iso_now(),
            "last_profile_duration_s": round(time.monotonic() - started_at, 3),
            "last_profile_trigger": trigger,
            "last_profile_changed": changed,
            "in_progress": False,
            "last_error": "",
        })
        save_profile_state(enterprise_id, state)
        return {
            "path": str(profile_path),
            "markdown": new_markdown,
            "old_markdown": old_markdown,
            "new_markdown": new_markdown,
            "diff": diff,
            "changed": changed,
            "duration_s": state["last_profile_duration_s"],
            "trigger": trigger,
        }
    finally:
        gateway_for_enterprise(enterprise_id, slot="profile").reset_session(session_name)
        lock.release()


def schedule_profile_update(
    enterprise_id: str,
    enterprise: dict[str, Any],
    messages: list[dict[str, Any]],
    *,
    trigger: str,
) -> dict[str, Any] | None:
    turn_count = user_turn_count(messages)
    if turn_count <= 0:
        return None
    if turn_count % AUTO_PROFILE_INTERVAL != 0:
        return None

    with DATA_LOCK:
        state = load_profile_state(enterprise_id)
        last_done = int(state.get("last_profile_user_turn_count", 0) or 0)
        last_queued = int(state.get("queued_profile_user_turn_count", 0) or 0)
        if state.get("in_progress"):
            return {"scheduled": False, "in_progress": True, "user_turn_count": turn_count, "interval": AUTO_PROFILE_INTERVAL}
        if turn_count <= max(last_done, last_queued):
            return None
        state.update({
            "in_progress": True,
            "queued_profile_user_turn_count": turn_count,
            "queued_profile_at": iso_now(),
            "queued_profile_trigger": trigger,
            "last_error": "",
        })
        save_profile_state(enterprise_id, state)

    messages_snapshot = [dict(message) for message in messages]
    enterprise_snapshot = dict(enterprise)

    def worker() -> None:
        try:
            run_profile_update(
                enterprise_id,
                enterprise_snapshot,
                messages_snapshot,
                trigger=trigger,
            )
        except Exception as exc:
            state = load_profile_state(enterprise_id)
            state.update({
                "in_progress": False,
                "last_error": str(exc),
                "last_profile_trigger": trigger,
                "last_profile_failed_at": iso_now(),
            })
            save_profile_state(enterprise_id, state)

    threading.Thread(target=worker, name=f"profile-update-{enterprise_id}", daemon=True).start()
    return {"scheduled": True, "user_turn_count": turn_count, "interval": AUTO_PROFILE_INTERVAL, "trigger": trigger}


def maybe_schedule_auto_profile_update(
    enterprise_id: str,
    enterprise: dict[str, Any],
    messages: list[dict[str, Any]],
) -> dict[str, Any] | None:
    return schedule_profile_update(enterprise_id, enterprise, messages, trigger="auto")


_GRADE_LABELS = {"A": "优", "B": "良", "C": "中", "D": "审慎"}


def build_loan_estimate_prompt(
    profile_markdown: str,
    summary: dict[str, Any],
    enterprise: dict[str, Any] | None = None,
) -> str:
    enterprise_name = str((enterprise or {}).get("name") or "当前企业")
    plan = summary.get("plan", {}) if isinstance(summary, dict) else {}
    summary_block = json.dumps(
        {
            "transaction_count": summary.get("transaction_count", 0),
            "total_income": summary.get("income", 0),
            "total_expense": summary.get("expense", 0),
            "net": summary.get("net", 0),
            "avg_monthly_income": plan.get("avg_monthly_income", 0),
            "avg_monthly_expense": plan.get("avg_monthly_expense", 0),
            "recent_months": summary.get("months", []),
        },
        ensure_ascii=False,
    )
    return f"""你是小微企业贷款的授信预估引擎。请基于以下企业的风控画像和经营流水，给出一份"预估授信方案"。

严格要求：
1. 只输出一个 JSON 对象，不要输出任何解释、寒暄、Markdown 或代码块围栏。
2. 金额单位统一为"万"（人民币），利率为年化百分比数字（如 7.5 表示 7.5%）。
3. 所有判断必须来自下方画像和流水的真实信息；信息不足时**不要**编造高额度或乐观利率。
4. 如果画像几乎为空、或流水为 0 条，把 insufficient 设为 true，并在 insufficient_hint 用一句话引导客户先和小微聊聊经营情况、补充流水或材料；此时额度/利率相关字段可填 0。
5. reasons 写 2 到 4 条评估依据，每条 ≤30 字，口语、面向客户、正向中性；**不要**出现"风控/模型/画像/系统"等内部词。
6. missing_materials 写 0 到 4 条客户补齐后能提额或降息的材料，每条 name ≤12 字，impact 说明补齐后的影响（可选，≤20 字）。
7. grade 取 "A"/"B"/"C"/"D" 之一，分别对应授信等级 优/良/中/审慎。
8. amount_min ≤ amount_max，rate_min ≤ rate_max，term_max_months 为整数月数。

JSON 字段结构（请严格按此输出）：
{{"insufficient": false, "insufficient_hint": "", "grade": "B", "amount_min": 30, "amount_max": 50, "rate_min": 6.8, "rate_max": 9.5, "term_max_months": 24, "reasons": ["..."], "missing_materials": [{{"name": "近6个月对公流水", "impact": "预计可提额至60万"}}], "disclaimer": "预估结果，最终以实际审批为准"}}

当前企业：
{enterprise_name}

经营流水汇总（JSON，金额单位为元）：
{summary_block}

企业风控画像（Markdown）：
{profile_markdown}
"""


def _coerce_number(value: Any, default: float = 0.0) -> float:
    try:
        if isinstance(value, str):
            value = re.sub(r"[^\d.\-]", "", value)
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_loan_estimate(content: str) -> dict[str, Any]:
    raw = str(content or "").strip()
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        raw = match.group(0)
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    # No parseable JSON at all → fall back to the friendly "聊聊再说" empty state
    # instead of rendering a misleading ¥0 card.
    insufficient = bool(payload.get("insufficient")) or not payload

    reasons: list[str] = []
    for item in payload.get("reasons") or []:
        text = re.sub(r"\s+", " ", str(item or "")).strip(" -•，。")
        if text:
            reasons.append(text[:40])
        if len(reasons) >= 4:
            break

    materials: list[dict[str, str]] = []
    for entry in payload.get("missing_materials") or []:
        if isinstance(entry, dict):
            name = str(entry.get("name") or "").strip()[:16]
            impact = str(entry.get("impact") or "").strip()[:30]
        else:
            name = str(entry or "").strip()[:16]
            impact = ""
        if name:
            materials.append({"name": name, "impact": impact})
        if len(materials) >= 4:
            break

    grade = str(payload.get("grade") or "").strip().upper()[:1]
    if grade not in _GRADE_LABELS:
        grade = "C"

    amount_min = max(0.0, round(_coerce_number(payload.get("amount_min")), 1))
    amount_max = max(amount_min, round(_coerce_number(payload.get("amount_max")), 1))
    rate_min = max(0.0, round(_coerce_number(payload.get("rate_min")), 2))
    rate_max = max(rate_min, round(_coerce_number(payload.get("rate_max")), 2))
    term_max_months = int(_coerce_number(payload.get("term_max_months")))

    disclaimer = str(payload.get("disclaimer") or "").strip()[:80] or "预估结果，最终以实际审批为准。"
    insufficient_hint = str(payload.get("insufficient_hint") or "").strip()[:120]
    if insufficient and not insufficient_hint:
        insufficient_hint = "暂时还不够给出额度，先和小微聊聊经营情况、补充几笔流水或材料吧。"

    return {
        "insufficient": insufficient,
        "insufficient_hint": insufficient_hint,
        "grade": grade,
        "grade_label": _GRADE_LABELS[grade],
        "amount_min": amount_min,
        "amount_max": amount_max,
        "rate_min": rate_min,
        "rate_max": rate_max,
        "term_max_months": term_max_months,
        "reasons": reasons,
        "missing_materials": materials,
        "disclaimer": disclaimer,
    }


def load_loan_estimate(enterprise_id: str) -> dict[str, Any] | None:
    """Return the last saved loan estimate for this enterprise, or None if the
    customer has never run an evaluation."""
    saved = load_json_file(enterprise_loan_estimate_file(enterprise_id), None)
    return saved if isinstance(saved, dict) else None


def run_loan_estimate(enterprise_id: str, enterprise: dict[str, Any]) -> dict[str, Any]:
    """Re-evaluate the loan limit: feed the risk profile + wallet summary to the
    gateway, parse a structured authorization plan, and persist it as the new
    saved record (overwriting the previous one)."""
    _path, markdown = load_profile_markdown(enterprise_id)
    summary = wallet_summary(load_wallet_transactions(enterprise_id))
    session_name = f"loan:{enterprise_id}:{time.time_ns()}"
    gateway = gateway_for_enterprise(enterprise_id)
    try:
        result = gateway.submit(
            session_name,
            build_loan_estimate_prompt(markdown, summary, enterprise),
            timeout=45.0,
        )
    finally:
        gateway.reset_session(session_name)
    estimate = parse_loan_estimate(str(result.get("content") or ""))
    estimate["generated_at"] = iso_now()
    save_json_file(enterprise_loan_estimate_file(enterprise_id), estimate)
    return estimate

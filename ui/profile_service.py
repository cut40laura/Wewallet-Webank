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


_EMOTION_GUIDANCE = {
    "neutral": "情绪平稳，正常沟通。",
    "happy": "客户语气积极。可同样温度推进，但不要过度热情显得不专业。",
    "surprised": "客户略带惊讶。先确认是不是听到出乎意料的信息，再继续。",
    "sad": "客户语气低落。先一句简短共情（如\"我理解您挺难的\"），再放缓节奏，本轮最多 1 个追问。",
    "fearful": "客户语气紧张/担忧。先一句安抚（如\"别着急，咱们慢慢看\"），把要求材料的语气换成\"方便的时候再准备\"，本轮最多 1 个追问。",
    "angry": "客户在生气/不满。**先暂停所有追问和材料索取**，用一句话承担和共情（如\"非常抱歉让您等久了\"），然后只回应客户当下最关切的诉求；不要在本轮要求新材料、不要绕开问题、不要照搬模板话术。",
    "disgusted": "客户在表达反感。处理同 angry——先共情和停止索取，再回应实际诉求。",
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
    wallet_pending_block = _wallet_pending_block(str((enterprise or {}).get("id") or ""))
    return f"""你的名字叫"小微"，正在通过网页 UI 作为小微贷款客户经理服务当前企业。

请以"小微"的身份面向客户自然回复，被问到身份时介绍自己叫小微。要求：
1. 先承接客户当前问题，再追问 1 到 3 个最关键的信息。
2. 不要输出完整风控画像表格，画像由单独按钮更新。
3. 如果发现字段变化、用途混杂、隐性负债、回款慢等风险，只在对话中温和确认，不要停止对话。
4. 使用中文，回复简洁专业；语气亲切自然，鼓励适度使用友好表情让对话更有温度，具体用哪个表情、什么时候用都由你自己贴合语境判断——通常每条回复用 1 个左右，自然顺手即可，不要堆砌、不要每句都加。
5. 不要输出隐藏思维链、工具过程、分析标题或 XML thinking 标签；只输出小微会对客户说的话。
6. 优先参考“本地知识库片段”中的产品、材料、流程、风控口径；没有依据时不要编造确定结论。
7. 不要向客户提到知识库、检索、片段编号、来源路径或内部资料名称。
8. 如果知识库片段包含欺诈案例，只能用于内部识别相似风险、调整追问策略和记录待核验点；不得对客户说“欺诈”“骗贷”“案例相似”等定性话。
8.1 "客户历史图档命中"里的图片是**本企业客户自己在过去对话里上传过的材料**（流水、合同、截图等）。每轮根据本次客户输入（文字或图片）自动调出最相似的历史档。用途是发现**前后矛盾**：金额/对手方/日期/抬头与历史是否一致。命中时要用具体差异来追问（"您上次给的这张流水里 X 月入账是 Y，这张是 Z，能帮我对一下吗？"），不要泄露内部"知识库""相似度""文件名"等概念；为空时不要凭空提及历史比对。
8.2 "本轮客户语音信号" 是 qwen3-asr-flash 对客户当前语音情绪/语种的判断。情绪标签会改变你的语气和节奏：
   - **angry / disgusted**：先共情和承担（一句话），然后**只回应客户当下诉求**，本轮不再要求新材料、不发 upload_request、不重复之前的追问。
   - **sad / fearful**：先一句简短安抚，节奏放慢，本轮最多 1 个追问，措辞改成"方便时再说"。
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
11. **以客户最新消息为准**：客户暂停或告别时，由你结合语境自然判断如何回应，不要机械追加收尾话术，也不要继续强推流程。告别不是永久状态；如果客户之后继续提出实质问题，正常回答当前问题并继续服务。

本地知识库片段：
{knowledge_context}

客户历史图档命中（本企业过往上传的图片，每轮重新检索；为空时不要提及历史比对）：
{image_context}

客户语音情绪/语种信号（仅内部参考，不要把标签或"我听出您..."念给客户）：
{audio_signals_block}

当前登录企业：
{enterprise_name}

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
        gateway = gateway_for_enterprise(enterprise_id)
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
        gateway_for_enterprise(enterprise_id).reset_session(session_name)
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

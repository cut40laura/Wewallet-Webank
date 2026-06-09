"""
用户模拟器 — 模拟真实客户与钱包项目对话，用于 RL 训练数据收集。

架构：
  DeepSeek V4 Pro (模拟用户大脑)
       ↓ 生成消息 + 自主决定继续/终止
  wewallet chat API (客户经理)
       ↓ 返回回复
  Evaluator (评分)
       ↓
  对话日志 + 客户评价 → RL 训练数据

用法：
  python3 user_simulator.py --persona laowang --max-turns 10
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
import hashlib
import urllib.request
import urllib.error
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

SIMULATOR_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SIMULATOR_DIR.parent


def _load_dotenv(path: Path) -> None:
    """轻量 .env 加载：只填充尚未在环境中的键，无第三方依赖。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(PROJECT_ROOT / ".env")

# ============================================================
# 配置
# ============================================================
# 模拟器"假客户"大脑（OpenAI 兼容）。优先用 SIMULATOR_LLM_*，回退兼容旧的 DEEPSEEK_*。
LLM_API_KEY = os.environ.get("SIMULATOR_LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY", "")
LLM_BASE_URL = (
    os.environ.get("SIMULATOR_LLM_BASE_URL")
    or os.environ.get("DEEPSEEK_BASE_URL")
    or "https://api.deepseek.com/v1"
)
LLM_MODEL = os.environ.get("SIMULATOR_LLM_MODEL") or os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
# 本地 server.py 默认端口 8787（CUSTOMER_MANAGER_UI_PORT），可用 WEWALLET_BASE 覆盖
WEWALLET_BASE = os.environ.get("WEWALLET_BASE", "http://127.0.0.1:8787")
MEMORY_DIR = SIMULATOR_DIR / "memory"
LOG_DIR = SIMULATOR_DIR / "logs"
MAX_TURNS_DEFAULT = 100

os.makedirs(MEMORY_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)


# ============================================================
# 客户画像加载（从独立 .md 文件）
# ============================================================

PERSONAS_DIR = SIMULATOR_DIR / "personas"

def _split_frontmatter(text: str) -> tuple[dict, str]:
    """分离扁平 frontmatter 和正文（仅支持 key: value，无第三方依赖）。"""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, Any] = {}
    for line in parts[1].splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip().strip('"').strip("'")
        meta[key.strip()] = value
    body = parts[2].strip()
    return meta, body


def load_personas() -> dict[str, dict[str, Any]]:
    """从 personas/*.md 加载所有客户画像。"""
    personas: dict[str, dict[str, Any]] = {}
    for md_path in sorted(PERSONAS_DIR.glob("*.md")):
        key = md_path.stem  # 文件名即 key: laowang, xiaoqin, ...
        text = md_path.read_text(encoding="utf-8")
        meta, body = _split_frontmatter(text)
        personas[key] = {
            "id": meta.get("id", f"customer_{key}"),
            "name": meta.get("name", key),
            "full_name": meta.get("full_name", ""),
            "phone": str(meta.get("phone", "")),
            "password": str(meta.get("password", "")),
            "enterprise_name": meta.get("enterprise_name", ""),
            "enterprise_credit_code": meta.get("enterprise_credit_code", ""),
            "patience": float(meta.get("patience", 0.6)),
            "politeness": float(meta.get("politeness", 0.5)),
            "suspicion": float(meta.get("suspicion", 0.5)),
            "persona_prompt": body,
            "initial_message_pool": [
                f"你好，我想问问你们这个贷款怎么搞的？",
                f"你好，我开{meta.get('enterprise_name', '店')}的，想借点钱",
                f"你好，听说你们这边借钱利息挺低的？朋友介绍的",
            ],
        }
        print(f"  📂 加载画像: {meta.get('name', key)} ({key})")
    return personas


PERSONAS = load_personas()




# ============================================================
# DeepSeek API 调用
# ============================================================

def deepseek_chat(
    messages: list[dict[str, str]],
    temperature: float = 0.9,
    max_tokens: int = 300,
) -> str:
    """调用模拟器 LLM（OpenAI 兼容，模型/地址由环境变量决定）生成回复。"""
    payload = json.dumps({
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{LLM_BASE_URL}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[DeepSeek ERROR] {e}")
        return ""


# ============================================================
# WeWallet API 封装
# ============================================================

class WeWalletClient:
    """封装钱包项目 chat API 调用。"""

    def __init__(self, base_url: str = WEWALLET_BASE):
        self.base_url = base_url
        self.cookies: dict[str, str] = {}
        self.enterprise_id: str = ""
        # clear_agent_memory 清空的文件 → 原始内容，供 restore_agent_memory 还原
        self._memory_backup: dict[Path, str | None] = {}

    def _request(self, method: str, path: str, data: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        payload = json.dumps(data).encode("utf-8") if data else None

        headers = {"Content-Type": "application/json"}
        if self.cookies:
            cookie_str = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
            headers["Cookie"] = cookie_str

        req = urllib.request.Request(url, data=payload, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                set_cookie = resp.getheader("Set-Cookie")
                if set_cookie:
                    for part in set_cookie.split(";"):
                        if "=" in part:
                            k, v = part.split("=", 1)
                            self.cookies[k.strip()] = v.strip()
                body = resp.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8")
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return {"error": body, "status": e.code}

    def login(self, phone: str, password: str) -> bool:
        resp = self._request("POST", "/api/auth/password/login", {
            "phone": phone, "password": password,
        })
        return resp.get("authenticated", False)

    def create_enterprise(self, name: str, credit_code: str = "") -> bool:
        resp = self._request("POST", "/api/enterprise/create", {
            "name": name, "credit_code": credit_code,
        })
        ent = resp.get("enterprise", {})
        self.enterprise_id = ent.get("id", "")
        if self.enterprise_id:
            return True
        me = self._request("GET", "/api/auth/me")
        ent = me.get("enterprise", {})
        if ent and ent.get("id"):
            self.enterprise_id = ent["id"]
            return True
        msgs = self._request("GET", "/api/messages")
        if isinstance(msgs, dict) and not msgs.get("error"):
            return True
        return False

    def send_message(self, text: str, frustration: float = 0.0, customer_name: str = "") -> dict:
        payload = {"message": text, "frustration": round(frustration, 2)}
        if customer_name:
            payload["customer_name"] = customer_name
        return self._request("POST", "/api/chat", payload)

    def get_messages(self) -> list[dict]:
        return self._request("GET", "/api/messages").get("messages", [])

    def reset_conversation(self) -> bool:
        return self._request("POST", "/api/reset").get("ok", False)
    
    def clear_agent_memory(self) -> bool:
        """跑测前清空 agent 跨会话记忆，确保信息隔离。

        会先把原始内容备份到 self._memory_backup，结束时由 restore_agent_memory 还原，
        避免污染 git 跟踪的 .hermes-customer-manager/memories/{MEMORY,USER}.md。
        """
        if not self.enterprise_id:
            return False
        # 1. 运行时企业目录记忆（每次跑测临时生成，可清）
        mem_dir = PROJECT_ROOT / "runtime" / "app_data" / "hermes_homes" / f"ent_{self.enterprise_id}" / "memories"
        # 2. hermes_home 全局记忆（agent 实际写入位置，但被 git 跟踪 → 用完要还原）
        global_mem = PROJECT_ROOT / ".hermes-customer-manager" / "memories"
        try:
            for d in [mem_dir, global_mem]:
                d.mkdir(parents=True, exist_ok=True)
                for f in ["MEMORY.md", "USER.md"]:
                    p = d / f
                    if p not in self._memory_backup:
                        self._memory_backup[p] = p.read_text("utf-8") if p.exists() else None
                    p.write_text("", "utf-8")
            return True
        except Exception:
            return False

    def restore_agent_memory(self) -> None:
        """还原 clear_agent_memory 备份的原始记忆内容。"""
        for p, original in self._memory_backup.items():
            try:
                if original is None:
                    if p.exists():
                        p.unlink()
                else:
                    p.write_text(original, "utf-8")
            except Exception:
                pass
        self._memory_backup.clear()


# ============================================================
# 对话评估器
# ============================================================

@dataclass
class TurnScore:
    turn: int
    user_message: str
    assistant_reply: str
    empathy: float = 0.0
    info_richness: float = 0.0
    relevance: float = 0.0
    professionalism: float = 0.0
    knowledge_exchange: float = 0.0
    overall: float = 0.0
    notes: str = ""


def evaluate_turn(
    turn: int,
    user_message: str,
    assistant_reply: str,
    conversation_history: str,
    persona_name: str,
) -> TurnScore:
    eval_prompt = f"""你是对话质量评估专家。请评估以下贷款客户经理的回复质量。

## 客户画像
{persona_name}：小微企业主，来咨询贷款。

## 本轮对话
客户：{user_message}
客户经理：{assistant_reply}

## 评分标准（每项 0-100 分）
1. empathy（陪伴感/人情味）：回复是否让人愿意继续聊？有没有温度、懂不懂行业？**核心指标**
2. info_richness（信息丰度潜力）：这轮回复是否可能引发客户分享更多信息？有没有抛话题、埋锚点？
3. relevance（理解度）：是否准确理解客户意图、抓住了关键细节？
4. professionalism（专业度）：信息是否准确、有依据？有没有给客户有用的知识？
5. knowledge_exchange（知识互换）：有没有先给客户有价值的信息（算利息、讲流程、聊行业）再问问题？

## 输出格式（仅 JSON）
{{"empathy": 85, "info_richness": 80, "relevance": 90, "professionalism": 85, "knowledge_exchange": 75, "notes": "一句话点评"}}
"""
    try:
        raw = deepseek_chat(
            [{"role": "user", "content": eval_prompt}],
            temperature=0.3, max_tokens=200,
        )
        match = re.search(r"\{[^}]+\}", raw)
        if match:
            scores = json.loads(match.group())
            return TurnScore(
                turn=turn,
                user_message=user_message,
                assistant_reply=assistant_reply,
                empathy=scores.get("empathy", 0) / 100,
                info_richness=scores.get("info_richness", 0) / 100,
                relevance=scores.get("relevance", 0) / 100,
                professionalism=scores.get("professionalism", 0) / 100,
                knowledge_exchange=scores.get("knowledge_exchange", 0) / 100,
                overall=sum([
                    scores.get("empathy", 0),
                    scores.get("info_richness", 0),
                    scores.get("relevance", 0),
                    scores.get("professionalism", 0),
                    scores.get("knowledge_exchange", 0),
                ]) / 500,
                notes=scores.get("notes", ""),
            )
    except Exception as e:
        print(f"[Eval ERROR] {e}")
    return TurnScore(turn=turn, user_message=user_message, assistant_reply=assistant_reply)


# ============================================================
# 客户厌烦度模型 — 动态决定何时终止
# ============================================================

# 重复追问检测词库
REPETITION_PATTERNS = [
    "纳税", "电子税务", "流水", "合同", "负债", "借款",
    "贷款", "抵押", "担保", "征信", "法人", "对公",
    "营业执照", "供应商", "租约", "租金",
]

MIN_FORCED_TURNS = 8  # 最低强制轮数，不到此轮数不终止。12+轮应通过陪伴自然达到，非强制。

# 退出意图检测词库 — 客户明确想结束对话的信号
EXIT_SIGNALS = [
    "再见", "拜拜", "睡了", "睡觉", "明早", "明天见",
    "先走了", "回头聊", "先这样", "走了啊", "晚安",
    "回见", "不聊了", "先忙", "去忙了", "忙去了",
    "先下了", "挂了啊", "改天", "下次聊", "先这样吧",
    "得走了", "该走了", "休息了", "困了",
]

EXIT_SIGNAL_BASE_PENALTY = 0.10   # 首次退出信号的基础惩罚
EXIT_SIGNAL_ESCALATION = 0.03     # 每次连续退出递增
EXIT_MAX_CONSECUTIVE_PENALTY = 0.25  # 连续退出惩罚上限


def _detect_exit_intent(user_message: str) -> bool:
    """检测客户是否发出明确的退出信号。"""
    for signal in EXIT_SIGNALS:
        if signal in user_message:
            return True
    return False


def _calc_exit_penalty(consecutive_exits: int) -> float:
    """计算退出意图惩罚分 — 连续退出递增。

    首次退出: 0.10
    第二次:   0.13
    第三次:   0.16
    ...
    上限:     0.25
    """
    if consecutive_exits <= 0:
        return 0.0
    penalty = EXIT_SIGNAL_BASE_PENALTY + (consecutive_exits - 1) * EXIT_SIGNAL_ESCALATION
    return min(penalty, EXIT_MAX_CONSECUTIVE_PENALTY)


# 兴趣锚点话题词库 — 用于检测 agent 是否在同一个非贷款话题上反复打转
ANCHOR_TOPIC_KEYWORDS = [
    # 餐饮/美食
    "藤椒", "花椒", "麻", "辣", "腌", "炒", "菜", "口味", "配方",
    "剁椒", "水煮鱼", "凤爪", "泡椒", "厨房", "厨师", "食材", "调料",
    "菜品", "菜单", "招牌", "回头客", "好吃", "香", "味道", "辣椒",
    "菜籽油", "空运", "微辣",
    # 通用兴趣话题
    "广场舞", "跳舞", "孩子", "上学", "老家", "房子",
]

TOPIC_DECAY_SCHEDULE = [1.0, 0.7, 0.4, 0.15, 0.0]  # 同话题第1/2/3/4/5+轮的衰减系数


def _count_anchor_keywords(text: str) -> int:
    """统计一段文字中兴趣锚点关键词的出现次数。"""
    count = 0
    for kw in ANCHOR_TOPIC_KEYWORDS:
        count += text.count(kw)
    return count


def _get_topic_decay(topic_stickiness: int) -> float:
    """同话题重复轮数 → 衰减系数。

    topic_stickiness=0 (新话题): 1.0
    topic_stickiness=1 (第2轮):  0.7
    topic_stickiness=2 (第3轮):  0.4
    topic_stickiness=3 (第4轮):  0.15
    topic_stickiness>=4:         0.0  — 不再加分
    """
    if topic_stickiness <= 0:
        return 1.0
    idx = min(topic_stickiness, len(TOPIC_DECAY_SCHEDULE) - 1)
    return TOPIC_DECAY_SCHEDULE[idx]


def _detect_repetition(assistant_reply: str, recent_assistant_replies: list[str]) -> float:
    """检测 agent 是否在反复追问同样的事。
    
    Returns:
        惩罚分 0.0~0.12
    """
    if not recent_assistant_replies:
        return 0.0
    
    overlap = 0
    for pattern in REPETITION_PATTERNS:
        if pattern in assistant_reply:
            # 这个关键词在最近几轮也出现过吗？
            for recent in recent_assistant_replies:
                if pattern in recent:
                    overlap += 1
                    break
    
    # 2个以上重叠关键词 → agent 在反复问 → 厌烦
    if overlap >= 3:
        return 0.10
    elif overlap >= 2:
        return 0.06
    elif overlap >= 1:
        return 0.02
    return 0.0


def update_frustration(
    persona: dict,
    score: "TurnScore",
    assistant_reply: str,
    recent_assistant_replies: list[str],
    current_frustration: float,
    consecutive_exits: int = 0,
    topic_stickiness: int = 0,
) -> tuple[float, dict]:
    """计算本轮后的厌烦度。
    
    厌烦度是 0~1 的累积值：
    - 基础疲劳 + 重复追问 + 退出意图 + 压迫感 → 上升
    - 共情 + 信息丰度 + 知识互换 → 下降（受话题衰退衰减）
    
    Returns:
        (new_frustration, delta_detail_dict)
    """
    patience = persona.get("patience", 0.6)
    
    # 话题衰减系数 — 同一兴趣锚点重复越久，降躁效果越弱
    topic_decay = _get_topic_decay(topic_stickiness)
    
    # 1. 自然疲劳 — 每轮 +0.03~0.04
    base_fatigue = 0.032 * (1.0 - patience) + 0.032
    
    # 2. 重复追问惩罚 — agent 反复问同样的问题
    repetition_penalty = _detect_repetition(assistant_reply, recent_assistant_replies)
    
    # 3. 共情奖励 — 严格：只有共情>80%才降厌烦
    empathy_bonus = max(0.0, score.empathy - 0.80) * 0.08  # 0 ~ 0.016
    
    # 4. 信息丰度奖励 — 兴趣锚点法，受话题衰退衰减
    info_richness_bonus = max(0.0, score.info_richness - 0.70) * 0.07 * topic_decay  # 衰减后 0 ~ 0.021
    
    # 5. 信息有用奖励 — 严格：只有相关>85%才降
    relevance_bonus = max(0.0, score.relevance - 0.85) * 0.06  # 0 ~ 0.009
    
    # 6. 知识互换奖励 — 受话题衰退衰减
    knowledge_bonus = max(0.0, score.knowledge_exchange - 0.70) * 0.06 * topic_decay  # 衰减后 0 ~ 0.018
    
    # 7. 退出意图惩罚 — 客户明确说了要结束
    exit_penalty = _calc_exit_penalty(consecutive_exits)
    
    # 汇算
    delta = base_fatigue + repetition_penalty + exit_penalty - empathy_bonus - info_richness_bonus - relevance_bonus - knowledge_bonus
    
    new_frustration = min(1.0, max(0.0, current_frustration + delta))
    
    detail = {
        "frustration_before": round(current_frustration, 3),
        "frustration_after": round(new_frustration, 3),
        "delta": round(delta, 4),
        "base_fatigue": round(base_fatigue, 4),
        "repetition_penalty": round(repetition_penalty, 4),
        "exit_penalty": round(exit_penalty, 4),
        "topic_decay": round(topic_decay, 2),
        "empathy_bonus": -round(empathy_bonus, 4),
        "info_richness_bonus": -round(info_richness_bonus, 4),
        "relevance_bonus": -round(relevance_bonus, 4),
        "knowledge_bonus": -round(knowledge_bonus, 4),
    }
    
    return new_frustration, detail


def get_frustration_threshold(persona: dict) -> float:
    """获取客户的厌烦阈值。
    
    耐心越高，阈值越高，越能忍。
    """
    patience = persona.get("patience", 0.6)
    return 0.45 + patience * 0.40  # 0.65~0.85


def decide_termination_by_frustration(
    frustration: float,
    persona: dict,
    turn_num: int,
) -> tuple[bool, str]:
    """根据厌烦度判断是否终止对话。
    
    Returns:
        (should_terminate, reason)
    """
    # 前 MIN_FORCED_TURNS 轮强制继续
    if turn_num < MIN_FORCED_TURNS:
        return False, ""
    
    threshold = get_frustration_threshold(persona)
    
    if frustration >= threshold:
        if frustration >= 0.95:
            reason = "烦死了，不想再聊了"
        elif frustration >= threshold + 0.10:
            reason = "聊得差不多了，没啥可说的了"
        else:
            reason = "该问的都问了，该走了"
        return True, reason
    
    return False, ""


# ============================================================
# 最终客户评价
# ============================================================

def generate_final_evaluation(
    persona: dict,
    conversation_log: list[dict],
    scores: list[TurnScore],
    termination_reason: str,
) -> str:
    """生成客户视角的最终评价。"""
    
    # 压缩对话摘要
    summary_lines = []
    for t in conversation_log:
        summary_lines.append(f"客户: {t['user'][:80]}")
        summary_lines.append(f"经理: {t['assistant'][:120]}")
    summary = "\n".join(summary_lines[-12:])  # 最近6轮
    
    avg_scores = {
        "综合": sum(s.overall for s in scores) / len(scores) if scores else 0,
        "陪伴感": sum(s.empathy for s in scores) / len(scores) if scores else 0,
        "信息丰度": sum(s.info_richness for s in scores) / len(scores) if scores else 0,
        "理解度": sum(s.relevance for s in scores) / len(scores) if scores else 0,
        "专业度": sum(s.professionalism for s in scores) / len(scores) if scores else 0,
        "知识互换": sum(s.knowledge_exchange for s in scores) / len(scores) if scores else 0,
    }
    
    eval_prompt = f"""你现在是{persona['name']}，刚跟微众银行的客户经理聊完贷款。
对话轮数：{len(conversation_log)} 轮
结束原因：{termination_reason}
系统评分：{json.dumps(avg_scores, ensure_ascii=False)}

最近对话：
{summary}

请以老王的身份，写一段100-200字的评价，回答：
1. 这个客户经理靠谱不？值不值得聊？
2. 他懂不懂餐饮生意？
3. 会不会再找他？
4. 有啥不满意的地方？

用老王的口语风格（俺/啥/呗），像在跟朋友说这个经历。"""
    
    evaluation = deepseek_chat(
        [{"role": "user", "content": eval_prompt}],
        temperature=0.9, max_tokens=300,
    )
    return evaluation or "（评价生成失败）"


# ============================================================
# 对话记忆管理
# ============================================================

def load_memory(persona_id: str) -> dict:
    path = MEMORY_DIR / f"{persona_id}.json"
    if path.exists():
        return json.loads(path.read_text("utf-8"))
    return {
        "persona_id": persona_id,
        "conversations": [],
        "facts_learned": {},
        "pain_points": [],
        "trust_level": 0.5,
        "satisfaction": 0.5,
    }


def save_memory(persona_id: str, memory: dict) -> None:
    path = MEMORY_DIR / f"{persona_id}.json"
    path.write_text(json.dumps(memory, ensure_ascii=False, indent=2), "utf-8")


# ============================================================
# 下一轮消息生成
# ============================================================

INFO_GATE_THRESHOLD = 0.70  # 信息丰度低于此值时，客户不会说"那就办吧"

def _build_next_message_prompt(
    persona: dict,
    avg_info_richness: float,
    turn_num: int,
    deepseek_history: list,
) -> str:
    """根据当前信息采集进度和轮数，动态调整客户行为指令。
    
    核心逻辑：信息不足时，客户不仅要继续聊，还要主动引导 Agent 追问。
    """
    name = persona['name']
    
    # 信息充足：正常运行，可以推进
    if avg_info_richness >= INFO_GATE_THRESHOLD:
        return f"""基于刚才客户经理的回复，你现在作为{name}，接下来想说什么？

记住你的性格：口语化、爱跑题、数字说不清。自然回应，不要刻意迎合。
只输出你要说的话，20-100字。"""

    # 不足+轮数已多：给最后一次"你还想了解什么"机会后自然终止
    if turn_num >= 18:
        return f"""基于刚才客户经理的回复，你现在作为{name}，接下来想说什么？

记住你的性格：口语化、爱跑题、数字说不清。
⚠️ 重要：不要主动说"那就办吧""教我怎么操作""帮我申请"等推进流程的话。
如果客户经理想推进流程，你说"先不急，你再问问我别的吧"或"还有啥要了解的？"
只输出你要说的话，20-100字。"""
    
    # 信息不足：阻止推进
    return f"""基于刚才客户经理的回复，你现在作为{name}，接下来想说什么？

记住你的性格：口语化、爱跑题、数字说不清。
⚠️ 重要：严格禁止说"那就办吧""教我怎么操作""帮我申请""利息怎么算"。
如果客户经理想教你操作或推进流程，你要说"还早呢，你再问问我的情况呗"或"不急，你了解清楚再说"。
你还有很多事情想让对方了解，继续自然地聊。
只输出你要说的话，20-100字。"""


# ============================================================
# 主模拟流程
# ============================================================

def run_simulation(
    persona_key: str = "laowang",
    max_turns: int = MAX_TURNS_DEFAULT,
    verbose: bool = True,
) -> dict:
    """运行完整模拟对话。客户自主决定何时终止。"""
    persona = PERSONAS[persona_key]
    memory = load_memory(persona["id"])
    
    deepseek_history: list[dict[str, str]] = [
        {"role": "system", "content": persona["persona_prompt"]},
    ]
    
    client = WeWalletClient()
    
    if verbose:
        print(f"\n{'='*60}")
        print(f"🤖 用户模拟器启动 — {persona['name']}（{persona['enterprise_name']}）")
        print(f"   耐心度={persona.get('patience',0.6):.0%} 礼貌度={persona.get('politeness',0.7):.0%}")
        print(f"{'='*60}")
    
    # Step 1: 登录
    if verbose:
        print("[1/5] 登录...")
    if not client.login(persona["phone"], persona["password"]):
        return {"error": "登录失败"}
    
    # Step 2: 创建/复用企业（每次跑生成唯一企业名，杜绝跨会话污染）
    if verbose:
        print("[2/5] 创建/复用企业...")
    import uuid
    unique_suffix = uuid.uuid4().hex[:6]
    unique_name = f"{persona['enterprise_name']}_{unique_suffix}"
    if not client.create_enterprise(unique_name, persona.get("enterprise_credit_code", "")):
        return {"error": "创建企业失败"}
    
    # Step 3: 重置对话 & 清空 agent 记忆（严格信息隔离）
    client.reset_conversation()
    client.clear_agent_memory()  # 清除跨会话记忆，确保从零开始
    # 二次确认：确保没有任何残留消息
    existing = client.get_messages()
    if existing:
        if verbose:
            print(f"  ⚠️ 清除 {len(existing)} 条旧消息")
        client.reset_conversation()
    
    if verbose:
        print(f"[3/5] 对话就绪（最多 {max_turns} 轮，客户自主决定终止）...\n")
    
    # Step 4: 多轮对话
    conversation_log: list[dict] = []
    scores: list[TurnScore] = []
    running_satisfaction = 0.5
    
    # 厌烦度模型
    frustration = 0.0
    frustration_log: list[dict] = []
    frustration_threshold = get_frustration_threshold(persona)
    consecutive_exits = 0  # 连续退出信号计数器
    topic_stickiness = 0   # 同话题重复轮数（兴趣锚点衰退）
    
    import random
    first_message = random.choice(persona["initial_message_pool"])
    current_message = first_message
    terminated = False
    termination_reason = ""
    actual_turns = 0
    
    if verbose:
        print(f"   厌烦阈值={frustration_threshold:.0%} | 最低{MIN_FORCED_TURNS}轮强制继续")
    
    for turn_num in range(1, max_turns + 1):
        actual_turns = turn_num
        
        if verbose:
            print(f"\n--- 第 {turn_num} 轮 ---")
            print(f"👤 {persona['name']}: {current_message}")
        
        # 合法可观察信号（真实系统也能获取，不含策略指导）
        full_name = persona.get('full_name', '')
        customer_name = f"{full_name[0]}老板" if full_name else "老板"
        
        # 发送到 wewallet（附带客户名称和厌烦度——都是可观察信号）
        resp = client.send_message(current_message, frustration, customer_name=customer_name)
        
        if "error" in resp:
            assistant_reply = f"[错误] {resp['error']}"
            if verbose:
                print(f"  ⚠️ API 错误: {resp['error']}")
        else:
            messages = resp.get("messages", [])
            assistant_msgs = [m for m in messages if m.get("role") == "assistant"]
            if assistant_msgs:
                last_assistant = assistant_msgs[-1]
                assistant_reply = last_assistant.get("content", "")
                assistant_reply = re.sub(r"<thinking>.*?</thinking>", "", assistant_reply, flags=re.DOTALL).strip()
            else:
                assistant_reply = "[无回复]"
        
        if verbose:
            print(f"🤖 客户经理: {assistant_reply[:200]}{'...' if len(assistant_reply) > 200 else ''}")
        
        # 记录
        turn_log = {
            "turn": turn_num,
            "user": current_message,
            "assistant": assistant_reply,
            "timestamp": time.time(),
        }
        conversation_log.append(turn_log)
        
        # 更新 DeepSeek 历史（模拟用户记忆）
        deepseek_history.append({"role": "user", "content": f"客户经理：{assistant_reply}"})
        
        # 评估
        history_text = "\n".join(
            f"客户: {t['user']}\n客户经理: {t['assistant']}"
            for t in conversation_log[-5:]
        )
        score = evaluate_turn(turn_num, current_message, assistant_reply, history_text, persona["name"])
        scores.append(score)
        
        # 滚动满意度
        running_satisfaction = running_satisfaction * 0.7 + score.overall * 0.3
        
        # 更新厌烦度
        recent_assistant = [
            t["assistant"] for t in conversation_log[-4:]
            if t.get("assistant") and not t["assistant"].startswith("[")
        ]
        
        # 退出意图追踪
        if _detect_exit_intent(current_message):
            consecutive_exits += 1
        else:
            consecutive_exits = 0
        
        # 话题黏性追踪 — 同一兴趣锚点重复出现则累积
        anchor_count = _count_anchor_keywords(assistant_reply)
        recent_anchor_count = sum(
            _count_anchor_keywords(t["assistant"])
            for t in conversation_log[-3:]
            if t.get("assistant") and not t["assistant"].startswith("[")
        )
        if anchor_count >= 1 and recent_anchor_count >= 1:
            topic_stickiness += 1  # 同一话题在延续
        elif anchor_count == 0:
            topic_stickiness = 0   # 话题切换，重置
        # else: anchor_count>=1 but recent=0 → 新兴趣锚点出现，保持0（新话题首次）       
        
        frustration, fr_detail = update_frustration(
            persona, score, assistant_reply, recent_assistant, frustration,
            consecutive_exits=consecutive_exits,
            topic_stickiness=topic_stickiness,
        )
        frustration_log.append({"turn": turn_num, **fr_detail})
        
        if verbose:
            status = "😊" if running_satisfaction > 0.7 else "😐" if running_satisfaction > 0.4 else "😤"
            fr_emoji = "😌" if frustration < 0.3 else "😐" if frustration < 0.6 else "😤"
            exit_info = f" ⚠️退出x{consecutive_exits}" if consecutive_exits > 0 else ""
            topic_info = f" 🔁同话题x{topic_stickiness}" if topic_stickiness >= 2 else ""
            print(f"  📊 评分: emp={score.empathy:.0%} info={score.info_richness:.0%} "
                  f"rel={score.relevance:.0%} prof={score.professionalism:.0%} "
                  f"kx={score.knowledge_exchange:.0%} | 满意 {status} {running_satisfaction:.0%}"
                  f" | 厌烦 {fr_emoji} {frustration:.0%}/{frustration_threshold:.0%}{exit_info}{topic_info}")
        
        # 厌烦度决定：终止？
        should_terminate, reason = decide_termination_by_frustration(
            frustration, persona, turn_num,
        )
        if should_terminate:
            terminated = True
            termination_reason = reason
            if verbose:
                print(f"\n  🛑 厌烦度 {frustration:.0%} ≥ 阈值 {frustration_threshold:.0%}，客户终止: {termination_reason}")
            break
        
        # 模拟真实阅读+思考节奏（客户看完回复、想一想要说什么）
        # 满意→慢慢想，不满→秒回，中性→正常节奏
        if running_satisfaction > 0.7:
            read_delay = random.uniform(2.0, 4.0)   # 心情好，认真思考
        elif running_satisfaction < 0.4:
            read_delay = random.uniform(0.5, 1.5)   # 不高兴，秒回/懒得想
        else:
            read_delay = random.uniform(1.5, 3.5)   # 正常
        if verbose:
            print(f"  ⏳ 客户阅读思考中... ({read_delay:.1f}s)")
        time.sleep(read_delay)
        
        # 计算当前信息采集进度（基于平均 info_richness 分）
        avg_info = (sum(s.info_richness for s in scores) / len(scores)) if scores else 0.0
        
        # 生成下一轮消息（信息门槛：不满足时不触发"那就办吧"）
        next_prompt = _build_next_message_prompt(persona, avg_info, turn_num, deepseek_history)
        next_msg = deepseek_chat(
            deepseek_history + [{"role": "user", "content": next_prompt}],
            temperature=0.9, max_tokens=200,
        )
        current_message = next_msg if next_msg else "嗯，那具体怎么弄呢？"
        deepseek_history.append({"role": "assistant", "content": current_message})
    
    # Step 5: 生成客户评价 & 汇总
    if verbose:
        print(f"\n[4/5] 生成客户评价...")
    
    customer_eval = generate_final_evaluation(
        persona, conversation_log, scores, termination_reason,
    )
    
    avg_scores = {
        "relevance": sum(s.relevance for s in scores) / len(scores) if scores else 0,
        "empathy": sum(s.empathy for s in scores) / len(scores) if scores else 0,
        "info_richness": sum(s.info_richness for s in scores) / len(scores) if scores else 0,
        "professionalism": sum(s.professionalism for s in scores) / len(scores) if scores else 0,
        "knowledge_exchange": sum(s.knowledge_exchange for s in scores) / len(scores) if scores else 0,
        "overall": sum(s.overall for s in scores) / len(scores) if scores else 0,
    }
    
    # 更新长期记忆
    memory["conversations"].append({
        "timestamp": time.time(),
        "turns": actual_turns,
        "terminated": terminated,
        "termination_reason": termination_reason,
        "scores": avg_scores,
        "customer_evaluation": customer_eval,
    })
    memory["satisfaction"] = avg_scores["overall"]
    save_memory(persona["id"], memory)
    
    # 保存日志
    log_path = LOG_DIR / f"{persona_key}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    log_data = {
        "persona": persona_key,
        "persona_name": persona["name"],
        "turns": actual_turns,
        "max_turns": max_turns,
        "terminated": terminated,
        "termination_reason": termination_reason,
        "final_frustration": frustration,
        "frustration_threshold": frustration_threshold,
        "frustration_log": frustration_log,
        "avg_scores": avg_scores,
        "customer_evaluation": customer_eval,
        "conversation": conversation_log,
        "per_turn_scores": [
            {
                "turn": s.turn,
                "relevance": s.relevance,
                "empathy": s.empathy,
                "info_richness": s.info_richness,
                "professionalism": s.professionalism,
                "knowledge_exchange": s.knowledge_exchange,
                "overall": s.overall,
                "notes": s.notes,
            }
            for s in scores
        ],
    }
    log_path.write_text(json.dumps(log_data, ensure_ascii=False, indent=2), "utf-8")
    
    # 保存清洁版纯文本对话记录（人类可读）
    txt_path = LOG_DIR / f"{persona_key}_{time.strftime('%Y%m%d_%H%M%S')}.txt"
    txt_lines = []
    txt_lines.append(f"{'='*60}")
    txt_lines.append(f"客户: {persona['name']} | 轮数: {actual_turns} | 终止: {termination_reason}")
    txt_lines.append(f"综合: {avg_scores['overall']:.0%} | 陪伴感: {avg_scores['empathy']:.0%} | 信息丰度: {avg_scores['info_richness']:.0%} | 知识互换: {avg_scores['knowledge_exchange']:.0%}")
    txt_lines.append(f"{'='*60}\n")
    for t in conversation_log:
        txt_lines.append(f"--- 第 {t['turn']} 轮 ---")
        txt_lines.append(f"👤 {persona['name']}: {t['user']}")
        txt_lines.append(f"🤖 客户经理: {t['assistant']}")
        txt_lines.append("")
    txt_lines.append(f"{'='*60}")
    txt_lines.append(f"📝 客户评价: {customer_eval}")
    txt_lines.append(f"{'='*60}")
    txt_path.write_text("\n".join(txt_lines), "utf-8")
    
    report = {
        "persona": persona["name"],
        "turns": actual_turns,
        "terminated": terminated,
        "termination_reason": termination_reason,
        "avg_scores": avg_scores,
        "customer_evaluation": customer_eval,
        "log_path": str(log_path),
        "txt_path": str(txt_path),
        "memory_path": str(MEMORY_DIR / f"{persona['id']}.json"),
    }
    
    if verbose:
        memory_path = MEMORY_DIR / f"{persona['id']}.json"
        print(f"\n[5/5] 完成！")
        print(f"\n{'='*60}")
        print(f"📊 模拟结果 — {persona['name']}")
        print(f"  轮数:     {actual_turns}（{'厌烦度达阈值' if terminated else '达到上限'}）")
        if termination_reason:
            print(f"  终止原因: {termination_reason}")
        print(f"  最终厌烦: {frustration:.0%} / 阈值 {frustration_threshold:.0%}")
        print(f"  综合评分: {avg_scores['overall']:.0%}")
        print(f"  陪伴感:   {avg_scores['empathy']:.0%}")
        print(f"  信息丰度: {avg_scores['info_richness']:.0%}")
        print(f"  理解度:   {avg_scores['relevance']:.0%}")
        print(f"  专业度:   {avg_scores['professionalism']:.0%}")
        print(f"  知识互换: {avg_scores['knowledge_exchange']:.0%}")
        print(f"\n  📝 客户评价:")
        print(f"  {customer_eval}")
        print(f"\\n  日志(JSON): {log_path}")
        print(f"  日志(TXT):  {txt_path}")
        print(f"  记忆: {memory_path}")
        print(f"{'='*60}")
    
    # 严格信息隔离：退出登录，清除会话
    try:
        client._request("POST", "/api/auth/logout")
        client.cookies.clear()
    except Exception:
        pass
    # 还原被清空的全局记忆文件，避免污染 git 跟踪内容
    client.restore_agent_memory()

    return report


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="用户模拟器 — RL训练数据生成")
    parser.add_argument("--persona", default="laowang", choices=list(PERSONAS.keys()),
                        help="选择客户画像")
    parser.add_argument("--max-turns", type=int, default=MAX_TURNS_DEFAULT,
                        help="最大对话轮数")
    parser.add_argument("--quiet", action="store_true",
                        help="减少输出")
    args = parser.parse_args()

    run_simulation(
        persona_key=args.persona,
        max_turns=args.max_turns,
        verbose=not args.quiet,
    )

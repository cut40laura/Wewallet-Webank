"""端到端实时语音的 WebSocket 中继（豆包 openspeech 实时对话 / StepFun stepaudio）。

为什么需要中继：浏览器原生 WebSocket **不能自定义请求头**，没法带鉴权；而且凭证绝不能
下发到前端。所以这里起一个本地 asyncio WS 服务：

    浏览器  ⇄  本中继（注入凭证 + 协议翻译）  ⇄  上游实时语音 wss

前端和中继之间用一套**抽象事件协议**（input_audio_buffer.append / response.audio.delta /
response.audio_transcript.delta / vision.frame …），中继负责把它翻成上游各自的协议，所以
切换 provider 前端基本不用动。按 ``VOICECALL_REALTIME_PROVIDER`` 选上游：

  - doubao（默认）：字节 openspeech「实时对话」(volc.speech.dialog)，**二进制帧协议**，
    ASR+LLM+TTS 一体。编解码在 voicecall_doubao.py。
  - stepfun：stepaudio-2.5-realtime，OpenAI-realtime JSON 协议。

**视觉桥接**：实时语音模型看不了图。每轮客户一开口，前端就静默截一帧用 ``vision.frame`` 事件
发上来（无手动"看材料"按钮），中继截下不转发，改调多模态视觉（voicecall.describe_frame，默认
doubao-1.6-vision）把画面关键信息 + 反欺诈核验提示描述出来，再以一条 ``[画面]`` 开头的文字
**静默**注入上游会话：吞掉本轮播报、只更新小微的"视觉/核验记忆"，不打断、不每轮复述画面；她在
对话相关时（对方举材料、问你看到什么、画面与口述对不上）自然地结合画面回应。

随 server.py 同进程、独立线程、独立端口运行（见 ``start_relay_thread``）。
依赖 ``websockets``。
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
import secrets
import threading
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import websockets
from websockets.asyncio.client import connect as ws_connect
from websockets.asyncio.server import serve as ws_serve

import voicecall_doubao as dbq
from config import (
    DOUBAO_REALTIME_ACCESS_KEY,
    DOUBAO_REALTIME_API_KEY,
    DOUBAO_REALTIME_APP_ID,
    DOUBAO_REALTIME_APP_KEY,
    DOUBAO_REALTIME_ASR_TWOPASS,
    DOUBAO_REALTIME_END_WINDOW_MS,
    DOUBAO_REALTIME_MODEL_VERSION,
    DOUBAO_REALTIME_RESOURCE_ID,
    DOUBAO_REALTIME_TTS_SPEAKER,
    DOUBAO_REALTIME_WS_URL,
    STEP_API_KEY,
    STEP_REALTIME_WSS,
    VOICECALL_REALTIME_PROVIDER,
    VOICECALL_RELAY_HOST,
    VOICECALL_RELAY_PORT,
    VOICECALL_RELAY_TOKEN,
    realtime_voice_ready,
)
from voicecall import (
    REALTIME_INSTRUCTIONS,
    check_contradictions,
    describe_frame,
    realtime_session_config,
    verify_call_token,
)
import video_calls


async def _load_call_memory(enterprise_id: str) -> str:
    """接通时构建一次"开场记忆"（画像+近期对话）。

    与主聊天共享同一份记忆，让实时通话的小微一接通就认得这位客户。DB 读 + 画像
    蒸馏丢线程池跑，避免阻塞事件循环；只在会话建立时跑一次，不在每轮音频环里，
    故不影响实时延迟。任何异常都吞掉、返回空串（退化成无记忆通话，不拖垮通话）。
    """
    if not enterprise_id:
        return ""
    try:
        from profile_service import build_call_memory_context
        from enterprise import load_messages

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: build_call_memory_context(enterprise_id, load_messages(enterprise_id)),
        )
    except Exception as exc:
        _dbg(f"记忆加载失败（退化为无记忆通话）：{exc!r}")
        return ""


# [DBG-vc] 临时诊断：把豆包事件号翻成可读名，定位"问我长什么样就卡住"。用完整体删除。
_DBG_EVENT_NAMES = {
    50: "CONN_STARTED", 51: "CONN_FAILED", 52: "CONN_FINISHED",
    150: "SESSION_STARTED", 151: "SESSION_CANCELED", 152: "SESSION_FINISHED",
    153: "SESSION_FAILED", 154: "USAGE",
    350: "TTS_SENT_START", 351: "TTS_SENT_END", 352: "TTS_AUDIO", 359: "TTS_ENDED",
    364: "TTS_SUBTITLE", 450: "ASR_INFO", 451: "ASR_RESPONSE", 459: "ASR_ENDED",
    550: "CHAT_RESPONSE", 553: "CHAT_QUERY_CONFIRMED", 559: "CHAT_ENDED",
    599: "DIALOG_COMMON_ERROR",
}


def _dbg(msg: str) -> None:
    print(f"[DBG-vc] {time.monotonic():8.2f} {msg}", flush=True)


# 对小微贷申请人"自称在经营场所"而言偏可疑的场景类型（与 _VISION_STRUCTURED_PROMPT 的
# place_type 取值对齐）：在这些场景下，画面与"开厂/店面/营业"的口述更可能对不上。
_NON_BUSINESS_SCENES = {"居住/家", "车内"}


def _caption_with_scene(caption: str, observation: dict[str, Any] | None) -> str:
    """把**结构化硬事实**（有没有人/几个人、场景类型）并进 [画面] 旁白，让小微每轮都拿到
    可靠的客观依据——而不是只给一句可能没提到人的 caption。这是"以画面为准、不轻信用户"
    的前提：用户声称"我这有5个人"但画面没人时，小微据此才能纠正。

    保留 "[画面]" 前缀（人设约定当亲眼所见、且不读出方括号）。看不清/未知的字段不写。
    """
    obs = observation or {}
    bits: list[str] = []

    # 人物：最容易被用户口头"注水"的事实，明确写出有没有人、几个人；有外观描述就带上
    # （让小微能答"你看我长什么样"，而不只是描述环境）。
    present = obs.get("person_present")
    count = obs.get("person_count")
    desc = str(obs.get("person_desc") or "").strip()
    has_count = isinstance(count, (int, float)) and not isinstance(count, bool)
    if present is True or (has_count and count > 0):
        n = int(count) if has_count and count > 0 else None
        head = f"画面里可见约{n}人" if n else "画面里可见人物"
        bits.append(f"{head}（{desc}）" if desc else head)
    elif present is False or (has_count and count == 0):
        bits.append("画面里没看到人")

    pt = str(obs.get("place_type") or "").strip()
    if pt and pt != "看不清":
        bits.append(f"场景看着像{pt}")

    prefix = "（" + "；".join(bits) + "）" if bits else " "
    return "[画面]" + prefix + caption


def _verify_hint(observation: dict[str, Any] | None) -> str:
    """据结构化视觉信号，生成给小微的**静默核验提示**（反欺诈交叉核验）。

    以"（核验提示…）"开头：人设里约定这类内容是内部指引，绝不读出来，按它去做。
    没有可操作信号则返回 ""（不注入，省 token、不刷历史）。
    """
    if not observation:
        return ""
    bits: list[str] = []
    docs = [str(d) for d in observation.get("visible_documents") or [] if str(d).strip()]
    if docs:
        bits.append(
            "对方出示了" + "、".join(docs[:3]) +
            "，请让对方对准镜头并【口头念出上面的关键信息】（名称/日期/金额等），用念的和看到的互相核对，别只看不问"
        )
    if observation.get("looking_off_screen"):
        bits.append("对方似乎频繁看别处或像在照稿念，自然地多问一两句开放问题印证，别点破")
    # 画面 vs 口述场景：场景偏居家/车内时，和对方自称的经营情况对一下。明显对不上要客观直指。
    place_type = str(observation.get("place_type") or "").strip()
    if place_type in _NON_BUSINESS_SCENES:
        bits.append(
            f"画面场景像{place_type}，不太像营业/经营场所——若对方自称在开厂/店面经营、生意红火等"
            "明显对不上，**客观、直接地指出**这个不符并当场要求核实（如'我看您这边像是在家里，跟您说的"
            "在店面经营对不上，麻烦您说说现在什么情况，或把经营场所拍给我看下'），别绕弯子别给模糊台阶；"
            "但别用'骗贷/造假/欺诈'这类定性词，口径对上或给出证据才往下推进"
        )
    anomalies = [str(a) for a in observation.get("anomalies") or [] if str(a).strip()]
    if anomalies:
        bits.append("画面有疑点（" + "、".join(anomalies[:3]) + "），用温和确认口径的方式核对，别说破")
    if not bits:
        return ""
    return "（核验提示，仅你自己看、绝不要读出来）" + "；".join(bits) + "。"


# ══════════════════════════════════════════════════════════════════════════
# 上游 1：豆包 openspeech 实时对话（二进制帧协议）
# ══════════════════════════════════════════════════════════════════════════
class _DoubaoBridge:
    """一条浏览器⇄豆包连接的共享状态。

    suppress_until：静默喂画面触发的"吞复述"兜底截止时刻（monotonic）。每轮看画面都会以
    ChatTextQuery 注入画面文字、触发一次回复，但我们不想让她每轮都开口复述画面，于是吞掉这条
    复述的文字/音频，只让豆包把画面（含人物外观、场景、证件）收进上下文。**按复述的生命周期吞**：
    flush 时置位，复述那轮 TTS_ENDED 解除；suppress_until 只是兜底时限（防复述轮丢帧卡死）。
    用户一开口（ASR）也立即解除，避免吞真实回答。她要"答画面里的东西"（你长什么样/我手里这是
    什么）时，靠的是**音频轮回复直接用上下文里的画面信息作答**（那条不吞、正常播）。
    """

    def __init__(self, browser: Any, upstream: Any, session_id: str, enterprise_id: str = "") -> None:
        self.browser = browser
        self.upstream = upstream
        self.session_id = session_id
        self.enterprise_id = enterprise_id  # 该通话所属企业（从令牌解出），用于注入共享记忆
        self.session_started = False
        self.ai_speaking = False
        self.suppress_until = 0.0
        self.last_vision_desc = ""
        self.last_vision_at = 0.0  # 上次注入画面的时刻（monotonic），用于"静态场景也定期刷新事实"
        self.vision_in_flight = False  # 看画面任务在途（单飞闸门，防并发重复跑 describe_frame）
        self.pending_vision = None  # 待注入的 auto 画面文字：只在空闲时发，避免吞窗口盖到她真实回答
        # 用户当前是否在"一段语音"中：一句话有几十个 interim ASR 帧，只在起点动作一次
        # （发 speech_started + 打断），整段不重复，避免把小微切碎。ASR_ENDED 时复位。
        self.user_turn_active = False
        # 用户刚说完、小微的回复还没播完（ASR_ENDED → TTS_ENDED 之间）。这段"等回复"间隙
        # ai_speaking/user_turn_active 都是 False、看似空闲，实则真实回复 ~1s 后就到——此时
        # flush 画面注入设的 suppress 窗会把真实回复整条吞掉（"突然不回复，再说一句才好"的根因）。
        # 故 flush 的空闲判定必须把它也算上。下次用户开口（ASR 起点）自然复位，不会卡死。
        self.awaiting_reply = False
        # 打断后丢弃被打断旧轮的残留帧：发 CLIENT_INTERRUPT 到豆包真停下来之间，旧轮的
        # 文本/字幕/音频帧还会陆续到达，不丢会和用户的话、和新回复交替播出（断断续续+冲突）。
        # 从发出打断起置位，ASR_ENDED（用户说完，新回复在它之后才来）清除。
        self.discard_old_turn = False
        # ── 实时矛盾检测（口述 vs 档案，确定性旁路）状态 ──
        # 接通时把开场记忆原文也留一份当"已知档案"基线；每句 ASR 定稿触发一次后台比对
        # （线程池跑、单飞 + 只保最新待查，绝不卡音频转发），命中则前端弹警示块 +
        # 静默注入核对提示 + 登记到挂断风控。
        self.memory_text = ""
        self.current_utterance = ""  # 当前这段语音的 ASR 累积全文（每帧带全量，覆盖即可）
        self.recent_turns: list[tuple[str, str]] = []  # 最近几轮 (角色, 文本)，比对时当上下文
        self.ai_turn_text = ""  # 本轮 AI 字幕累积（进 recent_turns 用）
        self.contradiction_in_flight = False
        self.pending_check_utterance = ""  # 在途时新句子只保最新一条，不排队不并发
        self.contradiction_keys: set[str] = set()  # field|known 去重（整通范围）
        self.pending_risk_hint = ""  # 待静默注入的核对提示（与画面注入共用 flush 通道）
        self.alerted_anomalies: set[str] = set()  # 已弹过的画面疑点指纹（整通范围）


# 吞画面复述的【兜底】时限：正常解除靠"复述那轮 TTS_ENDED"（生命周期吞），这个时限只防
# 复述轮丢帧/没出 TTS 时卡死。历史教训：之前是写死 3s 的时间窗，盖不满偏长的复述（LLM ~1s
# 后才开始出 TTS，整条流完常要 4~8s），3s 后泄漏的后半段紧跟在真实回复尾音后播出——掐了头
# 的半截画面描述、语气突变平铺（"回复结尾语音冲突/语气突变"的根因）。现在窗口敢放宽到 20s，
# 是因为 flush 只在真空闲时发（见 awaiting_reply），窗口内不会再有真实回复可误吞。
_SUPPRESS_FALLBACK_S = 20.0
# 静态场景也定期刷新画面事实：即便事实没变，超过这个间隔也重注一次，避免"无人/人数"被
# 对话截断挤出小微的活跃上下文，导致用户口头注水时她手里没有反驳依据。
_VISION_REFRESH_S = 12.0


def _fresh_anomalies(bridge: Any, observation: dict[str, Any] | None) -> list[str]:
    """从一帧观察里挑出**这通还没弹过**的画面疑点，供前端弹警示块。

    视觉模型每帧重新生成 anomaly 文案，措辞会微抖（"相关经营场所"vs"相关场所"），
    逐字去重失效、同一疑点反复弹。指纹取归一化后的前 12 字：措辞抖动几乎都在尾部，
    头部（"场景为宿舍非小微企业…"）稳定。整通范围去重。
    """
    if not isinstance(observation, dict):
        return []
    fresh: list[str] = []
    for raw in observation.get("anomalies") or []:
        text = str(raw).strip()
        fingerprint = re.sub(r"[\W_]+", "", text)[:12]
        if text and fingerprint and fingerprint not in bridge.alerted_anomalies:
            bridge.alerted_anomalies.add(fingerprint)
            fresh.append(text)
    return fresh


async def _notify_visual_risks(bridge: Any, observation: dict[str, Any] | None) -> None:
    """新出现的画面疑点推给前端弹警示块（risk.visual）；没新的不发，绝不抛错。"""
    fresh = _fresh_anomalies(bridge, observation)
    if not fresh:
        return
    try:
        await bridge.browser.send(json.dumps({"type": "risk.visual", "items": fresh}))
    except Exception:
        pass


async def _flush_pending_vision(bridge: _DoubaoBridge) -> None:
    """空闲时把待注入的画面文字发给豆包（静默：吞掉它触发的复述）。

    为什么要"等空闲"：注入画面是以 ChatTextQuery 触发一次（被吞掉的）回复，吞到这条复述的
    TTS_ENDED 为止。若在她正回答用户时注入，吞的就会是她的**真实回答**。
    所以只在 `不在播报 且 用户没在说 且 不在等回复` 时才发；不空闲就攒着，空闲了再 flush。

    画面（含人物外观/场景/证件）就这样静默进上下文；用户问"你长什么样""我手里这是什么"时，
    她的**音频轮回复直接用上下文作答**（那条不在吞窗内、正常播），无需对画面注入特殊放行。
    """
    if not bridge.pending_vision and not bridge.pending_risk_hint:
        return
    if bridge.ai_speaking or bridge.user_turn_active or bridge.awaiting_reply:
        return  # 不空闲（在播 / 用户在说 / 等回复间隙），先攒着
    # 画面与风控核对提示共用这条静默注入通道：合成一条 ChatTextQuery，一次吞一轮复述。
    parts = [p for p in (bridge.pending_vision, bridge.pending_risk_hint) if p]
    content = "\n".join(parts)
    bridge.pending_vision = None
    bridge.pending_risk_hint = ""
    # 吞掉这条触发的复述：到它的 TTS_ENDED 为止（生命周期吞），时限只是丢帧兜底。
    bridge.suppress_until = time.monotonic() + _SUPPRESS_FALLBACK_S
    _dbg(f"FLUSH 注入画面+设 suppress（至复述 TTS_ENDED，兜底 {_SUPPRESS_FALLBACK_S}s）| content={content[:60]!r}")
    await bridge.upstream.send(
        dbq.make_full_client_frame(dbq.EVENT_CHAT_TEXT_QUERY, {"content": content}, bridge.session_id))


async def _inject_vision_doubao(bridge: _DoubaoBridge, frame: str) -> None:
    """看画面：一帧 → 多模态结构化观察 → **静默**注入豆包会话（含反欺诈核验提示）。

    每轮你一开口前端就静默截一帧发上来（无手动"看材料"按钮）。注入始终静默：攒进 pending、
    等空闲再发，并吞掉这条触发的播报——只更新她的"视觉/核验记忆"，不打断、不每轮复述画面。
    反欺诈核验提示（_verify_hint）本就是"只给她自己看、适时自然去做"的内部指引，一并折叠进去。

    **跑在后台任务里**（见 _vision_task_doubao），describe_frame ~5s 阻塞调用不会卡住浏览器→
    豆包的音频转发（否则 ASR 延迟）。
    """
    loop = asyncio.get_running_loop()
    _t0 = time.monotonic()
    result = await loop.run_in_executor(None, describe_frame, frame)  # 阻塞 requests，丢线程池
    caption = str(result.get("caption") or "看不清。")
    observation = result.get("observation")
    _dbg(f"VISION describe_frame 耗时 {time.monotonic()-_t0:.1f}s caption={caption[:40]!r} obs={observation}")
    try:
        await bridge.browser.send(json.dumps({
            "type": "vision.described", "text": caption, "observation": observation,
        }))
    except Exception:
        pass
    # 尽调留痕：观察登记进进程内登记簿（纯内存 append），挂断时随转写一起落库。
    video_calls.note_observation(bridge.enterprise_id, observation)
    await _notify_visual_risks(bridge, observation)  # 新画面疑点→前端警示块（整通去重）
    base = _caption_with_scene(caption, observation)  # 含"有没有人/几个人/场景"硬事实
    hint = _verify_hint(observation)  # 反欺诈核验内部指引（绝不读出），有则折进静默注入
    content = base + ("\n" + hint if hint else "")

    # 事实没变且刚注过就跳过；超过刷新间隔即便没变也重注一次（保事实常新）。
    now = time.monotonic()
    if content == bridge.last_vision_desc and (now - bridge.last_vision_at) < _VISION_REFRESH_S:
        return
    bridge.last_vision_desc = content
    bridge.last_vision_at = now
    bridge.pending_vision = content  # 攒起来，等空闲（_flush_pending_vision）再发
    await _flush_pending_vision(bridge)


async def _vision_task_doubao(bridge: _DoubaoBridge, frame: str) -> None:
    """后台跑一次看画面，兜住异常、收尾复位单飞闸门（连接断了等都不该冒泡成未捕获任务异常）。"""
    try:
        await _inject_vision_doubao(bridge, frame)
    except Exception:
        pass
    finally:
        bridge.vision_in_flight = False


def _maybe_schedule_contradiction_check(bridge: _DoubaoBridge, utterance: str) -> None:
    """一句 ASR 定稿后调度一次"口述 vs 档案"比对（确定性旁路）。

    性能护栏：①没档案/短句（寒暄"嗯/好的"）直接跳过；②单飞——在途时新句子只
    覆盖"最新待查"，绝不并发、绝不排队堆积；③真正的网络比对丢线程池跑
    （check_contradictions 阻塞 requests），不碰音频转发协程。
    """
    utterance = (utterance or "").strip()
    # 阈值 4：拦下"嗯/好的/对对对"这类纯应答，但放过"我叫麦子"这种 4 字身份自报
    # （曾设 6 把它拦掉了，名字与档案不符就漏检）。
    if not bridge.memory_text or len(utterance) < 4:
        return
    if bridge.contradiction_in_flight:
        bridge.pending_check_utterance = utterance  # 只保最新，过时的不值得查
        return
    bridge.contradiction_in_flight = True
    asyncio.create_task(_contradiction_task_doubao(bridge, utterance))


async def _contradiction_task_doubao(bridge: _DoubaoBridge, utterance: str) -> None:
    """后台比对一次：命中 → 前端弹警示块 + 静默注入核对提示 + 登记进挂断风控。"""
    try:
        loop = asyncio.get_running_loop()
        recent = "\n".join(f"{role}：{text}" for role, text in bridge.recent_turns[-6:])
        items = await loop.run_in_executor(
            None, check_contradictions, bridge.memory_text, utterance, recent)
        for item in items:
            key = f"{item.get('field', '')}|{item.get('known', '')}"
            if key in bridge.contradiction_keys:
                continue  # 同一处出入整通只报一次，别轰炸
            bridge.contradiction_keys.add(key)
            _dbg(f"CONTRADICTION 命中 {item}")
            # ① 登记到挂断风控（与画面观察同一登记簿机制，挂断时合入风控判级+待核验点）。
            video_calls.note_contradiction(bridge.enterprise_id, item)
            # ② 通知前端在通话 UI 弹红色警示块。
            try:
                await bridge.browser.send(json.dumps({"type": "risk.contradiction", "item": item}))
            except Exception:
                pass
            # ③ 静默注入核对提示，引导小微接下来自然、不指控地当场核对。
            hint = (
                "（风控提示，仅你自己看、绝不要读出来也不要说'系统提示'：用户刚才的说法"
                f"与已知档案不符——{item.get('field') or '某项信息'}：用户说\"{item.get('stated', '')}\"，"
                f"但档案里是\"{item.get('known', '')}\"。你【必须在下一次回应里当场点出这处"
                "不一致并请用户确认，绝不顺着用户的新说法走、绝不改用新口径】（涉及姓名时"
                "更不要改口称呼）；口吻自然、给台阶但事实要摆出来"
                + (f"，例如：\"{item['nudge']}\"" if item.get("nudge") else "")
                + "。核清之前一律沿用档案口径。）"
            )
            bridge.pending_risk_hint = (
                bridge.pending_risk_hint + "\n" + hint if bridge.pending_risk_hint else hint)
        if items:
            await _flush_pending_vision(bridge)  # 空闲就立刻注入，不空闲攒着等 TTS_ENDED
    except Exception:
        pass
    finally:
        bridge.contradiction_in_flight = False
        # 在途期间又有新句子定稿：补查最新那条（递归只一层深，单飞闸门仍然有效）。
        pending, bridge.pending_check_utterance = bridge.pending_check_utterance, ""
        if pending:
            _maybe_schedule_contradiction_check(bridge, pending)


async def _pump_doubao_upstream(bridge: _DoubaoBridge) -> None:
    async for raw in bridge.upstream:
        if not isinstance(raw, (bytes, bytearray)):
            continue  # 豆包上游是二进制帧，文本忽略
        frame = dbq.decode_frame(bytes(raw))
        if frame is None:
            await bridge.browser.send(json.dumps({"type": "proxy.warning", "message": "收到无法解析的豆包帧。"}))
            continue

        # [DBG-vc] 事件流（跳过 TTS 音频帧 352 避免刷屏）
        if frame.event != dbq.EVENT_TTS_RESPONSE:
            _supp = max(0.0, bridge.suppress_until - time.monotonic())
            _dbg(f"up ev={_DBG_EVENT_NAMES.get(frame.event, frame.event)} "
                 f"suppress_left={_supp:.1f} ai_speaking={bridge.ai_speaking} "
                 f"pending={bool(bridge.pending_vision)} json={(frame.json or {})}")

        # 用户一开口就解除静默，避免把这轮真实回答也吞掉
        if frame.event == dbq.EVENT_ASR_RESPONSE:
            if bridge.suppress_until > time.monotonic():
                _dbg("  -> ASR_RESPONSE 清除 suppress")
            bridge.suppress_until = 0.0
            # 矛盾检测旁路：ASR 每帧带本段累积全文，覆盖记录即可（定稿在 ASR_ENDED）。
            _text = "".join(
                item.get("text", "") for item in ((frame.json or {}).get("results") or [])
                if isinstance(item, dict) and item.get("text"))
            if _text:
                bridge.current_utterance = _text

        suppressing = bridge.suppress_until > time.monotonic()
        if suppressing and frame.event in (dbq.EVENT_CHAT_RESPONSE, dbq.EVENT_TTS_SUBTITLE):
            _dbg(f"  -> 吞掉播报 ev={_DBG_EVENT_NAMES.get(frame.event)} json={(frame.json or {})}")
        if bridge.discard_old_turn and frame.event in (
            dbq.EVENT_CHAT_RESPONSE, dbq.EVENT_TTS_SUBTITLE, dbq.EVENT_TTS_RESPONSE,
        ):
            _dbg(f"  -> 丢弃被打断旧轮残留 ev={_DBG_EVENT_NAMES.get(frame.event)}")
        for payload in dbq.translate_frame(frame):
            if (suppressing or bridge.discard_old_turn) and payload.get("type") in (
                "response.text.delta", "response.audio.delta", "response.audio_transcript.delta",
            ):
                continue
            await bridge.browser.send(json.dumps(payload))
        # 【主解除点】复述那轮的 TTS_ENDED：生命周期吞到这里结束（上面的 20s 时限只是丢帧兜底）。
        # 不能用 ChatEnded——它早于音频，用它解除会让复述的音频漏出来。
        if suppressing and frame.event == dbq.EVENT_TTS_ENDED:
            bridge.suppress_until = 0.0

        # 跟踪 AI 是否在播报。【只认 TTS 生命周期】：CHAT_ENDED（文字生成完）比 TTS_ENDED
        # （音频播完）早 ~1.5s，若用 CHAT_ENDED 判"说完了"，flush 会在她尾音还没播完时设
        # suppress、把这条回复剩下的语音吞掉（"没说完就被吞"的根因）。故只在 TTS_ENDED 清。
        # 兜底：若某条回复无 TTS/丢了 TTS_ENDED 导致卡 True，下次用户开口会复位（见打断逻辑）。
        if frame.event in (dbq.EVENT_TTS_SENTENCE_START, dbq.EVENT_TTS_RESPONSE):
            if not bridge.discard_old_turn:  # 被打断旧轮的残留帧不算"在播报"
                bridge.ai_speaking = True
        elif frame.event == dbq.EVENT_TTS_ENDED:
            bridge.ai_speaking = False
            bridge.awaiting_reply = False  # 这轮回复播完，"等回复"间隙结束，可以安全 flush 画面了
            # 矛盾检测旁路：小微这轮说完，进上下文窗口（被吞的画面复述轮 ai_turn_text 为空，自然跳过）。
            if bridge.ai_turn_text:
                bridge.recent_turns.append(("经理", bridge.ai_turn_text))
                del bridge.recent_turns[:-8]
                bridge.ai_turn_text = ""

        # 矛盾检测旁路：累积小微本轮字幕当上下文（吞复述/丢旧轮的帧不算她对客户说的话）。
        if (frame.event == dbq.EVENT_TTS_SUBTITLE and not suppressing
                and not bridge.discard_old_turn and (frame.json or {}).get("text")):
            bridge.ai_turn_text += str(frame.json["text"])

        # 用户语音"起点"才动作一次：通知前端停播+截帧（speech_started），并在 AI 正说时打断她。
        # 整段语音的后续 interim 帧都跳过——否则几十个 interim 会把小微反复掐断。
        if frame.event == dbq.EVENT_ASR_RESPONSE:
            if not bridge.user_turn_active:
                bridge.user_turn_active = True
                bridge.awaiting_reply = False  # 兜底：上轮若无 TTS/丢了 TTS_ENDED，别让它卡死 flush
                await bridge.browser.send(json.dumps({"type": "input_audio_buffer.speech_started"}))
                if bridge.ai_speaking and bridge.session_started:
                    await bridge.upstream.send(
                        dbq.make_full_client_frame(dbq.EVENT_CLIENT_INTERRUPT, {}, bridge.session_id))
                    bridge.ai_speaking = False
                    bridge.discard_old_turn = True  # 打断生效前旧轮还会漏几帧，全部丢弃
        elif frame.event == dbq.EVENT_ASR_ENDED:
            bridge.user_turn_active = False  # 本段用户语音结束，下段重新允许起点动作
            bridge.awaiting_reply = True  # 真实回复马上要来，进入"等回复"间隙，禁 flush
            bridge.discard_old_turn = False  # 旧轮残留早已排干（打断在这句话开头），恢复转发新回复
            # 矛盾检测旁路：这句定稿了，进上下文窗口 + 调度一次后台比对（单飞、不卡音频）。
            utterance, bridge.current_utterance = bridge.current_utterance, ""
            if utterance:
                bridge.recent_turns.append(("用户", utterance))
                del bridge.recent_turns[:-8]
                _maybe_schedule_contradiction_check(bridge, utterance)

        # 只在 TTS_ENDED（她真说完、用户也没在说）flush 画面。【不在 CHAT_ENDED】：那时 TTS
        # 还在播，suppress 会切掉尾音。【也不在 ASR_ENDED】：用户刚说完、真实回复 ~1s 后就到，
        # 此时 flush 设的 suppress 窗会把整条真实回复吞掉（"突然不回复"的根因）。
        # vision 完成时自身也会 flush（同受 awaiting_reply 闸门约束），不漏。
        if frame.event == dbq.EVENT_TTS_ENDED:
            await _flush_pending_vision(bridge)

        if frame.event == dbq.EVENT_CONNECTION_STARTED:
            # 接通即注入"开场记忆"：把主聊天沉淀的客户档案+近期对话拼进人设，
            # 让小微一接通就认得这位客户。只在这里跑一次，不进每轮音频环。
            memory = await _load_call_memory(bridge.enterprise_id)
            system_role = REALTIME_INSTRUCTIONS
            if memory:
                system_role = f"{REALTIME_INSTRUCTIONS}\n\n{memory}"
                bridge.memory_text = memory  # 同一份记忆留作矛盾检测的"已知档案"基线
                _dbg(f"注入开场记忆 {len(memory)} 字（enterprise={bridge.enterprise_id}）")
            session_cfg = dbq.build_session_config(
                system_role,
                tts_speaker=DOUBAO_REALTIME_TTS_SPEAKER,
                model_version=DOUBAO_REALTIME_MODEL_VERSION,
                end_smooth_window_ms=DOUBAO_REALTIME_END_WINDOW_MS,
                asr_twopass=DOUBAO_REALTIME_ASR_TWOPASS,
            )
            await bridge.upstream.send(
                dbq.make_full_client_frame(dbq.EVENT_START_SESSION, session_cfg, bridge.session_id))
        elif frame.event == dbq.EVENT_SESSION_STARTED:
            bridge.session_started = True

        if dbq.is_failure_event(frame.event):
            _dbg(f"!! FAILURE event={_DBG_EVENT_NAMES.get(frame.event, frame.event)} "
                 f"code={frame.code} json={(frame.json or {})} -> 关闭浏览器连接")
            await bridge.browser.close(code=1011, reason="upstream session failed")
            return


async def _pump_doubao_browser(bridge: _DoubaoBridge) -> None:
    async for msg in bridge.browser:
        # 二进制：直接当上行音频帧（前端也可能走 base64，见下）
        if isinstance(msg, (bytes, bytearray)):
            if bridge.session_started:
                await bridge.upstream.send(dbq.make_audio_frame(bytes(msg), bridge.session_id))
            continue
        try:
            data = json.loads(msg)
        except (ValueError, TypeError):
            continue
        t = data.get("type")
        if t == "input_audio_buffer.append" and data.get("audio") and bridge.session_started:
            try:
                audio = base64.b64decode(str(data["audio"]))
            except (ValueError, TypeError):
                continue
            await bridge.upstream.send(dbq.make_audio_frame(audio, bridge.session_id))
        elif t == "vision.frame":
            # 后台任务跑看画面，别 await（describe_frame ~5s 会卡住音频转发 → ASR 延迟）。
            # 单飞：已有一次在途就跳过（前端 visionBusy 也会挡，这里再兜一层）。
            if not bridge.vision_in_flight:
                bridge.vision_in_flight = True
                asyncio.create_task(
                    _vision_task_doubao(bridge, str(data.get("frame") or "")))
        elif t == "response.cancel" and bridge.session_started:
            await bridge.upstream.send(
                dbq.make_full_client_frame(dbq.EVENT_CLIENT_INTERRUPT, {}, bridge.session_id))
        # input_audio_buffer.commit 等忽略：豆包走服务端 VAD 自动断句


async def _handle_doubao(browser: Any, enterprise_id: str = "") -> None:
    """一个浏览器连接走豆包实时对话：开上游、握手、配会话、双向桥接。"""
    connect_id = str(uuid4())
    session_id = str(uuid4())
    headers = dbq.build_upstream_headers(
        connect_id,
        app_id=DOUBAO_REALTIME_APP_ID,
        access_key=DOUBAO_REALTIME_ACCESS_KEY,
        api_key=DOUBAO_REALTIME_API_KEY,
        app_key=DOUBAO_REALTIME_APP_KEY,
        resource_id=DOUBAO_REALTIME_RESOURCE_ID,
    )
    async with ws_connect(
        DOUBAO_REALTIME_WS_URL,
        additional_headers=headers,
        proxy=None,
        max_size=None,
    ) as upstream:
        await upstream.send(dbq.make_full_client_frame(dbq.EVENT_START_CONNECTION, {}, None))
        bridge = _DoubaoBridge(browser, upstream, session_id, enterprise_id)
        up = asyncio.create_task(_pump_doubao_upstream(bridge))
        down = asyncio.create_task(_pump_doubao_browser(bridge))
        try:
            _done, pending = await asyncio.wait({up, down}, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
        finally:
            # 收尾：礼貌结束会话与连接
            try:
                if bridge.session_started:
                    await upstream.send(dbq.make_full_client_frame(dbq.EVENT_FINISH_SESSION, {}, session_id))
                await upstream.send(dbq.make_full_client_frame(dbq.EVENT_FINISH_CONNECTION, {}, None))
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════════════
# 上游 2：StepFun stepaudio-2.5-realtime（OpenAI-realtime JSON 协议）
# ══════════════════════════════════════════════════════════════════════════
class _StepBridge:
    """一条浏览器⇄StepFun 连接的共享状态。"""

    def __init__(self, browser: Any, upstream: Any, enterprise_id: str = "") -> None:
        self.browser = browser
        self.upstream = upstream
        self.enterprise_id = enterprise_id  # 该通话所属企业，用于观察留痕
        self.last_vision_desc = ""
        self.vision_in_flight = False  # 看画面任务在途（单飞闸门）
        self.alerted_anomalies: set[str] = set()  # 已弹过的画面疑点指纹（整通范围）


async def _inject_vision_step(bridge: _StepBridge, frame: str) -> None:
    """每轮静默看画面：一帧 → 结构化观察 → 以 user 消息**静默**注入会话（含反欺诈核验提示）。

    不触发 response.create：只更新她的视觉/核验上下文，不打断当前对话、不每轮复述画面。
    核验提示（_verify_hint）本就是"只给她自己看、适时自然去做"的内部指引，一并折进静默注入。
    """
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, describe_frame, frame)
    caption = str(result.get("caption") or "看不清。")
    observation = result.get("observation")
    try:
        await bridge.browser.send(json.dumps({
            "type": "vision.described", "text": caption, "observation": observation,
        }))
    except Exception:
        pass
    # 尽调留痕：观察登记进进程内登记簿（去重前登记，每帧观察都留痕）。
    video_calls.note_observation(bridge.enterprise_id, observation)
    await _notify_visual_risks(bridge, observation)  # 新画面疑点→前端警示块（整通去重）
    if caption == bridge.last_vision_desc:
        return
    bridge.last_vision_desc = caption
    text = _caption_with_scene(caption, observation)
    hint = _verify_hint(observation)
    if hint:
        text += "\n" + hint
    await bridge.upstream.send(json.dumps({
        "type": "conversation.item.create",
        "item": {"type": "message", "role": "user",
                 "content": [{"type": "input_text", "text": text}]},
    }))


async def _vision_task_step(bridge: _StepBridge, frame: str) -> None:
    """后台跑一次看画面（StepFun），兜异常、复位单飞闸门。"""
    try:
        await _inject_vision_step(bridge, frame)
    except Exception:
        pass
    finally:
        bridge.vision_in_flight = False


async def _pump_step_upstream(bridge: _StepBridge) -> None:
    async for msg in bridge.upstream:
        await bridge.browser.send(msg)


async def _pump_step_browser(bridge: _StepBridge) -> None:
    async for msg in bridge.browser:
        if isinstance(msg, (bytes, bytearray)):
            await bridge.upstream.send(msg)
            continue
        try:
            data = json.loads(msg)
        except (ValueError, TypeError):
            await bridge.upstream.send(msg)
            continue
        if data.get("type") == "vision.frame":
            # 后台跑，别 await（describe_frame ~5s 会卡住音频转发）。单飞防并发。
            if not bridge.vision_in_flight:
                bridge.vision_in_flight = True
                asyncio.create_task(
                    _vision_task_step(bridge, str(data.get("frame") or "")))
            continue
        await bridge.upstream.send(msg)


async def _handle_stepfun(browser: Any, enterprise_id: str = "") -> None:
    async with ws_connect(
        STEP_REALTIME_WSS,
        additional_headers={"Authorization": f"Bearer {STEP_API_KEY}"},
        proxy=None,
        max_size=None,
    ) as upstream:
        # 接通即注入与主聊天共享的"开场记忆"（只在建会话时一次，不进每轮音频环）。
        memory = await _load_call_memory(enterprise_id)
        if memory:
            _dbg(f"注入开场记忆 {len(memory)} 字（enterprise={enterprise_id}）")
        await upstream.send(json.dumps({"type": "session.update", "session": realtime_session_config(memory)}))
        bridge = _StepBridge(browser, upstream, enterprise_id)
        up = asyncio.create_task(_pump_step_upstream(bridge))
        down = asyncio.create_task(_pump_step_browser(bridge))
        _done, pending = await asyncio.wait({up, down}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()


# ══════════════════════════════════════════════════════════════════════════
# 连接入口：校验 token → 按 provider 分流
# ══════════════════════════════════════════════════════════════════════════
def _resolve_enterprise(browser: Any) -> str | None:
    """校验连接 query 里的 ?token=，返回令牌里绑定的 enterprise_id；无效返回 None。

    令牌由服务端 realtime-config 用 auth_secret 签发（绑定 enterprise_id+时效），
    既防公网盗用中继、又让中继认得出是哪个企业在通话，据此注入该客户的共享记忆。
    """
    try:
        path = browser.request.path  # 形如 /?token=xxx
    except Exception:
        path = ""
    token = (parse_qs(urlsplit(path).query).get("token") or [""])[0]
    # 兼容老的全局静态令牌：校验通过则放行，但没有 enterprise 绑定→无记忆通话。
    if VOICECALL_RELAY_TOKEN and secrets.compare_digest(token, VOICECALL_RELAY_TOKEN):
        return ""
    return verify_call_token(token)


async def _handle_browser(browser: Any) -> None:
    """一个浏览器连接：校验 token、按 provider 选上游、双向桥接，任一端断开即收尾。"""
    if not realtime_voice_ready():
        await browser.close(code=1011, reason="realtime voice not configured")
        return
    enterprise_id = _resolve_enterprise(browser)
    if enterprise_id is None:
        await browser.close(code=4401, reason="unauthorized")
        return
    _dbg(f"浏览器已连接，开始桥接（enterprise={enterprise_id or '—'}）")
    try:
        if VOICECALL_REALTIME_PROVIDER == "stepfun":
            await _handle_stepfun(browser, enterprise_id)
        else:
            await _handle_doubao(browser, enterprise_id)
    except websockets.exceptions.WebSocketException as exc:
        _dbg(f"!! WebSocketException: {exc!r}")
        try:
            await browser.close(code=1011, reason="upstream error")
        except Exception:
            pass
    except Exception as exc:
        import traceback
        _dbg(f"!! relay 异常: {exc!r}\n{traceback.format_exc()}")
        try:
            await browser.close(code=1011, reason="relay error")
        except Exception:
            pass
    finally:
        _dbg("桥接结束，连接收尾")


async def serve_relay(host: str = VOICECALL_RELAY_HOST, port: int = VOICECALL_RELAY_PORT) -> None:
    async with ws_serve(_handle_browser, host, port, max_size=None):
        await asyncio.Future()  # run forever


def start_relay_thread() -> bool:
    """在守护线程里跑中继（供 server.py 启动时调用）。缺凭证则不启动，返回是否启动。"""
    if not realtime_voice_ready():
        return False

    def _run() -> None:
        try:
            asyncio.run(serve_relay())
        except Exception as exc:  # 中继挂了不该拖垮主服务
            print(f"[voicecall_relay] stopped: {exc}", flush=True)

    threading.Thread(target=_run, name="voicecall-relay", daemon=True).start()
    return True


if __name__ == "__main__":
    print(f"voicecall relay ({VOICECALL_REALTIME_PROVIDER}): "
          f"ws://{VOICECALL_RELAY_HOST}:{VOICECALL_RELAY_PORT}", flush=True)
    asyncio.run(serve_relay())

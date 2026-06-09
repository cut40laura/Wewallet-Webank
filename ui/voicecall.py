"""通话版小微：视频通话模块的大脑（路线1 MVP）。

和主线文字版小微（profile_service.build_gateway_chat_turn + Hermes 网关）
**完全独立**：这里直接打火山方舟(Ark) 的 Doubao 多模态模型，一次调用既
理解客户说的话、又能看一帧摄像头画面（客户举着的营业执照/流水等）。

为什么不复用主线 Hermes 大脑：Hermes 是回合制、带一大套工具，延迟和形态
不适合"打电话"。这里要的是短、口语、快。等拿到 openspeech 的 App ID+Token，
浏览器端的 STT/TTS 占位会换成真正的端到端 RealtimeVoice，本模块的提示词
和画面注入逻辑可以平移过去。

失败模式：抛出 RuntimeError，由 server 层转成 JSON 错误；前端用语音念出
一句"网络好像有点慢"。
"""
from __future__ import annotations

import json
import re
from typing import Any

import requests

from config import (
    ARK_API_KEY,
    ARK_BASE_URL,
    ARK_VISION_MODEL,
    STEP_API_KEY,
    STEP_BASE_URL,
    STEP_REALTIME_VOICE,
    STEP_VOICECALL_MODEL,
    VOICECALL_MODEL,
    VOICECALL_PROVIDER,
    VOICECALL_VISION_PROVIDER,
)


REQUEST_TIMEOUT_S = 30
MAX_HISTORY_TURNS = 8  # 通话讲究即时，只带最近几轮，省 token、降延迟。

# 通话版小微人设：从主线小微的风控提示词里裁出"口语版核心"——保留身份、
# 静默交叉验算、温和追问、待核验闭环；去掉表格/工具/JSON/upload_request 等
# 只在文字 UI 才有意义的东西。语气为"打电话"，回复要短。
SYSTEM_PROMPT = """你叫"小微"，是微众钱包的小微贷款客户经理，现在正在和客户**视频通话**。被问到身份就说你是小微。

这是语音通话，不是打字，所以：
- 回复要**短、口语化**，像真人打电话，一般 1～3 句话，别长篇大论、别念清单。
- **绝对不要**输出 Markdown、表格、emoji、JSON、分点编号、括号注释或任何书面格式——你说的每个字都会被读出来。
- 一次只问 1 个最关键的问题，等客户回答再往下。

业务要点（内部把握，别照本宣科）：
1. 先自然接住客户当前的话，再推进贷款相关信息（经营情况、流水、用途、额度、回款、负债、材料）。
2. **静默交叉验算（每轮心里都做）**，分三支处理：
   - **数字**：收入减成本对得上自报利润吗？人手/产能和营收配吗？额度和流水/纳税规模匹配吗？数字对不上时**温和确认、给台阶**："您前面说的 X 和 Y，我这边对一下口径哈，方便说下……吗？"，别用"欺诈/不合理"这类定性词。
   - **画面 vs 口述场景**：客户说开工厂/店面、生意红火，画面却像卧室、车里、空无一人不像营业场所，或说在店里忙画面却冷清没客人——**这种明显对不上时，要客观、直接地指出，别绕弯子、别替对方找借口、别给模糊台阶**：把你看到的事实摆出来并当场要求核实，例如"我看您现在这边像是在家里，跟您说的在店面经营对不上，这块我得核实一下——您方便说说现在是什么情况，或者把经营场所拍给我看一下吗？"。**仍然不要**用"骗贷/造假/欺诈"这类定性指控词，但事实要讲清楚、口径必须对上或给出证据才往下推进，不能含糊放过。
   - **有没有人/有没有某物——一律以画面为准，绝不轻信口头**：[画面] 旁白会客观告诉你当前画面里有没有人、大概几个人。客户口头说"我这有5个人""我这有一屋子货""我旁边就是设备"，但你收到的画面事实是"没看到人/只看到一位/没看到那东西"时，**绝不能顺着就当真**，要客观、直接地指出不符并要求对方把人或东西移到镜头前："我这边画面里这会儿就看到您一位（/没看到人），您说的几位同事方便都到镜头前我确认下吗？" 在对方真的把人/物显示到镜头里、画面事实改变之前，**不要在回答里承认或附和那些画面上看不到的人或东西**。
3. **疑点要咬住**：客户用"回头补/差不多/没定/挺多的"这种含糊话搪塞，不算说清楚；先礼貌记下，后面换个说法再问，别不了了之。
4. 如果客户把材料举到镜头前（营业执照、流水、合同等），结合你看到的画面回应，并请客户**口头念出上面的关键信息**（公司全名、成立日期、金额、日期、名称等），用他念的和你看到的互相核对——这是核身防伪的关键，别只看不问，也别替客户念。看不清就让他举近一点、举稳一点、光线亮一点。看不到画面时不要假装看到了。
5. 语气亲切、有耐心；客户情绪激动或难过时先共情一句再继续，但该核实的还是要温和地问。
"""


def _build_messages(transcript: str, history: list[dict[str, Any]] | None, frame_data_uri: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in (history or [])[-MAX_HISTORY_TURNS:]:
        role = "assistant" if str(turn.get("role")) == "assistant" else "user"
        text = str(turn.get("content") or "").strip()
        if text:
            messages.append({"role": role, "content": text})

    # 当前这轮：有画面就走多模态 content 数组，否则纯文本。
    spoken = transcript.strip() or "（客户没说话，可能在给你看材料）"
    if frame_data_uri:
        messages.append({
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": frame_data_uri}},
                {"type": "text", "text": spoken},
            ],
        })
    else:
        messages.append({"role": "user", "content": spoken})
    return messages


def _resolve_provider() -> tuple[str, str, str, str, dict[str, Any]]:
    """按 VOICECALL_PROVIDER 选大脑，返回 (label, api_key, base_url, model, extra)。

    Ark 和 StepFun 都是 OpenAI 兼容的 /chat/completions，区别只在凭证/地址/模型，
    所以下游 call_xiaowei 一套代码通吃。step-3.7-flash 原生支持图片，多模态注入
    画面的 message 结构两家一致。

    ``extra`` 是要并进 payload 的 provider 专属参数：
    - StepFun 的 step-3.7-flash 是**推理模型**，每轮都会先思考再出 content。打电话
      要快，所以用 ``reasoning_effort: low`` 把思考压到最短；同时调高 max_tokens——
      思考 token 也算在预算里，给少了会把 content 饿成空字符串（finish=length）。
      注意 step-3.5-flash 虽不推理但**不支持图片**，本模块要看摄像头帧故不能用。
    """
    if VOICECALL_PROVIDER == "stepfun":
        if not STEP_API_KEY:
            raise RuntimeError("STEP_API_KEY 未配置，视频通话不可用")
        return "StepFun", STEP_API_KEY, STEP_BASE_URL, STEP_VOICECALL_MODEL, {
            "reasoning_effort": "low",
            "max_tokens": 800,
        }
    if not ARK_API_KEY:
        raise RuntimeError("ARK_API_KEY 未配置，视频通话不可用")
    return "Ark", ARK_API_KEY, ARK_BASE_URL, VOICECALL_MODEL, {"max_tokens": 400}


def call_xiaowei(
    transcript: str,
    history: list[dict[str, Any]] | None = None,
    frame_data_uri: str = "",
) -> str:
    """跑通话版小微一轮。返回小微要说的话（纯文本，供前端 TTS 念出）。"""
    label, api_key, base_url, model, extra = _resolve_provider()

    payload = {
        "model": model,
        "messages": _build_messages(transcript, history, frame_data_uri),
        "temperature": 0.7,
        **extra,
    }
    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=REQUEST_TIMEOUT_S,
        )
        resp.raise_for_status()
        body = resp.json()
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"{label} 请求失败：{exc}") from exc
    except ValueError as exc:
        raise RuntimeError(f"{label} 响应非 JSON：{exc}") from exc

    try:
        text = str(body["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"{label} 响应缺少内容：{body}") from exc
    if not text:
        raise RuntimeError("小微没给出回复")
    return text


# ──────────────────────────────────────────────────────────────────────────
# 实时语音（stepaudio-2.5-realtime）相关：会话人设 + 视觉桥接
#
# 端到端实时语音模型自己听+说，但**看不了图**。混合桥接的做法：客户把材料举到
# 镜头前时，前端截一帧发给中继，中继调 step-3.7-flash（多模态）把画面里的关键证件
# 信息客观描述出来，再以一条文字消息注入实时会话，让小微"像看到了一样"开口转述并
# 交叉验算。describe_frame() 就是这一步的"眼睛"。
# ──────────────────────────────────────────────────────────────────────────

# 实时会话用的人设：在文字版口语人设基础上，补一句"看材料"的行为约定——因为画面
# 是以文字旁白注入的，要让小微把它当成"自己看到的"，而不是别人转述的。
REALTIME_INSTRUCTIONS = SYSTEM_PROMPT + (
    "\n\n（系统补充·视觉）通话中会不时收到以 [画面] 开头的旁白，那是你此刻通过摄像头看到的实时画面。"
    "\n- 当成自己亲眼所见，别说「系统告诉我」「旁白说」之类的话；也【别把「[画面]」这几个字、"
    "方括号或任何括号本身念出来】。"
    "\n- 平时把最新画面默默记住就好，别每次都复述、别一看到画面就主动播报；只有当画面和当前对话"
    "相关（对方把证件/单据/商品举到镜头前，或你需要核对材料），或对方问到画面（你看到了什么、"
    "我手里这是什么）时，才自然地结合画面回应。"
    "\n- 只说画面旁白里确实提到的，【绝不编造】没提到的长相、穿着、场景或证件内容。完全没有画面、"
    "或画面看不清时，才说这边还看不清、请对方对准镜头、举稳一点、光线亮一点；只要有清楚的画面旁白"
    "就正常据此回答，别再反复说看不清。"
    "\n- 【画面事实优先于口头声称】旁白里「画面里没看到人/可见约N人/没看到某物」是客观事实。对方"
    "口头说「我这有5个人」「我这有货」但画面事实对不上时，【绝不顺着当真、绝不附和画面上看不到的人或物】，"
    "客观直接指出（如「我这边就看到您一位，您说的几位方便都到镜头前我看下吗」）并请对方把人/物移到镜头前；"
    "等画面事实真的变了再据实回应。"
    "\n- 核验材料别光用看的：请对方把证件/执照/单据对准镜头举稳，并【口头念出上面的关键信息】"
    "（姓名、出生年份、公司全名、成立日期、金额、日期等），拿对方念的和你看到的互相核对；对不上"
    "就温和确认，别假装自己看清了、也别替对方念。发现对不上别指控，给台阶、温和求证。"
    "\n\n通话中可能收到以「（核验提示」开头的内容，那是只给你看的内部核验指引——"
    "【绝对不要读出来、不要提它的存在】，按它说的在合适时机自然地去做就行。"
)

# 多模态模型当"眼睛"：不只找证件，而是客观描述整帧并**结构化**输出反欺诈信号
# （场所类型、是否有人、是否疑似照稿念、可见证件与其文字、与经营场景不符的疑点）。
# 结构化的好处：caption 注入实时会话当小微"亲眼所见"，其余字段喂尽调反欺诈交叉核验
# （见 voicecall_relay._verify_hint：出示证件→提示口头念出核对；疑点→温和确认口径）。
# 默认用 Doubao doubao-1.6-vision（走 Ark）；也可切回 StepFun step-3.7-flash。
_VISION_STRUCTURED_PROMPT = (
    "你是小微企业贷款视频通话里的画面观察器，只客观描述这一帧里**确实看到**的，"
    "看不清就如实标注，绝不猜测、绝不编造长相/穿着/场景细节。"
    "严格只输出一个 JSON 对象（不要解释、不要多余文字）：\n"
    '{"place_type":"办公室|居住/家|店铺|工厂/车间|户外|车内|会议室|其他|看不清",'
    '"person_present":true/false,"person_count":数字,'
    '"looking_off_screen":true/false,'  # 是否频繁瞟别处/疑似照稿念
    '"person_desc":"有人物时，简述画面里这个人【确实看得清的】外观：性别、大致年龄段、发型、衣着颜色款式、戴没戴眼镜/帽子、表情或姿态；没人或看不清就空字符串。绝不猜测、绝不编造",'
    '"visible_documents":["证件/执照/合同/流水等，看不清就空数组"],'
    '"document_text":"证件/单据上能读到的关键字（名称、日期、金额、公司抬头等），读不到就空字符串",'
    '"notable_objects":["显著物品/商品/设备"],'
    # 关键：判"与**常规**经营/营业场所不符"（看图就能判），不是"与所述不符"（你看不到对话、判不了）。
    '"anomalies":["与常规经营/营业场所明显不符之处（如不像做生意的地方、像卧室/车内/空无一人），没有就空数组"],'
    '"caption":"一句话客观描述这帧画面：画面里**有人就先简述这个人**（性别、大致年龄段、发型、衣着等确实看得清的），再带场景；没人就只说场景。40字以内"}'
    "\n要求：直接只输出这个 JSON，不要思考过程、不要解释；每个数组最多列 3 项；caption 控制在 40 字内。"
)


def _salvage_caption(raw: str) -> str:
    """JSON 截断/解析失败时，尽量从原文里捞出 caption 文本（容忍缺尾引号）；捞不到返回 ""。"""
    match = re.search(r'"caption"\s*:\s*"([^"]{0,80})', raw or "")
    return match.group(1).strip() if match else ""


def _extract_json(raw: str) -> str:
    """从模型输出里抠出 JSON 对象文本：兼容```json 代码块、前后夹带的解释文字。"""
    text = (raw or "").strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    candidate = fenced.group(1).strip() if fenced else text
    if candidate.startswith("{") and candidate.endswith("}"):
        return candidate
    start, end = candidate.find("{"), candidate.rfind("}")
    if 0 <= start < end:
        return candidate[start:end + 1]
    return ""


def _parse_observation(raw: str) -> dict[str, Any] | None:
    """把结构化视觉输出解析成 dict 并规整关键字段；解析不出返回 None。"""
    payload = _extract_json(raw)
    if not payload:
        return None
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    data.setdefault("caption", "")
    data.setdefault("place_type", "看不清")
    data.setdefault("person_present", False)
    data.setdefault("looking_off_screen", False)
    for key in ("visible_documents", "notable_objects", "anomalies"):
        if not isinstance(data.get(key), list):
            data[key] = []
    for key in ("document_text", "person_desc"):
        if not isinstance(data.get(key), str):
            data[key] = ""
    return data


def _resolve_vision_provider() -> tuple[str, str, str, dict[str, Any]] | None:
    """按 VOICECALL_VISION_PROVIDER 选"眼睛"，返回 (api_key, base_url, model, extra)。

    凭证缺失返回 None（describe_frame 据此走兜底，不抛错中断通话）。``extra`` 是要并进
    payload 的 provider 专属参数：StepFun 的 step-3.7-flash 是推理模型，思考 token 也算
    预算，给 reasoning_effort:low + 大 max_tokens 避免 content 被思考吃空；Doubao 的
    doubao-1.6-vision 不推理，普通 max_tokens 即可。
    """
    if VOICECALL_VISION_PROVIDER == "stepfun":
        if not STEP_API_KEY:
            return None
        return STEP_API_KEY, STEP_BASE_URL, STEP_VOICECALL_MODEL, {
            "reasoning_effort": "low",
            "max_tokens": 2048,
        }
    if not ARK_API_KEY:
        return None
    return ARK_API_KEY, ARK_BASE_URL, ARK_VISION_MODEL, {"max_tokens": 800}


def _vision_request(frame_data_uri: str) -> str:
    """跑一次视觉请求，返回模型输出的原始文本；网络/HTTP/结构异常/缺凭证都返回 ""（绝不抛错）。"""
    resolved = _resolve_vision_provider()
    if resolved is None:
        return ""
    api_key, base_url, model, extra = resolved
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": frame_data_uri}},
                {"type": "text", "text": _VISION_STRUCTURED_PROMPT},
            ],
        }],
        "temperature": 0.2,
        **extra,
    }
    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=REQUEST_TIMEOUT_S,
        )
        resp.raise_for_status()
        return str(resp.json()["choices"][0]["message"]["content"] or "").strip()
    except (requests.exceptions.RequestException, ValueError, KeyError, IndexError, TypeError):
        return ""


def describe_frame(frame_data_uri: str) -> dict[str, Any]:
    """看一帧客户举到镜头前的画面，返回结构化观察供注入实时会话 + 反欺诈交叉核验。

    返回 ``{"caption": <一句话自然描述，可直接注入/念>, "observation": <结构化 dict 或 None>}``。
    失败/看不清也返回可用的 caption，**绝不抛错**中断通话。
    """
    if not frame_data_uri:
        return {"caption": "看不清，画面里好像没有材料。", "observation": None}
    if _resolve_vision_provider() is None:
        return {"caption": "看不清。", "observation": None}

    raw = _vision_request(frame_data_uri)
    observation = _parse_observation(raw)
    if observation is None:
        # 偶发空内容/不可解析：step 推理结果有抖动，重试一次（手动看材料是低频动作，代价可接受）。
        raw2 = _vision_request(frame_data_uri)
        obs2 = _parse_observation(raw2)
        if obs2 is not None:
            observation, raw = obs2, raw2
        elif raw2 and not raw:
            raw = raw2

    # caption 绝不回退成生 JSON 串（截断时那会被当 [画面] 注入念出来）：解析成功用其 caption，
    # 否则从原文捞 caption，再不行给一句干净兜底。
    if observation:
        caption = observation.get("caption") or _salvage_caption(raw) or "看不清。"
    else:
        caption = _salvage_caption(raw) or "画面有点糊，看不太清。"
    return {"caption": caption, "observation": observation}


def realtime_session_config() -> dict[str, Any]:
    """实时会话的 session.update.session 配置（人设/音色/音频格式/断句）。"""
    return {
        "modalities": ["text", "audio"],
        "instructions": REALTIME_INSTRUCTIONS,
        "voice": STEP_REALTIME_VOICE,
        "input_audio_format": "pcm16",
        "output_audio_format": "pcm16",
        "turn_detection": {"type": "server_vad", "silence_duration_ms": 600},
    }


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "喂，你好，我想问下贷款的事"
    print(call_xiaowei(q))

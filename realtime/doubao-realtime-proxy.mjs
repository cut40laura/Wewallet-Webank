import http from "node:http";
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import WebSocket, { WebSocketServer } from "ws";

// —— 加载同目录 .env（无需 dotenv 依赖）——
try {
  const root = dirname(fileURLToPath(import.meta.url));
  for (const line of readFileSync(join(root, ".env"), "utf8").split(/\r?\n/)) {
    const m = line.match(/^([A-Z0-9_]+)=(.*)$/);
    if (m && process.env[m[1]] === undefined) process.env[m[1]] = m[2];
  }
} catch {}

const PORT = Number(process.env.DOUBAO_REALTIME_PROXY_PORT || 8870);
const HOST = process.env.DOUBAO_REALTIME_PROXY_HOST || "127.0.0.1";
const API_KEY = process.env.DOUBAO_REALTIME_API_KEY || "";
const APP_ID = process.env.DOUBAO_REALTIME_APP_ID || "";
const ACCESS_KEY = process.env.DOUBAO_REALTIME_ACCESS_KEY || "";
const APP_KEY = process.env.DOUBAO_REALTIME_APP_KEY || "PlgvMymc7f3tQnJ6";
const RESOURCE_ID = process.env.DOUBAO_REALTIME_RESOURCE_ID || "volc.speech.dialog";
const MODEL_VERSION = process.env.DOUBAO_REALTIME_MODEL_VERSION || "1.2.1.1";
const INPUT_MOD = process.env.DOUBAO_REALTIME_INPUT_MOD || "audio";
const UPSTREAM_URL =
  process.env.DOUBAO_REALTIME_WS_URL ||
  "wss://openspeech.bytedance.com/api/v3/realtime/dialogue";

// 视频通话：亲和的客户经理，先陪聊、暗中兼顾反欺诈。实时语音模型自己看不清画面，但页面会在需要时注入 Seed 视觉结果。
const VIDEO_SYSTEM_ROLE =
  "你是微众银行小微信贷的客户经理，正在和用户视频通话。你的风格像一位会聊天的真人经理：先让对方放松、自然地聊起来，而不是一上来就走核验流程。" +
  "【先陪聊·再引导】先针对用户当下说的话或画面做出具体、自然的回应，顺着对方的话题聊一两句，可以拉家常、闲聊；只有当用户提到资金需求、主动问贷款/额度/周转，或聊到自己的生意经营时，才顺势温和地带一句相关的话，绝不硬把话题拽回尽调，也不要不停追问流水、资料。" +
  "【暗中反欺诈】放松聊天的同时，你心里始终留意有没有欺诈或冒用风险，但要不动声色、绝不指控、不让对方紧张：①留意前后说法是否矛盾，发现不一致时用好奇、随口的语气温和求证，并给对方台阶；②留意是否有人在旁边提词、念稿、被指使，或本人神情紧张、答非所问、回避正脸或证件；③留意画面与口述是否对得上（经营场景是否真实），可以用闲聊的方式自然核实，比如随口问问店里生意、周边环境、平时几点开门。" +
  "【看画面】你自己看不清摄像头画面，但系统会持续给你以“（画面信息：…）”开头的消息，那是真实视觉模型当前看到的画面内容。你只需默默记住最新的画面信息，不要主动播报、不要每次都复述、不要照念括号本身；只有当用户问到画面（你看到了什么、这是什么、我手里拿的、证件、物品、环境等）时，再用最新的画面信息自然作答，绝不编造画面信息里没有的细节。完全没有任何画面信息时，才说这边还看不清、请对方对准镜头；只要有画面信息就正常据此回答，不要再说看不清。" +
  "【场景对不上时·先核对不附和】这是“默默记住画面”的唯一例外：当用户主动声称自己所在的地点/场景/环境（如“我在餐厅”“在店里”“在办公室”），而这与最新画面信息明显不符（画面更像宿舍、卧室、车里等）时，绝不能顺着附和、也不要假装相信。①先用好奇、不指控的口吻把这处出入摆出来核对一句，例如“诶，我这边画面看着更像是在宿舍呢，跟餐厅好像对不太上，是镜头切到别处了吗？”；②若用户能合理解释（临时换了地方、在后厨等），就接受、继续自然地聊；③若用户回避、含糊或反复狡辩，就再自然地请他给点能对上的佐证（转一圈镜头看看周边、念念门口招牌、拍下经营环境）；④仍然无法自圆其说时，心里把它记为可疑（疑似拿画面或说法造假），后续核验更谨慎。全程口吻始终客气、不撕破脸。注意：只有在确有画面信息、且明显矛盾时才这样做；没有画面信息或拿不准时，宁可不质疑。" +
  "【核验证件时】需要核对身份或资料时，自然地请用户把东西对准镜头，并【让用户口头念出关键信息】来核对，像顺手确认而非审问，例如“方便的话把身份证对准镜头，顺口念一下上面的姓名和出生年份，我这边记一下”。除非系统已给出画面信息，否则你根据用户口述来核对，而不是假装自己看清了。" +
  "【边界】①亲和、口语化，一次只说一两句话，一次只提一个请求。②你记得用户之前说过的话。③不指控、给台阶。④合规：不承诺额度或审批结果，不编造任何不确定的信息。";

// 语音通话：纯语音人设（不涉及摄像头/视频）。
const VOICE_SYSTEM_ROLE =
  "你是微众银行小微信贷 AI 客户经理，正在和用户实时语音通话。原则：1) 先正面回答用户当下说的话、紧扣对方内容，别自顾自走流程。2) 充分尊重用户意愿——如果用户不想做尽调、想聊别的、或想结束，就顺着用户来，正常聊或礼貌结束，不要反复把话题硬拽回尽调，更不要不停追问经营、流水、资料这些；只有当用户主动愿意或明确需要办贷款时，才自然地推进尽调内容。3) 不确定的事就先问，不要假设或编造你没看到的信息。用口语化、简洁的中文，一次说一两句。";

const EVENT_SEND = {
  StartConnection: 1,
  FinishConnection: 2,
  StartSession: 100,
  FinishSession: 102,
  TaskRequest: 200,
  EndASR: 400,
  ChatTextQuery: 501,
  ClientInterrupt: 515
};

const EVENT_RECEIVE = {
  ConnectionStarted: 50,
  ConnectionFailed: 51,
  ConnectionFinished: 52,
  SessionStarted: 150,
  SessionCanceled: 151,
  SessionFinished: 152,
  SessionFailed: 153,
  Usage: 154,
  TTSSentenceStart: 350,
  TTSSentenceEnd: 351,
  TTSResponse: 352,
  TTSEnded: 359,
  TTSSubtitle: 364,
  ASRInfo: 450,
  ASRResponse: 451,
  ASREnded: 459,
  ChatResponse: 550,
  ChatTextQueryConfirmed: 553,
  ChatEnded: 559,
  DialogCommonError: 599
};

const server = http.createServer((req, res) => {
  // 浏览器从 Python(UI 端口) 调本代理(:8870) 是跨域，统一放行
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  if (req.method === "OPTIONS") {
    res.writeHead(204);
    res.end();
    return;
  }

  const url = new URL(req.url, "http://localhost");
  if (req.method === "POST" && url.pathname === "/api/vision") {
    handleVision(req, res).catch((error) => sendJson(res, 502, { error: String(error?.message || error) }));
    return;
  }
  if (req.method === "POST" && url.pathname === "/api/video-chat") {
    handleVideoChat(req, res).catch((error) => sendJson(res, 502, { error: String(error?.message || error) }));
    return;
  }
  if (req.method === "POST" && url.pathname === "/api/risk-summary") {
    handleRiskSummary(req, res).catch((error) => sendJson(res, 502, { error: String(error?.message || error) }));
    return;
  }
  if (req.method === "POST" && url.pathname === "/api/contradiction-check") {
    handleContradictionCheck(req, res).catch((error) => sendJson(res, 502, { error: String(error?.message || error) }));
    return;
  }

  sendJson(res, 200, {
    ok: true,
    service: "doubao-realtime-proxy",
    configured: hasRealtimeCredentials(),
    credential_mode: APP_ID && ACCESS_KEY ? "app-id-access-key" : API_KEY ? "api-key" : "mock",
    path: "/v1/realtime-voice/stream"
  });
});

const wss = new WebSocketServer({ server, path: "/v1/realtime-voice/stream" });

wss.on("connection", (client, request) => {
  const sessionId = randomUUID();
  const connectId = randomUUID();
  const scene = parseScene(request); // "video" | "voice"
  const systemRole = scene === "video" ? VIDEO_SYSTEM_ROLE : VOICE_SYSTEM_ROLE;

  if (!hasRealtimeCredentials()) {
    client.send(
      JSON.stringify({
        type: "proxy.mock",
        session_id: sessionId,
        message: "未配置豆包实时语音凭证，已进入本地模拟语音模式。"
      })
    );
    return bindMockSession(client, sessionId);
  }

  const upstream = new WebSocket(UPSTREAM_URL, {
    headers: buildUpstreamHeaders(connectId)
  });

  let upstreamReady = false;
  let sessionStarted = false;
  let aiSpeaking = false; // AI 是否正在播报（用于打断）
  let suppressTurnUntil = 0; // >now 表示当前轮是"静默喂画面"，吞掉它的播报不下发给前端

  upstream.on("open", () => {
    upstreamReady = true;
    safeSend(client, {
      type: "proxy.connected",
      session_id: sessionId,
      upstream: "doubao-realtime-dialogue",
      credential_mode: APP_ID && ACCESS_KEY ? "app-id-access-key" : "api-key"
    });
    upstream.send(makeFullClientFrame(EVENT_SEND.StartConnection, {}, null));
  });

  upstream.on("message", (data) => {
    const frame = decodeDoubaoFrame(data);
    if (!frame) {
      safeSend(client, { type: "proxy.warning", message: "收到无法解析的豆包二进制帧。" });
      return;
    }

    // 用户一开口就解除静默，避免把用户这轮的真实回答也吞掉
    if (frame.event === EVENT_RECEIVE.ASRResponse) suppressTurnUntil = 0;

    const translated = translateDoubaoFrame(frame);
    const suppressing = suppressTurnUntil > Date.now();
    for (const payload of translated) {
      // 静默喂画面这一轮：吞掉文字/音频播报，只让豆包把画面收进上下文
      if (suppressing && (payload.type === "response.text.delta" || payload.type === "response.audio.delta" || payload.type === "response.audio_transcript.delta")) {
        continue;
      }
      safeSend(client, payload);
    }
    // 只在 TTS 真正播完(TTSEnded)时解除：ChatEnded 早于音频，若用它解除会让喂画面那轮的音频漏出来（念一段但不显示文字）
    if (suppressing && frame.event === EVENT_RECEIVE.TTSEnded) {
      suppressTurnUntil = 0;
    }

    // 跟踪 AI 是否在播报
    if (frame.event === EVENT_RECEIVE.TTSSentenceStart || frame.event === EVENT_RECEIVE.TTSResponse) {
      aiSpeaking = true;
    } else if (frame.event === EVENT_RECEIVE.TTSEnded || frame.event === EVENT_RECEIVE.ChatEnded) {
      aiSpeaking = false;
    }
    // 用户开口（ASR）时若 AI 正在说 → 打断上游，让它停下来听用户最新的话
    if (frame.event === EVENT_RECEIVE.ASRResponse && aiSpeaking && sessionStarted) {
      upstream.send(makeFullClientFrame(EVENT_SEND.ClientInterrupt, {}, sessionId));
      aiSpeaking = false;
    }

    if (frame.event === EVENT_RECEIVE.ConnectionStarted) {
      upstream.send(makeFullClientFrame(EVENT_SEND.StartSession, createSessionConfig(systemRole), sessionId));
    }
    if (frame.event === EVENT_RECEIVE.SessionStarted) {
      sessionStarted = true;
    }
    if (isFailureEvent(frame.event)) {
      client.close();
    }
  });

  upstream.on("error", (error) => {
    safeSend(client, {
      type: "proxy.error",
      message: `豆包实时语音连接失败：${error.message}`,
      credential_hint:
        APP_ID && ACCESS_KEY
          ? "请确认实时语音权限、AppID、Access Token 与资源开通状态。"
          : "该接口需要 X-Api-App-ID 与 X-Api-Access-Key；只有新版 X-Api-Key 时可能返回 403。"
    });
  });

  upstream.on("close", (code, reason) => {
    safeSend(client, { type: "proxy.closed", code, reason: reason.toString() });
    client.close();
  });

  client.on("message", (data, isBinary) => {
    if (!upstreamReady || upstream.readyState !== WebSocket.OPEN) return;

    if (isBinary) {
      if (sessionStarted) upstream.send(makeAudioFrame(Buffer.from(data), sessionId));
      return;
    }

    const payload = parseJson(data.toString("utf8"));
    if (!payload) return;

    if (payload.type === "input_audio_buffer.append" && payload.audio && sessionStarted) {
      upstream.send(makeAudioFrame(Buffer.from(String(payload.audio), "base64"), sessionId));
      return;
    }

    if (payload.type === "input_audio_buffer.commit" && sessionStarted) {
      upstream.send(makeFullClientFrame(EVENT_SEND.EndASR, {}, sessionId));
      return;
    }

    if (payload.type === "conversation.item.create" && payload.text && sessionStarted) {
      upstream.send(makeFullClientFrame(EVENT_SEND.ChatTextQuery, { content: String(payload.text) }, sessionId));
      return;
    }
    if (payload.type === "input_text" && payload.text && sessionStarted) {
      upstream.send(makeFullClientFrame(EVENT_SEND.ChatTextQuery, { content: String(payload.text) }, sessionId));
      return;
    }

    // 静默喂画面：作为文本查询送进豆包（更新其对话上下文），但本轮播报会被吞掉不下发。
    if (payload.type === "context_text" && payload.text && sessionStarted) {
      suppressTurnUntil = Date.now() + 8000; // 安全上限，防漏掉结束事件后一直静音
      upstream.send(makeFullClientFrame(EVENT_SEND.ChatTextQuery, { content: String(payload.text) }, sessionId));
      return;
    }

    if (payload.type === "response.cancel" && sessionStarted) {
      upstream.send(makeFullClientFrame(EVENT_SEND.ClientInterrupt, {}, sessionId));
    }
  });

  client.on("close", () => {
    if (upstream.readyState === WebSocket.OPEN) {
      if (sessionStarted) upstream.send(makeFullClientFrame(EVENT_SEND.FinishSession, {}, sessionId));
      upstream.send(makeFullClientFrame(EVENT_SEND.FinishConnection, {}, null));
      upstream.close();
    }
  });
});

server.listen(PORT, HOST, () => {
  console.log(`Doubao realtime proxy listening on ws://${HOST}:${PORT}/v1/realtime-voice/stream`);
});

// ============ 视频通话·视觉理解 /api/vision（豆包 ARK → Qwen 降级 → mock） ============

const VISION_DEFAULT_PROMPT =
  "你是语音视频尽调中的 AI 客户经理。用一句中文简洁描述这帧画面里：人是否在场、所处环境/经营场所、可见的关键物品或证件。不要寒暄，只给客观描述。";
const VISION_STRUCTURED_PROMPT = `你是视频尽调的画面观察器。只描述你在这帧里**确实看到**的，看不清就如实标注，绝不猜测。严格输出 JSON：
{"place_type":"办公室|居住/宿舍|店铺|户外|车内|会议室|其他|看不清",
"person_present":true/false,"person_count":数字,
"looking_off_screen":true/false,
"visible_documents":["证件/执照等，看不清就空数组"],
"document_text":"如有证件且能读到的关键字，否则空字符串",
"notable_objects":["显著物品"],"anomalies":["与常规经营场景不符之处，没有就空数组"],
"caption":"一句话客观描述"}`;

function resolveVisionProvider() {
  if (process.env.ARK_API_KEY) {
    return {
      provider: "ark",
      apiKey: process.env.ARK_API_KEY,
      baseUrl: (process.env.ARK_BASE_URL || "https://ark.cn-beijing.volces.com/api/v3").replace(/\/+$/, ""),
      model: process.env.ARK_VISION_MODEL || "doubao-1.6-vision"
    };
  }
  if (process.env.QWEN_API_KEY) {
    return {
      provider: "qwen",
      apiKey: process.env.QWEN_API_KEY,
      baseUrl: (process.env.QWEN_BASE_URL || "https://dashscope.aliyuncs.com/compatible-mode/v1").replace(/\/+$/, ""),
      model: process.env.QWEN_MULTIMODAL_MODEL || "qwen-vl-plus"
    };
  }
  return { provider: "mock", apiKey: "", baseUrl: "", model: "" };
}

async function handleVision(req, res) {
  const body = await readJsonBody(req);
  const image = typeof body.image === "string" ? body.image : "";
  if (!image.startsWith("data:image")) {
    return sendJson(res, 400, { error: "image 需为 data:image/... 的 dataURL。" });
  }

  const { provider, apiKey, baseUrl, model } = resolveVisionProvider();
  const structured = body.mode === "structured";
  if (provider === "mock") {
    const description = "（未配置视觉模型凭证：请在 realtime/.env 设置 ARK_API_KEY/ARK_VISION_MODEL，或保留 QWEN_API_KEY 降级。）";
    return sendJson(res, 200, {
      provider,
      description,
      ...(structured ? { observation: fallbackObservation(description) } : {})
    });
  }

  const upstream = await fetch(`${baseUrl}/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
    body: JSON.stringify({
      model,
      messages: [
        {
          role: "user",
          content: [
            { type: "text", text: structured ? VISION_STRUCTURED_PROMPT : body.prompt || VISION_DEFAULT_PROMPT },
            { type: "image_url", image_url: { url: image } }
          ]
        }
      ]
    })
  });

  if (!upstream.ok) {
    const detail = await upstream.text().catch(() => "");
    return sendJson(res, upstream.status || 502, { provider, error: detail || upstream.statusText || "视觉模型请求失败。" });
  }

  const data = await upstream.json();
  const description = data.choices?.[0]?.message?.content?.trim() || "";
  return sendJson(res, 200, {
    provider,
    description,
    ...(structured ? { observation: parseStructuredObservation(description) } : {})
  });
}

function parseStructuredObservation(raw) {
  const jsonText = extractJsonObject(raw);
  if (!jsonText) return fallbackObservation(raw);
  try {
    const parsed = JSON.parse(jsonText);
    if (typeof parsed !== "object" || parsed === null) return fallbackObservation(raw);
    return {
      ...parsed,
      place_type: typeof parsed.place_type === "string" && parsed.place_type ? parsed.place_type : "看不清",
      caption: typeof parsed.caption === "string" && parsed.caption ? parsed.caption : raw
    };
  } catch {
    return fallbackObservation(raw);
  }
}

function extractJsonObject(raw) {
  const trimmed = String(raw || "").trim();
  const fenced = trimmed.match(/```(?:json)?\s*([\s\S]*?)\s*```/i);
  const candidate = fenced?.[1]?.trim() || trimmed;
  if (candidate.startsWith("{") && candidate.endsWith("}")) return candidate;
  const start = candidate.indexOf("{");
  const end = candidate.lastIndexOf("}");
  if (start >= 0 && end > start) return candidate.slice(start, end + 1);
  return "";
}

function fallbackObservation(caption) {
  return { caption, place_type: "看不清" };
}

// ============ 视频通话·文字兜底 /api/video-chat（豆包 ARK 流式 → text/plain） ============

const VIDEO_CHAT_SYSTEM_PROMPT = [
  "你是 WeWallet 微众银行小微信贷的 AI 客户经理，正在和用户实时视频通话。",
  "【性格】亲和、自然，像会聊天的真人客户经理。可以先和用户拉家常、闲聊、回应当下的话题，让对方放松，不用一上来就谈贷款或尽调。",
  "【先回应再引导】先针对用户这句话或当前画面做出具体自然的回应，说明你听懂/看懂了什么，顺着聊一两句；只有当用户表达资金需求、主动问贷款/额度/周转，或聊到自己的生意经营时，才顺势温和带入一句相关的问题，绝不硬拽话题，也不要不停追问流水、资料。",
  "【暗中反欺诈】轻松聊天的同时，你心里始终留意有没有欺诈或冒用风险，但要不动声色、绝不指控、不让对方紧张：",
  "- 留意前后说法是否矛盾（如先说店是朋友的、又改口说是自己的；先说开店、又说在别处上班），出现这种反复时不要轻易放过，用好奇、随口的语气追一句把它问实，并给对方台阶；",
  "- 若听到旁边有人提词、念稿、有人指使，或本人答非所问、对自己的店名/证件信息都要现找现看、明显不熟悉，这些都是高风险信号，要不动声色地多问一句自然的问题做交叉印证（比如随口问问店开在哪条街、平时几点开门、主营什么）；",
  "- 留意画面与口述是否对得上（经营场景是否真实），可以用闲聊的方式自然核实。",
  "【核验克制】请对方把证件对准镜头、念关键信息，这类要求点到为止：同一件事别反复催，正常聊天里自然提一次即可，不要每句话都把话题拽回‘把营业执照对准镜头’。",
  "【别假装看得见】这是文字通道，你并不能真正看清画面。用户问‘你看我这是不是本人/这是什么/画面里有啥’时，不要凭空确认或描述，要如实说这边画面还看不太清，请对方对准镜头、或口头念出关键信息来核对，绝不编造看到的内容。",
  "【画面与口述对不上时·先核对不附和】当系统已给出“摄像头视觉摘要”、而用户声称的所在地点/场景/环境与摘要明显不符时，不要附和、不要假装相信：先用好奇、不指控的口吻指出这处出入、请对方核对一句；若对方能合理解释就接受、继续聊；若回避或反复狡辩，就自然地请他给更多能对上的佐证（转一圈镜头看看周边、念念门口招牌等）；仍说不通就心里记为可疑、后续更谨慎。口吻始终客气、不指控。注意：只有在确有视觉摘要、且明显矛盾时才这样做；没有摘要或拿不准时，按‘别假装看得见’如实说看不清，绝不凭空质疑。",
  "【边界】一次只说一两句，口语化、简洁，不长篇大论、不罗列流程清单。不承诺额度、通过率或审批结果，不夸大，合规为先。"
].join("\n");

async function handleVideoChat(req, res) {
  const apiKey = process.env.ARK_API_KEY;
  const baseUrl = (process.env.ARK_BASE_URL || "https://ark.cn-beijing.volces.com/api/v3").replace(/\/+$/, "");
  const model = process.env.ARK_TEXT_MODEL || process.env.ARK_VISION_MODEL || "doubao-seed-2-0-mini-260428";
  if (!apiKey) return sendJson(res, 500, { error: "未配置 ARK_API_KEY，视频通话文字回复不可用。" });

  const body = await readJsonBody(req);
  const messages = normalizeMessages(body.messages);
  if (!messages.length) return sendJson(res, 400, { error: "messages 不能为空。" });

  const upstream = await fetch(`${baseUrl}/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
    body: JSON.stringify({
      model,
      stream: true,
      thinking: { type: "disabled" },
      messages: [{ role: "system", content: VIDEO_CHAT_SYSTEM_PROMPT }, ...messages]
    })
  });

  if (!upstream.ok || !upstream.body) {
    const detail = await upstream.text().catch(() => "");
    return sendJson(res, upstream.status || 502, { error: detail || upstream.statusText || "豆包 ARK 流式接口请求失败。" });
  }

  res.writeHead(200, {
    "Content-Type": "text/plain; charset=utf-8",
    "Cache-Control": "no-store",
    "X-Accel-Buffering": "no",
    "Access-Control-Allow-Origin": "*"
  });

  const decoder = new TextDecoder();
  let buffer = "";
  for await (const chunk of upstream.body) {
    buffer += decoder.decode(chunk, { stream: true });
    const lines = buffer.split(/\r?\n/);
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (isSseDone(line)) {
        res.end();
        return;
      }
      const text = parseSseDelta(line);
      if (text) res.write(text);
    }
  }
  const tail = parseSseDelta(buffer);
  if (tail) res.write(tail);
  res.end();
}

function normalizeMessages(messages) {
  if (!Array.isArray(messages)) return [];
  return messages
    .filter((m) => m && ["user", "assistant"].includes(m.role) && typeof m.content === "string")
    .map((m) => ({ role: m.role, content: m.content.slice(0, 8000) }));
}

function parseSseDelta(line) {
  const trimmed = String(line || "").trim();
  if (!trimmed.startsWith("data:")) return "";
  const data = trimmed.slice(5).trim();
  if (!data || data === "[DONE]") return "";
  try {
    const payload = JSON.parse(data);
    return payload.choices?.[0]?.delta?.content || payload.choices?.[0]?.message?.content || "";
  } catch {
    return "";
  }
}

function isSseDone(line) {
  const trimmed = String(line || "").trim();
  return trimmed === "data: [DONE]" || trimmed === "[DONE]";
}

// ============ 视频通话·风控总结 /api/risk-summary（规则聚合 + ARK 总结，best-effort） ============

const RISK_SUMMARY_PROMPT = [
  "你是微众银行小微信贷的风控审核助手。下面给你一段 AI 客户经理与用户的视频尽调通话：包含逐句对话转写，以及系统逐帧的客观画面观察。",
  "请基于这些材料，判断本次通话是否存在欺诈、冒用或经营造假的风险迹象，给出克制、就事论事的结论。只依据材料，绝不臆测材料里没有的内容。",
  '严格输出 JSON：{"level":"low|medium|high","reasons":["简短中文要点，最多5条，没有就空数组"]}。',
  "判级参考：前后说法矛盾、有人提词念稿、本人对自己店名/证件不熟、画面与口述对不上、回避正脸或证件等，属于升级信号；材料正常则 low。"
].join("\n");

function aggregateRiskSignals(observations) {
  const list = Array.isArray(observations) ? observations : [];
  let anomalyCount = 0;
  let offScreenCount = 0;
  let personAbsentCount = 0;
  const documents = new Set();
  for (const obs of list) {
    if (!obs || typeof obs !== "object") continue;
    if (Array.isArray(obs.anomalies)) anomalyCount += obs.anomalies.filter(Boolean).length;
    if (obs.looking_off_screen === true) offScreenCount += 1;
    if (obs.person_present === false) personAbsentCount += 1;
    if (Array.isArray(obs.visible_documents)) {
      for (const doc of obs.visible_documents) if (doc) documents.add(String(doc));
    }
  }
  return {
    frame_count: list.length,
    anomaly_count: anomalyCount,
    off_screen_count: offScreenCount,
    person_absent_count: personAbsentCount,
    documents_seen: [...documents]
  };
}

// 仅凭硬信号给一个保守的初始等级；AI 总结可在其之上调整。
function ruleLevel(signals) {
  if (signals.anomaly_count > 0) return "medium";
  if (signals.frame_count > 0 && signals.off_screen_count > signals.frame_count / 2) return "medium";
  return "low";
}

function transcriptToText(transcript) {
  if (!Array.isArray(transcript)) return "";
  return transcript
    .filter((t) => t && typeof t.text === "string" && t.text.trim())
    .map((t) => `${t.role === "ai" ? "客户经理" : "用户"}：${t.text.trim()}`)
    .join("\n")
    .slice(0, 8000);
}

function observationsToText(observations) {
  if (!Array.isArray(observations)) return "";
  return observations
    .map((o) => (o && o.caption ? String(o.caption) : ""))
    .filter(Boolean)
    .join("\n")
    .slice(0, 4000);
}

async function handleRiskSummary(req, res) {
  const body = await readJsonBody(req);
  const signals = aggregateRiskSignals(body.observations);
  const result = { level: ruleLevel(signals), reasons: [], signals };

  // 通话中实时检测到的"与历史不符"明细，作为风控判级的强信号纳入结论（无论是否有 ARK 凭证）。
  if (Array.isArray(body.contradictions) && body.contradictions.length) {
    result.signals.contradiction_count = body.contradictions.length;
    if (result.level === "low") result.level = "medium";
  }

  const apiKey = process.env.ARK_API_KEY;
  const transcriptText = transcriptToText(body.transcript);
  // 没凭证或没有任何对话内容时，退回纯规则结论。
  if (!apiKey || !transcriptText) {
    return sendJson(res, 200, result);
  }

  try {
    const baseUrl = (process.env.ARK_BASE_URL || "https://ark.cn-beijing.volces.com/api/v3").replace(/\/+$/, "");
    const model = process.env.ARK_TEXT_MODEL || process.env.ARK_VISION_MODEL || "doubao-seed-2-0-mini-260428";
    const contradictionText = (Array.isArray(body.contradictions) ? body.contradictions : [])
      .map((c) => `- ${c.field || ""}：用户说"${c.stated || ""}"，档案为"${c.known || ""}"`)
      .join("\n");
    const userContent =
      `对话转写：\n${transcriptText}\n\n画面观察：\n${observationsToText(body.observations) || "（无）"}` +
      (contradictionText ? `\n\n通话中已实时检测到的与历史档案不符之处：\n${contradictionText}` : "");
    const upstream = await fetch(`${baseUrl}/chat/completions`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
      body: JSON.stringify({
        model,
        thinking: { type: "disabled" },
        messages: [
          { role: "system", content: RISK_SUMMARY_PROMPT },
          { role: "user", content: userContent }
        ]
      })
    });
    if (upstream.ok) {
      const data = await upstream.json();
      const parsed = parseJson(extractJsonObject(data.choices?.[0]?.message?.content || ""));
      if (parsed && typeof parsed === "object") {
        if (["low", "medium", "high"].includes(parsed.level)) result.level = parsed.level;
        if (Array.isArray(parsed.reasons)) result.reasons = parsed.reasons.filter((r) => typeof r === "string" && r).slice(0, 5);
      }
    }
  } catch {
    // best-effort：AI 总结失败就用规则结论
  }

  return sendJson(res, 200, result);
}

// ============ 视频通话·实时矛盾检测 /api/contradiction-check（记忆锚点比对，ARK） ============
//
// 把"已知客户档案/流水（记忆锚点）"与用户当前这句口述交给文本模型，判断是否
// 明确矛盾。判定逻辑放在这条确定性旁路里，实时语音模型只负责自然话术。

const CONTRADICTION_PROMPT = [
  "你是微众银行小微信贷的实时风控比对器，正在一通视频尽调通话中运行。",
  "下面给你：①这家企业的【已知档案】（历史风控画像、待核验点、系统流水事实——这是可信基线）；②用户在视频里【刚说的话】；③通话的最近上下文。",
  "你的唯一任务：判断【刚说的话】是否与【已知档案】或前文出现**明确、具体**的矛盾/不符（如金额、用途、店名、证件号、经营时间、人数规模等对不上）。",
  "严格要求：只报你有把握的明确矛盾，宁可漏报不可误报；模糊、可并存、信息不足的一律不报；绝不臆测档案里没有的内容。",
  '严格输出 JSON：{"contradictions":[{"field":"矛盾涉及的要素","stated":"用户这次的说法","known":"档案/前文里的已知值","nudge":"一句客户经理可以自然说出口、不指控、给台阶的核对话"}]}。没有明确矛盾就输出 {"contradictions":[]}。',
  "nudge 用‘帮我对一下口径’式的温和措辞，例如：‘您前面提到月流水大概三十万，刚说到的是十万左右，我这边核一下口径，是不是分了不同账户呀？’"
].join("\n");

async function handleContradictionCheck(req, res) {
  const body = await readJsonBody(req);
  const memory = String(body.memory || "").slice(0, 6000).trim();
  const utterance = String(body.utterance || "").slice(0, 1500).trim();
  const recent = String(body.recent || "").slice(0, 2000).trim();
  const apiKey = process.env.ARK_API_KEY;

  // 没有记忆基线 / 没有口述 / 没凭证 → 无从比对，返回空。
  if (!apiKey || !memory || !utterance) {
    return sendJson(res, 200, { contradictions: [] });
  }

  try {
    const baseUrl = (process.env.ARK_BASE_URL || "https://ark.cn-beijing.volces.com/api/v3").replace(/\/+$/, "");
    const model = process.env.ARK_TEXT_MODEL || process.env.ARK_VISION_MODEL || "doubao-seed-2-0-mini-260428";
    const userContent =
      `【已知档案】\n${memory}\n\n【最近上下文】\n${recent || "（无）"}\n\n【用户刚说的话】\n${utterance}`;
    const upstream = await fetch(`${baseUrl}/chat/completions`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
      body: JSON.stringify({
        model,
        thinking: { type: "disabled" },
        messages: [
          { role: "system", content: CONTRADICTION_PROMPT },
          { role: "user", content: userContent }
        ]
      })
    });
    if (!upstream.ok) return sendJson(res, 200, { contradictions: [] });
    const data = await upstream.json();
    const parsed = parseJson(extractJsonObject(data.choices?.[0]?.message?.content || ""));
    const list = Array.isArray(parsed?.contradictions) ? parsed.contradictions : [];
    const contradictions = list
      .filter((c) => c && typeof c === "object" && (c.field || c.stated || c.known))
      .slice(0, 3)
      .map((c) => ({
        field: String(c.field || "").slice(0, 120),
        stated: String(c.stated || "").slice(0, 300),
        known: String(c.known || "").slice(0, 300),
        nudge: String(c.nudge || "").slice(0, 300)
      }));
    return sendJson(res, 200, { contradictions });
  } catch {
    return sendJson(res, 200, { contradictions: [] });
  }
}

// ============ 共用工具 ============

function readJsonBody(req) {
  return new Promise((resolve) => {
    let raw = "";
    req.on("data", (chunk) => {
      raw += chunk;
    });
    req.on("end", () => resolve(parseJson(raw) || {}));
    req.on("error", () => resolve({}));
  });
}

function sendJson(res, status, payload) {
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Access-Control-Allow-Origin": "*" });
  res.end(JSON.stringify(payload));
}

function hasRealtimeCredentials() {
  return Boolean((APP_ID && ACCESS_KEY) || API_KEY);
}

function buildUpstreamHeaders(connectId) {
  const headers = {
    "X-Api-Resource-Id": RESOURCE_ID,
    "X-Api-App-Key": APP_KEY,
    "X-Api-Connect-Id": connectId
  };
  if (APP_ID && ACCESS_KEY) {
    headers["X-Api-App-ID"] = APP_ID;
    headers["X-Api-Access-Key"] = ACCESS_KEY;
  } else if (API_KEY) {
    headers["X-Api-Key"] = API_KEY;
  }
  return headers;
}

function parseScene(request) {
  try {
    const scene = new URL(request.url, "http://localhost").searchParams.get("scene");
    return scene === "video" ? "video" : "voice"; // 默认纯语音，避免未知客户端误用视频人设
  } catch {
    return "voice";
  }
}

function createSessionConfig(systemRole) {
  return {
    tts: {
      speaker: process.env.DOUBAO_REALTIME_TTS_SPEAKER || "zh_female_vv_jupiter_bigtts",
      audio_config: { format: "pcm_s16le", sample_rate: 24000, channel: 1, speech_rate: 0, loudness_rate: 0 },
      extra: {}
    },
    asr: {
      audio_info: { format: "pcm", sample_rate: 16000, channel: 1 },
      extra: { end_smooth_window_ms: 600, enable_custom_vad: false, enable_asr_twopass: true }
    },
    dialog: {
      bot_name: "微众小微贷",
      system_role: systemRole,
      speaking_style: "口语化、自然、亲和，一次只说一两句，简短不啰嗦。",
      dialog_id: "",
      extra: {
        strict_audit: true,
        input_mod: INPUT_MOD,
        enable_loudness_norm: true,
        enable_conversation_truncate: true,
        enable_user_query_exit: true,
        model: MODEL_VERSION
      }
    }
  };
}

function makeFullClientFrame(event, payload, sessionId) {
  const payloadBytes = Buffer.from(JSON.stringify(payload || {}), "utf8");
  const parts = [Buffer.from([0x11, 0x14, 0x10, 0x00]), uint32(event)];
  if (sessionId) {
    const sessionBytes = Buffer.from(sessionId, "utf8");
    parts.push(uint32(sessionBytes.length), sessionBytes);
  }
  parts.push(uint32(payloadBytes.length), payloadBytes);
  return Buffer.concat(parts);
}

function makeAudioFrame(audioBytes, sessionId) {
  const sessionBytes = Buffer.from(sessionId, "utf8");
  return Buffer.concat([
    Buffer.from([0x11, 0x24, 0x00, 0x00]),
    uint32(EVENT_SEND.TaskRequest),
    uint32(sessionBytes.length),
    sessionBytes,
    uint32(audioBytes.length),
    audioBytes
  ]);
}

function decodeDoubaoFrame(data) {
  const buffer = Buffer.isBuffer(data) ? data : Buffer.from(data);
  if (buffer.length < 8) return null;

  const headerSize = (buffer[0] & 0x0f) * 4;
  const messageType = buffer[1] >> 4;
  const flags = buffer[1] & 0x0f;
  const serialization = buffer[2] >> 4;
  const compression = buffer[2] & 0x0f;
  let offset = headerSize;
  let code = null;
  let sequence = null;
  let event = null;
  let session_id = null;

  if (messageType === 0x0f && offset + 4 <= buffer.length) {
    code = buffer.readInt32BE(offset);
    offset += 4;
  }

  if ([0x01, 0x02, 0x03].includes(flags) && offset + 4 <= buffer.length) {
    sequence = buffer.readInt32BE(offset);
    offset += 4;
  }

  if (flags === 0x04 && offset + 4 <= buffer.length) {
    event = buffer.readUInt32BE(offset);
    offset += 4;
  }

  if (event && event >= 100 && offset + 4 <= buffer.length) {
    const maybeSessionLength = buffer.readUInt32BE(offset);
    if (maybeSessionLength > 0 && maybeSessionLength <= 128 && offset + 4 + maybeSessionLength + 4 <= buffer.length) {
      const maybeSessionId = buffer.subarray(offset + 4, offset + 4 + maybeSessionLength).toString("utf8");
      if (/^[\w-]{8,128}$/.test(maybeSessionId)) {
        session_id = maybeSessionId;
        offset += 4 + maybeSessionLength;
      }
    }
  }

  if (offset + 4 > buffer.length) {
    return { messageType, flags, serialization, compression, code, sequence, event, session_id, payload: Buffer.alloc(0) };
  }

  const payloadSize = buffer.readUInt32BE(offset);
  offset += 4;
  const payload = buffer.subarray(offset, offset + payloadSize);

  return {
    messageType,
    flags,
    serialization,
    compression,
    code,
    sequence,
    event,
    session_id,
    payload,
    json: serialization === 0x01 ? parseJson(payload.toString("utf8")) : null
  };
}

function translateDoubaoFrame(frame) {
  const payloads = [];
  const data = frame.json || {};

  if (frame.messageType === 0x0f || frame.event === EVENT_RECEIVE.DialogCommonError) {
    payloads.push({
      type: "proxy.error",
      event: frame.event,
      code: frame.code,
      message: data.error || data.message || "豆包实时语音返回错误。",
      detail: data
    });
    return payloads;
  }

  if (frame.event === EVENT_RECEIVE.ConnectionStarted) {
    payloads.push({ type: "proxy.upstream_connection_started" });
  } else if (frame.event === EVENT_RECEIVE.SessionStarted) {
    payloads.push({ type: "proxy.upstream_session_started", dialog_id: data.dialog_id || "" });
  } else if (frame.event === EVENT_RECEIVE.ASRResponse) {
    // 用户开口 → 通知前端停播 AI（打断）
    payloads.push({ type: "input_audio_buffer.speech_started" });
    const text = (data.results || []).map((item) => item.text).filter(Boolean).join("");
    if (text) payloads.push({ type: "input_audio_transcription.delta", delta: text, is_interim: Boolean(data.results?.some((item) => item.is_interim)) });
  } else if (frame.event === EVENT_RECEIVE.ChatResponse) {
    if (data.content) payloads.push({ type: "response.text.delta", delta: data.content, question_id: data.question_id, reply_id: data.reply_id });
  } else if (frame.event === EVENT_RECEIVE.TTSSubtitle) {
    if (data.text) payloads.push({ type: "response.audio_transcript.delta", delta: data.text });
  } else if (frame.event === EVENT_RECEIVE.TTSResponse) {
    payloads.push({ type: "response.audio.delta", audio: frame.payload.toString("base64"), encoding: "pcm_s16le", sample_rate: 24000 });
  } else if (frame.event === EVENT_RECEIVE.ASREnded) {
    payloads.push({ type: "input_audio_transcription.done", detail: data });
  } else if (frame.event === EVENT_RECEIVE.ChatEnded || frame.event === EVENT_RECEIVE.TTSEnded) {
    payloads.push({ type: "response.done", event: frame.event, detail: data });
  } else if (frame.event === EVENT_RECEIVE.SessionFailed || frame.event === EVENT_RECEIVE.ConnectionFailed) {
    payloads.push({ type: "proxy.error", event: frame.event, message: data.error || data.message || "豆包实时语音会话失败。", detail: data });
  } else if (frame.event) {
    payloads.push({ type: "proxy.event", event: frame.event, detail: data });
  }

  return payloads;
}

function isFailureEvent(event) {
  return event === EVENT_RECEIVE.ConnectionFailed || event === EVENT_RECEIVE.SessionFailed || event === EVENT_RECEIVE.SessionCanceled;
}

function uint32(value) {
  const buffer = Buffer.alloc(4);
  buffer.writeUInt32BE(value);
  return buffer;
}

function bindMockSession(client, sessionId) {
  client.on("message", (data) => {
    const payload = parseJson(data.toString("utf8"));
    if (payload?.type === "input_audio_buffer.commit" || payload?.type === "conversation.item.create" || payload?.type === "input_text") {
      safeSend(client, {
        type: "response.text.delta",
        delta: "我听到了。我们先从经营场所、主营业务和近期流水三个方面完成核验。"
      });
      safeSend(client, { type: "response.done", session_id: sessionId });
    }
  });
}

function safeSend(socket, payload) {
  if (socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(payload));
  }
}

function parseJson(value) {
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

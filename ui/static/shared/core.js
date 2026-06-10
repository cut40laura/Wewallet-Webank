/*
 * shared/core.js — 业务核心层（桌面端 / 手机端共用）。
 *
 * 职责：全局状态 state、网络请求、SSE 流式聊天、画像轮询、钱包/贷款/账户数据加载。
 * 规则：本文件禁止直接操作 DOM。所有需要界面响应的地方，一律 Core.emit(事件)，
 * 由各端 view（chat.js）注册监听后自行渲染。改动会同时影响两端，改前先打招呼。
 *
 * 事件契约（view 必须按需订阅）：
 *   "messages"        消息列表变化 → 重渲染消息流
 *   "busy"            发送中状态变化 → 启用/禁用输入区
 *   "attachments"     待发送附件变化 → 重渲染附件预览
 *   "auth"            登录/企业绑定状态变化 → 重渲染登录态相关 UI
 *   "account-profile" 账户资料加载/更新 → 回填账户表单
 *   "wallet"          钱包数据变化 → 重渲染钱包面板
 *   "wallet-pending"  待确认流水变化 → 重渲染确认条
 *   "profile-markdown" (text) 画像 MD 内容 → 渲染画像抽屉正文
 *   "profile-status"   (text) 画像状态一句话 → 显示在画像抽屉摘要位
 *   "profile-diff"     ({diff, changed, hidden}) 画像变更记录
 *   "notify"           (text) 需要弹给用户的提示（view 决定 alert 还是 toast）
 *
 * 依赖：shared/format.js（sanitizeVisibleText、attachmentKind、isThinkingStatus）。
 * 加载顺序：format.js → core.js → 各端 view。
 */

const state = {
  messages: [],
  attachments: [],
  busy: false,
  recorder: null,
  recordingChunks: [],
  voiceMeter: null,
  auth: null,
  loginMode: "password",
  accountProfile: null,
  wallet: null,
  walletPeriod: "day",
  walletChartMode: "bar",
  walletPending: [],
  walletPendingBusyIds: new Set(),
  profilePollTimer: null,
  profileLastUpdatedAt: "",
};

const Core = (() => {
  const listeners = new Map();

  function on(event, handler) {
    if (!listeners.has(event)) listeners.set(event, []);
    listeners.get(event).push(handler);
  }

  function emit(event, payload) {
    for (const handler of listeners.get(event) || []) {
      try {
        handler(payload);
      } catch (error) {
        console.error(`Core listener for "${event}" failed:`, error);
      }
    }
  }

  return { on, emit };
})();

async function postJson(path, body = {}) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "请求失败");
  }
  return payload;
}

async function getJson(path) {
  const response = await fetch(path);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "请求失败");
  }
  return payload;
}

Core.setBusy = (value) => {
  state.busy = value;
  Core.emit("busy", value);
};

Core.setAuth = (auth) => {
  state.auth = auth || { authenticated: false };
  Core.emit("auth");
};

// ---------- 附件（待发送区） ----------

Core.addAttachment = (file) => {
  const kind = attachmentKind(file);
  const id = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  state.attachments.push({
    id,
    file,
    kind,
    name: file.name || (kind === "audio" ? "voice.webm" : kind),
    size: file.size || 0,
    type: file.type || "",
    url: URL.createObjectURL(file),
  });
  Core.emit("attachments");
};

Core.clearAttachments = () => {
  for (const attachment of state.attachments) {
    if (attachment.url && attachment.url.startsWith("blob:")) URL.revokeObjectURL(attachment.url);
  }
  state.attachments = [];
  Core.emit("attachments");
};

Core.removeAttachment = (id) => {
  const attachment = state.attachments.find((item) => item.id === id);
  if (attachment?.url?.startsWith("blob:")) URL.revokeObjectURL(attachment.url);
  state.attachments = state.attachments.filter((item) => item.id !== id);
  Core.emit("attachments");
};

// ---------- 消息流 ----------

Core.loadMessages = async () => {
  const payload = await getJson("/api/messages");
  state.messages = payload.messages || [];
  Core.emit("messages");
  void Core.ensureLatestSuggestions();
};

Core.ensureLatestSuggestions = async () => {
  if (state.busy || !state.messages.length) return;
  const latestAssistant = [...state.messages].reverse().find((message) => (
    message.role === "assistant" &&
    String(message.content || "").trim() &&
    !Array.isArray(message.suggestions)
  ));
  if (!latestAssistant) return;
  try {
    const payload = await postJson("/api/messages/suggestions");
    if (Array.isArray(payload.messages)) {
      state.messages = payload.messages;
      Core.emit("messages");
    }
  } catch (error) {
    // Recommendation chips are helpful, but chat history should still render normally.
  }
};

function lastAssistantMessage() {
  return state.messages[state.messages.length - 1];
}

function appendUniqueProgress(message, text) {
  if (!message) return;
  const value = typeof text === "object" ? text : sanitizeVisibleText(text);
  if (!value) return;
  message.progress = Array.isArray(message.progress) ? message.progress : [];
  const previous = message.progress[message.progress.length - 1];
  const previousText = typeof previous === "object" ? previous.text : previous;
  const nextText = typeof value === "object" ? value.text : value;
  if (previousText !== nextText) {
    message.progress.push(value);
  }
}

function applyChatStreamEvent(event) {
  const message = lastAssistantMessage();
  if (!message || message.role !== "assistant") return;
  const payload = event.payload || {};
  if (event.type === "assistant.start") {
    message.content = payload.content || message.content || "正在分析客户需求...";
  } else if (event.type === "progress.delta") {
    appendUniqueProgress(message, payload.text || "");
  } else if (event.type === "tool.generating") {
    appendUniqueProgress(message, { type: event.type, name: payload.name || "", text: `preparing ${payload.name || "tool"}...` });
  } else if (event.type === "tool.progress") {
    appendUniqueProgress(message, { type: event.type, name: payload.name || "", text: payload.preview || payload.text || payload.name || "" });
  } else if (event.type === "tool.start") {
    appendUniqueProgress(message, { type: event.type, name: payload.name || "", text: `started ${payload.name || "tool"}` });
  } else if (event.type === "tool.complete") {
    const duration = typeof payload.duration_s === "number" ? ` ${payload.duration_s.toFixed(1)}s` : "";
    const status = payload.error ? "error" : "complete";
    const text = payload.error
      ? `${status} ${payload.name || "tool"}${duration}: ${payload.error}`
      : `${status} ${payload.name || "tool"}${duration}`;
    appendUniqueProgress(message, { type: event.type, name: payload.name || "", status, text });
    if (payload.inline_diff) {
      message.inline_diffs = Array.isArray(message.inline_diffs) ? message.inline_diffs : [];
      message.inline_diffs.push(payload.inline_diff);
    }
  } else if (event.type === "status.update") {
    appendUniqueProgress(message, { type: event.type, status: payload.kind || "", text: payload.text || "" });
  } else if (event.type === "thinking.delta" || event.type === "reasoning.delta") {
    const text = String(payload.text || "");
    if (text) {
      message.thinking = `${message.thinking || ""}${text}`;
      // Only thinking.delta carries short status pings (e.g. "(⊙_⊙) deliberating...").
      // reasoning.delta streams the model's chain-of-thought token-by-token; those
      // tokens are short and newline-free, so they must NOT be shown as progress —
      // otherwise the whole reasoning leaks into the live progress ticker.
      if (event.type === "thinking.delta" && isThinkingStatus(text)) {
        appendUniqueProgress(message, { type: event.type, name: "Hermes", text });
      }
    }
  } else if (event.type === "reasoning.available") {
    return;
  } else if (event.type === "message.delta") {
    const text = String(payload.text || "");
    if (text) {
      if (message.content === "正在分析客户需求...") message.content = "";
      message.content = `${message.content || ""}${text}`;
    }
  } else if (event.type === "message.complete") {
    state.messages = payload.messages || state.messages;
    if (Array.isArray(payload.wallet_pending)) {
      state.walletPending = payload.wallet_pending;
      Core.emit("wallet-pending");
    }
    if (payload.auto_profile?.scheduled) {
      Core.emit("profile-status", `已自动开始更新风控画像（第 ${payload.auto_profile.user_turn_count} 轮），稍后会自动刷新...`);
      Core.startProfilePolling();
    } else if (payload.auto_profile?.in_progress) {
      Core.startProfilePolling();
    }
  } else if (event.type === "error") {
    throw new Error(payload.error || payload.message || "调用失败");
  }
}

async function postStreamingChat(message, attachments = []) {
  const body = new FormData();
  body.append("message", message);
  for (const attachment of attachments) {
    if (attachment.file) body.append("attachments", attachment.file, attachment.name || attachment.file.name);
  }
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    body,
  });
  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || "请求失败");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let completed = false;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line);
      applyChatStreamEvent(event);
      if (event.type === "message.complete") completed = true;
      Core.emit("messages");
    }
  }

  const tail = buffer.trim();
  if (tail) {
    const event = JSON.parse(tail);
    applyChatStreamEvent(event);
    if (event.type === "message.complete") completed = true;
    Core.emit("messages");
  }

  const assistant = lastAssistantMessage();
  if (assistant && assistant.role === "assistant") {
    assistant.streaming = false;
  }
  if (!completed) {
    appendUniqueProgress(assistant, "本轮连接已结束，未收到完成事件。");
  }
}

// 守卫不通过（空内容 / 正在发送）返回 null；否则立刻乐观渲染并返回发送 Promise，
// view 可据此同步清空输入框。
Core.sendMessage = (content) => {
  const text = String(content || "").trim();
  const attachments = [...state.attachments];
  if ((!text && !attachments.length) || state.busy) return null;
  return (async () => {
    const optimisticAttachments = attachments.map((item) => ({
      kind: item.kind,
      name: item.name,
      size: item.size,
      type: item.type,
      url: item.url,
    }));
    state.messages.push({ role: "user", content: text, attachments: optimisticAttachments });
    state.messages.push({ role: "assistant", content: "正在分析客户需求...", thinking: "", progress: [], inline_diffs: [], streaming: true });
    Core.emit("messages");
    state.attachments = [];
    Core.emit("attachments");
    Core.setBusy(true);
    try {
      await postStreamingChat(text, attachments);
      Core.emit("messages");
    } catch (error) {
      state.messages[state.messages.length - 1] = {
        role: "assistant",
        content: `调用失败：${error.message}`,
      };
      Core.emit("messages");
    } finally {
      for (const attachment of attachments) {
        if (attachment.url && attachment.url.startsWith("blob:")) URL.revokeObjectURL(attachment.url);
      }
      Core.setBusy(false);
    }
  })();
};

// ---------- 风控画像 ----------

Core.loadProfile = async () => {
  if (!state.auth?.authenticated || state.auth?.needs_enterprise) return null;
  try {
    const response = await fetch("/api/profile");
    const payload = await response.json();
    Core.emit("profile-markdown", payload.markdown || "暂无画像。");
    const profileState = payload.state || {};
    state.profileLastUpdatedAt = profileState.last_profile_updated_at || state.profileLastUpdatedAt || "";
    if (profileState.in_progress) {
      Core.emit("profile-status", "企业画像正在后台更新，稍后会自动刷新...");
      Core.startProfilePolling();
    } else if (profileState.last_error) {
      Core.emit("profile-status", `上次更新失败：${profileState.last_error}`);
    } else {
      Core.emit("profile-status", "查看当前企业的 MD 档案，画像会随对话自动更新。");
    }
    Core.emit("profile-diff", { diff: "", changed: false, hidden: true });
    return payload;
  } catch (error) {
    Core.emit("profile-status", `读取失败：${error.message}`);
    return null;
  }
};

Core.startProfilePolling = () => {
  if (state.profilePollTimer) return;
  const baselineUpdatedAt = state.profileLastUpdatedAt || "";
  const startedAt = Date.now();
  const tick = async () => {
    try {
      const response = await fetch("/api/profile");
      const payload = await response.json();
      const profileState = payload.state || {};
      const updatedAt = profileState.last_profile_updated_at || "";
      const finished = !profileState.in_progress && updatedAt && updatedAt !== baselineUpdatedAt;
      if (finished) {
        Core.emit("profile-markdown", payload.markdown || "暂无画像。");
        state.profileLastUpdatedAt = updatedAt;
        Core.emit("profile-status", profileState.last_profile_changed
          ? "企业画像已更新。"
          : "企业画像本轮无新增变更。");
        Core.stopProfilePolling();
        return;
      }
      if (profileState.last_error && !profileState.in_progress) {
        Core.emit("profile-status", `更新失败：${profileState.last_error}`);
        Core.stopProfilePolling();
        return;
      }
      if (Date.now() - startedAt > 5 * 60 * 1000) {
        Core.emit("profile-status", "画像更新仍在进行，请稍后手动刷新。");
        Core.stopProfilePolling();
      }
    } catch (error) {
      Core.emit("profile-status", `轮询失败：${error.message}`);
      Core.stopProfilePolling();
    }
  };
  state.profilePollTimer = window.setInterval(tick, 3000);
  tick();
};

Core.stopProfilePolling = () => {
  if (state.profilePollTimer) {
    window.clearInterval(state.profilePollTimer);
    state.profilePollTimer = null;
  }
};

Core.refreshProfile = async () => {
  if (!state.auth?.authenticated || state.auth?.needs_enterprise) return;
  Core.emit("profile-status", "正在检查画像状态...");
  try {
    const response = await fetch("/api/profile/refresh", { method: "POST" });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "刷新失败");
    }
    const message = payload.message || "";
    if (message) Core.emit("profile-status", message);
    const profileState = payload.state || {};
    state.profileLastUpdatedAt = profileState.last_profile_updated_at || state.profileLastUpdatedAt || "";
    if (payload.status === "in_progress") {
      Core.startProfilePolling();
    } else {
      await Core.loadProfile();
      if (message) Core.emit("profile-status", message);
    }
  } catch (error) {
    Core.emit("profile-status", `刷新失败：${error.message}`);
  }
};

// ---------- 钱包 ----------

Core.setWallet = (payload) => {
  state.wallet = payload || state.wallet || { transactions: [], summary: {} };
  Core.emit("wallet");
};

Core.loadWallet = async () => {
  if (!state.auth?.authenticated || state.auth?.needs_enterprise) return;
  Core.setWallet(await getJson("/api/wallet"));
};

Core.loadWalletPending = async () => {
  if (!state.auth?.authenticated || state.auth?.needs_enterprise) return;
  try {
    const response = await fetch("/api/wallet/pending");
    if (!response.ok) return;
    const payload = await response.json();
    state.walletPending = payload.pending || [];
    Core.emit("wallet-pending");
  } catch (_) {
    // silent — refreshed on next chat / page load
  }
};

Core.resolveWalletPending = async (pendingId, action) => {
  if (!pendingId || state.walletPendingBusyIds.has(pendingId)) return;
  state.walletPendingBusyIds.add(pendingId);
  Core.emit("wallet-pending");
  try {
    const response = await fetch(`/api/wallet/pending/${encodeURIComponent(pendingId)}/${action}`, {
      method: "POST",
    });
    const payload = await response.json();
    if (!response.ok) {
      Core.emit("notify", payload.error || `${action === "confirm" ? "确认" : "拒绝"}失败`);
      state.walletPending = state.walletPending.filter((item) => item.id !== pendingId);
    } else {
      state.walletPending = payload.pending || [];
      if (payload.transactions) {
        Core.setWallet({ transactions: payload.transactions, summary: payload.summary });
      }
    }
  } catch (error) {
    Core.emit("notify", `网络错误：${error.message}`);
  } finally {
    state.walletPendingBusyIds.delete(pendingId);
    Core.emit("wallet-pending");
  }
};

// ---------- 账户资料 ----------

Core.loadAccountProfile = async () => {
  if (!state.auth?.authenticated || state.auth?.needs_enterprise) return null;
  const payload = await getJson("/api/account/profile");
  state.accountProfile = payload.profile || null;
  Core.emit("account-profile");
  Core.emit("auth");
  return state.accountProfile;
};

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

const SHOW_INTERNAL_PANELS = localStorage.getItem("wewallet.showInternalPanels") === "1";
const appShell = document.querySelector(".app-shell");
const messageList = document.getElementById("messageList");
const composerForm = document.getElementById("composerForm");
const messageInput = document.getElementById("messageInput");
const sendButton = document.getElementById("sendButton");
const imageButton = document.getElementById("imageButton");
const attachmentPopover = document.getElementById("attachmentPopover");
const pickImageButton = document.getElementById("pickImageButton");
const pickFileButton = document.getElementById("pickFileButton");
const pickVideoButton = document.getElementById("pickVideoButton");
const imageInput = document.getElementById("imageInput");
const fileInput = document.getElementById("fileInput");
const videoInput = document.getElementById("videoInput");
const micButton = document.getElementById("micButton");
const attachmentPreview = document.getElementById("attachmentPreview");
const messageTemplate = document.getElementById("messageTemplate");
const walletPendingBar = document.getElementById("walletPendingBar");
const walletPendingList = document.getElementById("walletPendingList");
const walletPendingCount = document.getElementById("walletPendingCount");
const openProfileButton = document.getElementById("openProfileButton");
const openWalletButton = document.getElementById("openWalletButton");
const openLoanButton = document.getElementById("openLoanButton");
const openVideoCallButton = document.getElementById("openVideoCallButton");
const mobileMenuButton = document.getElementById("mobileMenuButton");
const openVoiceCallButton = document.getElementById("openVoiceCallButton");
const closeProfileButton = document.getElementById("closeProfileButton");
const refreshProfileButton = document.getElementById("refreshProfileButton");
const profileBackdrop = document.getElementById("profileBackdrop");
const profileDrawer = document.getElementById("profileDrawer");
const profileMarkdown = document.getElementById("profileMarkdown");
const profileSummary = document.getElementById("profileSummary");
const profileDiffDetails = document.getElementById("profileDiffDetails");
const profileDiff = document.getElementById("profileDiff");
const walletBackdrop = document.getElementById("walletBackdrop");
const walletDrawer = document.getElementById("walletDrawer");
const closeWalletButton = document.getElementById("closeWalletButton");
const importWalletButton = document.getElementById("importWalletButton");
const addWalletEntryButton = document.getElementById("addWalletEntryButton");
const walletCsvInput = document.getElementById("walletCsvInput");
const walletEntryForm = document.getElementById("walletEntryForm");
const walletDate = document.getElementById("walletDate");
const walletType = document.getElementById("walletType");
const walletAmount = document.getElementById("walletAmount");
const walletCategory = document.getElementById("walletCategory");
const walletDescription = document.getElementById("walletDescription");
const walletPeriodTabs = Array.from(document.querySelectorAll(".wallet-period-tab"));
const walletChartModeButtons = Array.from(document.querySelectorAll(".wallet-chart-mode"));
const walletSummary = document.getElementById("walletSummary");
const walletChart = document.getElementById("walletChart");
const walletPlan = document.getElementById("walletPlan");
const walletTransactions = document.getElementById("walletTransactions");
const walletMessage = document.getElementById("walletMessage");
const loanBackdrop = document.getElementById("loanBackdrop");
const loanModal = document.getElementById("loanModal");
const closeLoanButton = document.getElementById("closeLoanButton");
const refreshLoanButton = document.getElementById("refreshLoanButton");
const loanUpdatedAt = document.getElementById("loanUpdatedAt");
const loanBody = document.getElementById("loanBody");
const loanMessage = document.getElementById("loanMessage");
const sidebarToggleButton = document.getElementById("sidebarToggleButton");
const authScreen = document.getElementById("authScreen");
const loginForm = document.getElementById("loginForm");
const registerForm = document.getElementById("registerForm");
const enterpriseForm = document.getElementById("enterpriseForm");
const loginPhone = document.getElementById("loginPhone");
const loginPassword = document.getElementById("loginPassword");
const loginCode = document.getElementById("loginCode");
const loginPasswordField = document.getElementById("loginPasswordField");
const loginSmsField = document.getElementById("loginSmsField");
const passwordLoginTab = document.getElementById("passwordLoginTab");
const smsLoginTab = document.getElementById("smsLoginTab");
const sendLoginCodeButton = document.getElementById("sendLoginCodeButton");
const openRegisterButton = document.getElementById("openRegisterButton");
const backToLoginButton = document.getElementById("backToLoginButton");
const registerPhone = document.getElementById("registerPhone");
const registerPassword = document.getElementById("registerPassword");
const registerCode = document.getElementById("registerCode");
const sendRegisterCodeButton = document.getElementById("sendRegisterCodeButton");
const enterpriseName = document.getElementById("enterpriseName");
const enterpriseCreditCode = document.getElementById("enterpriseCreditCode");
const authMessage = document.getElementById("authMessage");
const accountButton = document.getElementById("accountButton");
const accountAvatar = document.getElementById("accountAvatar");
const accountLabel = document.getElementById("accountLabel");
const sessionStatus = document.getElementById("sessionStatus");
const accountBackdrop = document.getElementById("accountBackdrop");
const accountModal = document.getElementById("accountModal");
const closeAccountButton = document.getElementById("closeAccountButton");
const avatarUploadButton = document.getElementById("avatarUploadButton");
const avatarInput = document.getElementById("avatarInput");
const profileAvatarPreview = document.getElementById("profileAvatarPreview");
const accountTabUser = document.getElementById("accountTabUser");
const accountTabEnterprise = document.getElementById("accountTabEnterprise");
const accountUserPanel = document.getElementById("accountUserPanel");
const accountEnterprisePanel = document.getElementById("accountEnterprisePanel");
const accountProfileForm = document.getElementById("accountProfileForm");
const accountProfileMessage = document.getElementById("accountProfileMessage");
const logoutButton = document.getElementById("logoutButton");
const profilePhone = document.getElementById("profilePhone");
const profileNickname = document.getElementById("profileNickname");
const profileRole = document.getElementById("profileRole");
const accountEnterpriseFields = {
  name: document.getElementById("profileEnterpriseName"),
  credit_code: document.getElementById("profileCreditCode"),
  legal_representative: document.getElementById("profileLegalRepresentative"),
  city: document.getElementById("profileCity"),
  address: document.getElementById("profileAddress"),
  industry: document.getElementById("profileIndustry"),
  main_business: document.getElementById("profileMainBusiness"),
  established_at: document.getElementById("profileEstablishedAt"),
  business_years: document.getElementById("profileBusinessYears"),
  enterprise_type: document.getElementById("profileEnterpriseType"),
  annual_revenue: document.getElementById("profileAnnualRevenue"),
  employee_count: document.getElementById("profileEmployeeCount"),
  monthly_cashflow: document.getElementById("profileMonthlyCashflow"),
  has_corporate_account: document.getElementById("profileHasCorporateAccount"),
  payment_channels: document.getElementById("profilePaymentChannels"),
  has_tax_record: document.getElementById("profileHasTaxRecord"),
  has_social_security: document.getElementById("profileHasSocialSecurity"),
  funding_purpose: document.getElementById("profileFundingPurpose"),
  expected_amount: document.getElementById("profileExpectedAmount"),
  expected_term: document.getElementById("profileExpectedTerm"),
};
const DEFAULT_MESSAGE_PLACEHOLDER = "请输入您的经营情况、资金需求或材料问题";
const MOBILE_MESSAGE_PLACEHOLDER = "输入消息";

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function escapeAttribute(value) {
  return escapeHtml(value).replaceAll('"', "&quot;");
}

function renderInlineMarkdown(value) {
  let text = escapeHtml(value);
  const codeSpans = [];
  text = text.replace(/`([^`]+)`/g, (_match, code) => {
    const token = `\u0000CODE${codeSpans.length}\u0000`;
    codeSpans.push(`<code>${code}</code>`);
    return token;
  });
  text = text
    .replace(/\*\*([^*\n][\s\S]*?[^*\n])\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_\n][\s\S]*?[^_\n])__/g, "<strong>$1</strong>")
    .replace(/\*([^*\n]+)\*/g, "<em>$1</em>")
    .replace(/_([^_\n]+)_/g, "<em>$1</em>");
  return text.replace(/\u0000CODE(\d+)\u0000/g, (_match, index) => codeSpans[Number(index)] || "");
}

function splitTableRow(line) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function isTableDivider(line) {
  return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
}

function renderMarkdown(markdown) {
  const lines = String(markdown || "").replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
  const html = [];
  let paragraph = [];
  let listType = "";
  let tableRows = [];
  let inCode = false;
  let codeLang = "";
  let codeLines = [];

  function flushParagraph() {
    if (!paragraph.length) return;
    html.push(`<p>${renderInlineMarkdown(paragraph.join(" "))}</p>`);
    paragraph = [];
  }

  function flushList() {
    if (!listType) return;
    html.push(`</${listType}>`);
    listType = "";
  }

  function flushTable() {
    if (!tableRows.length) return;
    const [head, ...body] = tableRows;
    html.push('<div class="markdown-table-wrap"><table><thead><tr>');
    for (const cell of head) html.push(`<th>${renderInlineMarkdown(cell)}</th>`);
    html.push("</tr></thead>");
    if (body.length) {
      html.push("<tbody>");
      for (const row of body) {
        html.push("<tr>");
        for (const cell of row) html.push(`<td>${renderInlineMarkdown(cell)}</td>`);
        html.push("</tr>");
      }
      html.push("</tbody>");
    }
    html.push("</table></div>");
    tableRows = [];
  }

  function flushCode() {
    if (!inCode) return;
    const langClass = codeLang ? ` class="language-${escapeAttribute(codeLang)}"` : "";
    html.push(`<pre><code${langClass}>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
    inCode = false;
    codeLang = "";
    codeLines = [];
  }

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const trimmed = line.trim();

    if (trimmed.startsWith("```")) {
      if (inCode) {
        flushCode();
      } else {
        flushParagraph();
        flushList();
        flushTable();
        inCode = true;
        codeLang = trimmed.slice(3).trim().split(/\s+/)[0] || "";
      }
      continue;
    }

    if (inCode) {
      codeLines.push(line);
      continue;
    }

    if (!trimmed) {
      flushParagraph();
      flushList();
      flushTable();
      continue;
    }

    const heading = trimmed.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      flushList();
      flushTable();
      const level = heading[1].length;
      html.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }

    if (line.includes("|") && index + 1 < lines.length && isTableDivider(lines[index + 1])) {
      flushParagraph();
      flushList();
      flushTable();
      tableRows.push(splitTableRow(line));
      index += 1;
      continue;
    }

    if (tableRows.length && line.includes("|")) {
      tableRows.push(splitTableRow(line));
      continue;
    }

    const unordered = trimmed.match(/^[-*+]\s+(.+)$/);
    if (unordered) {
      flushParagraph();
      flushTable();
      if (listType !== "ul") {
        flushList();
        listType = "ul";
        html.push("<ul>");
      }
      html.push(`<li>${renderInlineMarkdown(unordered[1])}</li>`);
      continue;
    }

    const ordered = trimmed.match(/^\d+[.)]\s+(.+)$/);
    if (ordered) {
      flushParagraph();
      flushTable();
      if (listType !== "ol") {
        flushList();
        listType = "ol";
        html.push("<ol>");
      }
      html.push(`<li>${renderInlineMarkdown(ordered[1])}</li>`);
      continue;
    }

    const quote = trimmed.match(/^>\s?(.+)$/);
    if (quote) {
      flushParagraph();
      flushList();
      flushTable();
      html.push(`<blockquote>${renderInlineMarkdown(quote[1])}</blockquote>`);
      continue;
    }

    flushTable();
    flushList();
    paragraph.push(trimmed);
  }

  flushCode();
  flushParagraph();
  flushList();
  flushTable();
  return html.join("");
}

function renderMarkdownInto(element, text) {
  const cleanText = sanitizeVisibleText(text);
  element.classList.add("markdown-body");
  element.innerHTML = cleanText ? renderMarkdown(cleanText) : "";
}

function stripUploadRequestFence(value) {
  return String(value || "").replace(/```upload_request\s*\n[\s\S]*?\n```\s*/g, "").trim();
}

function renderUploadRequestCard(message) {
  const request = message?.upload_request;
  if (!request || message.uploadRequestDismissed) return null;
  const card = document.createElement("div");
  card.className = "upload-request-card";
  const header = document.createElement("div");
  header.className = "upload-request-header";
  const icon = document.createElement("span");
  icon.className = "upload-request-icon";
  icon.textContent = "📎";
  const title = document.createElement("span");
  title.className = "upload-request-title";
  title.textContent = "请补充资料";
  header.append(icon, title);
  card.appendChild(header);
  const reason = String(request.reason || "").trim();
  if (reason) {
    const body = document.createElement("div");
    body.className = "upload-request-reason";
    body.textContent = reason;
    card.appendChild(body);
  }
  const items = Array.isArray(request.items) ? request.items : [];
  if (items.length) {
    const list = document.createElement("ul");
    list.className = "upload-request-items";
    for (const item of items) {
      const li = document.createElement("li");
      const name = document.createElement("strong");
      name.textContent = String(item?.name || "").trim() || "材料";
      li.appendChild(name);
      const hint = String(item?.hint || "").trim();
      if (hint) {
        const small = document.createElement("span");
        small.className = "upload-request-hint";
        small.textContent = `· ${hint}`;
        li.appendChild(small);
      }
      list.appendChild(li);
    }
    card.appendChild(list);
  }
  const controls = document.createElement("div");
  controls.className = "upload-request-controls";
  const pickImage = document.createElement("button");
  pickImage.type = "button";
  pickImage.className = "upload-request-button primary";
  pickImage.textContent = "上传图片";
  pickImage.onclick = () => triggerUploadFromCard(message, "image");
  const pickFile = document.createElement("button");
  pickFile.type = "button";
  pickFile.className = "upload-request-button";
  pickFile.textContent = "上传文件";
  pickFile.onclick = () => triggerUploadFromCard(message, "file");
  const later = document.createElement("button");
  later.type = "button";
  later.className = "upload-request-button ghost";
  later.textContent = "稍后再传";
  later.onclick = () => {
    message.uploadRequestDismissed = true;
    renderMessages();
  };
  controls.append(pickImage, pickFile, later);
  card.appendChild(controls);
  return card;
}

function renderSuggestions(message) {
  const suggestions = Array.isArray(message?.suggestions) ? message.suggestions : [];
  const items = suggestions
    .map((item) => String(item || "").trim())
    .filter(Boolean)
    .slice(0, 4);
  if (!items.length) return null;
  const wrap = document.createElement("div");
  wrap.className = "suggestion-chips";
  wrap.setAttribute("aria-label", "推荐问题");
  for (const item of items) {
    const button = document.createElement("button");
    button.className = "suggestion-chip";
    button.type = "button";
    button.textContent = item;
    button.addEventListener("click", () => {
      messageInput.value = item;
      messageInput.style.height = "auto";
      messageInput.style.height = `${Math.min(messageInput.scrollHeight, 180)}px`;
      syncComposerTextState();
      messageInput.focus();
    });
    wrap.appendChild(button);
  }
  return wrap;
}

function triggerUploadFromCard(message, kind) {
  if (state.busy) return;
  message.uploadRequestDismissed = true;
  renderMessages();
  if (kind === "image") {
    imageInput.click();
  } else {
    fileInput.click();
  }
  messageInput.focus();
}

function sanitizeVisibleText(value) {
  let text = String(value || "").trim();
  while (text.includes("<think>") && text.includes("</think>")) {
    const start = text.indexOf("<think>");
    const end = text.indexOf("</think>", start);
    text = `${text.slice(0, start)}${text.slice(end + "</think>".length)}`.trim();
  }
  const prefixes = ["Chain of thought", "Thought process"];
  const lines = text.split("\n");
  const kept = [];
  let skipping = false;
  for (const line of lines) {
    const stripped = line.trim();
    if (prefixes.some((prefix) => stripped.startsWith(prefix))) {
      skipping = true;
      continue;
    }
    if (skipping && (!stripped || stripped.startsWith("最终") || stripped.startsWith("回复") || stripped.startsWith("答案"))) {
      skipping = false;
      const visible = stripped.replace(/^最终回复[:：]?/, "").replace(/^回复[:：]?/, "").replace(/^答案[:：]?/, "").trim();
      if (visible) kept.push(visible);
      continue;
    }
    if (!skipping) kept.push(line);
  }
  return kept.join("\n").trim();
}

function visibleAttachmentText(value, attachments) {
  const text = sanitizeVisibleText(value);
  const items = Array.isArray(attachments) ? attachments.filter(Boolean) : [];
  if (!items.length) return text;
  if (/^\[(图片|视频|文件)附件\]$/.test(text)) return "";
  if (/^\[语音附件[^\]]*\]$/.test(text)) return "";
  const voiceOnly = text.match(/^\[语音\]\s*([\s\S]+)$/);
  if (voiceOnly) return voiceOnly[1].trim();
  return text;
}

const REASONING_TAGS = ["think", "reasoning", "thinking", "thought", "REASONING_SCRATCHPAD"];

function splitReasoning(value) {
  let text = String(value || "");
  const reasoning = [];
  for (const tag of REASONING_TAGS) {
    const paired = new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>\\s*`, "gi");
    text = text.replace(paired, (_match, inner) => {
      const trimmed = String(inner || "").trim();
      if (trimmed) reasoning.push(trimmed);
      return "";
    });

    const unclosed = new RegExp(`<${tag}>([\\s\\S]*)$`, "i");
    text = text.replace(unclosed, (_match, inner) => {
      const trimmed = String(inner || "").trim();
      if (trimmed) reasoning.push(trimmed);
      return "";
    });
  }
  return {
    text: text.trim(),
    reasoning: reasoning.join("\n\n").trim(),
  };
}

function appendDetails(container, className, title, bodyText, open = false) {
  const text = sanitizeVisibleText(bodyText);
  if (!text) return;
  const details = document.createElement("details");
  details.className = className;
  details.open = open;
  const summary = document.createElement("summary");
  summary.textContent = title;
  const body = document.createElement("div");
  body.innerHTML = escapeHtml(text).replaceAll("\n", "<br>");
  details.append(summary, body);
  container.appendChild(details);
}

// 处理过程的线性图标（与界面其余 SVG 风格一致）
const PROC_ICONS = {
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  doc: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
  chart: '<path d="M4 20V10"/><path d="M10 20V4"/><path d="M16 20v-6"/><path d="M3 20h18"/>',
  book: '<path d="M5 4h13v16H6a2 2 0 0 1 0-4h12"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v3"/>',
  image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9.5" r="1.5"/><path d="m21 16-5-5L5 20"/>',
  bulb: '<path d="M9 18h6"/><path d="M10 21h4"/><path d="M12 3a6 6 0 0 0-4 10c.7.7 1 1.6 1 2h6c0-.4.3-1.3 1-2a6 6 0 0 0-4-10Z"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  check: '<path d="m5 12 5 5L20 6"/>',
  alert: '<circle cx="12" cy="12" r="9"/><path d="M12 7v6"/><path d="M12 16.5v.01"/>',
};

function procSvg(key) {
  const inner = PROC_ICONS[key] || PROC_ICONS.clock;
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`;
}

// 步骤类型图标用 emoji（彩色更直观），底色由 tone chip 提供
const PROC_EMOJI = {
  bulb: "💡",
  book: "📚",
  chart: "📊",
  edit: "✏️",
  search: "🔍",
  image: "🖼️",
  mic: "🎙️",
  doc: "📄",
  reply: "💬",
  clock: "⚙️",
};

function procEmoji(key) {
  return PROC_EMOJI[key] || PROC_EMOJI.clock;
}

// 把工具调用翻译成面向小微企业主的业务语言 + 图标
function describeProcStep(item) {
  const tid = String(item.tool_id || "").toLowerCase();
  const name = String(item.name || "");
  const lower = name.toLowerCase();
  const has = (...kw) => kw.some((k) => tid.includes(k) || lower.includes(k));
  if (has("asr") || name.includes("语音")) return { icon: "mic", tone: "orange", label: "识别你的语音" };
  if (has("knowledge") || name.includes("知识库")) return { icon: "book", tone: "indigo", label: "查阅贷款知识库" };
  if (has("image", "图档", "图片")) return { icon: "image", tone: "rose", label: "翻阅历史图档" };
  if (has("profile") || name.includes("画像")) return { icon: "edit", tone: "teal", label: "更新你的经营画像" };
  if (has("wallet") || name.includes("钱包") || name.includes("流水")) return { icon: "chart", tone: "green", label: "分析钱包流水" };
  if (has("write", "edit", "update") || name.includes("更新") || name.includes("写")) return { icon: "edit", tone: "teal", label: "更新你的资料" };
  if (has("search", "grep", "rg") || name.includes("检索") || name.includes("搜索")) return { icon: "search", tone: "blue", label: "检索相关信息" };
  if (has("read", "fetch", "get") || name.includes("查阅") || name.includes("查看") || name.includes("读取")) return { icon: "doc", tone: "blue", label: "查阅资料" };
  // 兜底：中文工具名直接用，否则给通用文案
  const friendly = /[一-龥]/.test(name) ? name : "处理中";
  return { icon: "clock", tone: "gray", label: friendly };
}

// 每条事件 = 一个时间线节点，保留事件原始文本（细粒度，不做工具合并）
function buildProcSteps(items) {
  const steps = [];
  for (const item of items) {
    const data = typeof item === "object" ? item : { text: item };
    const type = String(data.type || "");
    const isThink = /think|reason/i.test(type);
    let label = sanitizeVisibleText(data.text || data.preview || data.name || "");
    if (!label && !isThink) continue;

    // 连续的思考增量合并成同一个“思考”节点，只保留最新的实时状态
    if (isThink) {
      const prev = steps[steps.length - 1];
      if (prev && prev.kind === "think") {
        if (label) prev.live = label;
        continue;
      }
      steps.push({ kind: "think", icon: "bulb", tone: "amber", live: label, label: "", status: "step", dur: "" });
      continue;
    }

    // 工具/其它事件：把结尾的耗时（如 "... 0.8s"）抽出来单独右侧展示
    let dur = "";
    const durMatch = label.match(/\s(\d+(?:\.\d+)?)\s*s$/);
    if (durMatch) {
      const seconds = parseFloat(durMatch[1]);
      dur = seconds < 0.1 ? "<0.1s" : `${durMatch[1]}s`;
      label = label.slice(0, durMatch.index).trim();
    }
    // 把后端的英文前缀换成中文友好表达
    label = label
      .replace(/^started\s+/i, "开始")
      .replace(/^complete\s+/i, "完成")
      .replace(/^preparing\s+/i, "准备")
      .replace(/^generating\s+/i, "准备")
      .replace(/^error\s+/i, "失败 · ")
      .replace(/\.{3}$/, "…");
    let status = "step";
    if (data.status === "error" || type === "error") status = "error";
    else if (type === "tool.complete") status = "done";
    const desc = describeProcStep(data);
    steps.push({ icon: desc.icon, tone: desc.tone, label, status, dur });
  }
  return steps;
}

function appendProgress(container, progress, streaming = false) {
  const items = Array.isArray(progress) ? progress.filter(Boolean) : [];
  if (!items.length) return;
  const steps = buildProcSteps(items);
  if (!steps.length) return;
  // 思考节点默认都显示“思考完成”
  for (const step of steps) {
    if (step.kind === "think") {
      step.label = "思考完成";
      step.status = "done";
    }
  }
  if (streaming) {
    const tail = steps[steps.length - 1];
    if (tail && tail.kind === "think") {
      // 还在思考：显示实时状态，并在其后补“正在回复…”，让 analyzing 落到倒数第二
      tail.label = tail.live || "思考中…";
      tail.status = "step";
      steps.push({ kind: "reply", icon: "reply", tone: "teal", label: "正在回复…", status: "running", dur: "" });
    } else if (tail && tail.status === "step") {
      // 工具仍在进行，给脉冲反馈
      tail.status = "running";
    }
  }
  const lastLabel = steps[steps.length - 1].label;

  const details = document.createElement("details");
  details.className = "proc";
  details.open = streaming;

  const summary = document.createElement("summary");
  summary.className = "proc-summary";
  summary.innerHTML =
    `<span class="proc-chevron"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg></span>` +
    `<span class="proc-title">小微的思考</span>` +
    `<span class="proc-badge">${steps.length} 步</span>` +
    `<span class="proc-last">${escapeHtml(lastLabel)}</span>`;

  const list = document.createElement("ol");
  list.className = "proc-timeline";
  for (const step of steps) {
    const li = document.createElement("li");
    li.className = `proc-step is-${step.status}`;
    const nodeIcon = step.status === "done" ? procSvg("check") : step.status === "error" ? procSvg("alert") : "";
    const dur = step.dur ? `<span class="proc-dur">${escapeHtml(step.dur)}</span>` : "";
    li.innerHTML =
      `<span class="proc-node">${nodeIcon}</span>` +
      `<span class="proc-ico tone-${step.tone || "gray"}">${procEmoji(step.icon)}</span>` +
      `<span class="proc-label">${escapeHtml(step.label)}</span>${dur}`;
    list.appendChild(li);
  }

  details.append(summary, list);
  container.appendChild(details);
}

function isThinkingStatus(text) {
  const value = String(text || "").trim();
  return Boolean(value) && value.length <= 80 && !value.includes("\n");
}

function appendDiffPanels(container, diffs, open = false) {
  const items = Array.isArray(diffs) ? diffs.filter(Boolean) : [];
  if (!items.length) return;
  const details = document.createElement("details");
  details.className = "risk-reasoning diff-details";
  details.open = open;
  const summary = document.createElement("summary");
  summary.textContent = "变更记录";
  details.appendChild(summary);
  for (const diff of items) {
    const pre = document.createElement("pre");
    pre.className = "diff-panel";
    pre.textContent = String(diff || "");
    details.appendChild(pre);
  }
  container.appendChild(details);
}

function fileSizeLabel(size) {
  const value = Number(size || 0);
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value >= 1024) return `${Math.ceil(value / 1024)} KB`;
  return `${value} B`;
}

function moneyLabel(value) {
  return `¥${Number(value || 0).toLocaleString("zh-CN", { maximumFractionDigits: 0 })}`;
}

function parseWalletDate(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!match) return null;
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
}

function walletPeriodLabel(period) {
  return period === "week" ? "周" : period === "month" ? "月" : "日";
}

function walletAnchorDate(transactions) {
  const dates = transactions.map((item) => parseWalletDate(item.date)).filter(Boolean);
  if (!dates.length) return new Date();
  return new Date(Math.max(...dates.map((date) => date.getTime())));
}

function sameWalletDay(left, right) {
  return left.getFullYear() === right.getFullYear()
    && left.getMonth() === right.getMonth()
    && left.getDate() === right.getDate();
}

function walletWeekStart(date) {
  const copy = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const day = copy.getDay() || 7;
  copy.setDate(copy.getDate() - day + 1);
  return copy;
}

function walletDateKey(date, period) {
  if (period === "month") {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
  }
  if (period === "week") {
    const start = walletWeekStart(date);
    return `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, "0")}-${String(start.getDate()).padStart(2, "0")}`;
  }
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function walletBucketLabel(date, period) {
  if (period === "month") return `${date.getMonth() + 1}月`;
  if (period === "week") {
    const start = walletWeekStart(date);
    return `${start.getMonth() + 1}/${start.getDate()}周`;
  }
  return `${date.getMonth() + 1}/${date.getDate()}`;
}

function shiftWalletDate(date, period, offset) {
  const copy = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  if (period === "month") {
    copy.setMonth(copy.getMonth() + offset, 1);
    return copy;
  }
  copy.setDate(copy.getDate() + offset * (period === "week" ? 7 : 1));
  return period === "week" ? walletWeekStart(copy) : copy;
}

function walletTrendBuckets(transactions, period) {
  const anchor = period === "week" ? walletWeekStart(walletAnchorDate(transactions)) : walletAnchorDate(transactions);
  const count = period === "day" ? 7 : 6;
  const buckets = Array.from({ length: count }, (_item, index) => {
    const date = shiftWalletDate(anchor, period, index - count + 1);
    return {
      key: walletDateKey(date, period),
      label: walletBucketLabel(date, period),
      income: 0,
      expense: 0,
      net: 0,
    };
  });
  const byKey = new Map(buckets.map((bucket) => [bucket.key, bucket]));
  for (const item of transactions) {
    const date = parseWalletDate(item.date);
    if (!date) continue;
    const bucket = byKey.get(walletDateKey(date, period));
    if (!bucket) continue;
    const amount = Number(item.amount || 0);
    if (item.type === "income") bucket.income += amount;
    if (item.type === "expense") bucket.expense += amount;
  }
  for (const bucket of buckets) bucket.net = bucket.income - bucket.expense;
  return buckets;
}

function walletPeriodStats(transactions, period) {
  const anchor = walletAnchorDate(transactions);
  const weekStart = walletWeekStart(anchor);
  const items = transactions.filter((item) => {
    const date = parseWalletDate(item.date);
    if (!date) return false;
    if (period === "month") {
      return date.getFullYear() === anchor.getFullYear() && date.getMonth() === anchor.getMonth();
    }
    if (period === "week") {
      const diffDays = Math.floor((date - weekStart) / 86400000);
      return diffDays >= 0 && diffDays < 7;
    }
    return sameWalletDay(date, anchor);
  });
  const income = items.reduce((sum, item) => sum + (item.type === "income" ? Number(item.amount || 0) : 0), 0);
  const expense = items.reduce((sum, item) => sum + (item.type === "expense" ? Number(item.amount || 0) : 0), 0);
  return {
    income,
    expense,
    net: income - expense,
    count: items.length,
    anchor,
    items,
  };
}

function walletCategoriesByType(items, type) {
  const totals = new Map();
  for (const item of items) {
    if (item.type !== type) continue;
    const key = String(item.category || "未分类").trim() || "未分类";
    totals.set(key, (totals.get(key) || 0) + Number(item.amount || 0));
  }
  return [...totals.entries()]
    .map(([category, amount]) => ({ category, amount }))
    .sort((left, right) => right.amount - left.amount);
}

function renderWalletBarChart(buckets) {
  const maxValue = Math.max(1, ...buckets.flatMap((item) => [item.income || 0, item.expense || 0]));
  return buckets.map((item) => `
    <div class="wallet-month">
      <div class="wallet-bars">
        <span class="income" style="height:${Math.max(6, (item.income / maxValue) * 100)}%"></span>
        <span class="expense" style="height:${Math.max(6, (item.expense / maxValue) * 100)}%"></span>
      </div>
      <div>${escapeHtml(item.label)}</div>
      <small>${moneyLabel(item.net)}</small>
    </div>
  `).join("");
}

function walletLinePoints(values, maxValue, height) {
  const width = 100;
  const step = values.length > 1 ? width / (values.length - 1) : width;
  return values.map((value, index) => {
    const x = index * step;
    const y = height - (Number(value || 0) / maxValue) * (height - 8) - 4;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}

function renderWalletLineChart(buckets) {
  const maxValue = Math.max(1, ...buckets.flatMap((item) => [item.income || 0, item.expense || 0]));
  const incomePoints = walletLinePoints(buckets.map((item) => item.income), maxValue, 120);
  const expensePoints = walletLinePoints(buckets.map((item) => item.expense), maxValue, 120);
  return `
    <div class="wallet-line-chart">
      <svg viewBox="0 0 100 120" preserveAspectRatio="none" aria-hidden="true">
        <polyline class="income" points="${incomePoints}"></polyline>
        <polyline class="expense" points="${expensePoints}"></polyline>
      </svg>
      <div class="wallet-line-labels">${buckets.map((item) => `<span>${escapeHtml(item.label)}</span>`).join("")}</div>
    </div>
  `;
}

function renderWalletPieGroup(title, categories, tone) {
  const total = categories.reduce((sum, item) => sum + item.amount, 0);
  if (!total) {
    return `
      <div class="wallet-pie-panel">
        <h4>${title}</h4>
        <div class="wallet-empty compact">当前周期暂无${title}。</div>
      </div>
    `;
  }
  const colors = tone === "income"
    ? ["#00a6b4", "#4aa3a2", "#6b8ed6", "#8fbc8f", "#9b7cc1", "#5fb3d9"]
    : ["#d56f55", "#f2a65a", "#c98273", "#b79a72", "#9b7cc1", "#6b8ed6"];
  let cursor = 0;
  const stops = categories.map((item, index) => {
    const start = cursor;
    cursor += (item.amount / total) * 100;
    return `${colors[index % colors.length]} ${start.toFixed(2)}% ${cursor.toFixed(2)}%`;
  }).join(", ");
  return `
    <div class="wallet-pie-panel">
      <h4>${title}</h4>
      <div class="wallet-pie" style="background: conic-gradient(${stops})"></div>
      <div class="wallet-pie-list">
        ${categories.map((item, index) => `
          <div class="wallet-pie-row">
            <span style="background:${colors[index % colors.length]}"></span>
            <strong>${escapeHtml(item.category)}</strong>
            <b>${moneyLabel(item.amount)}</b>
          </div>
        `).join("")}
      </div>
    </div>
  `;
}

function renderWalletPieChart(items) {
  const incomeCategories = walletCategoriesByType(items, "income");
  const expenseCategories = walletCategoriesByType(items, "expense");
  return `
    <div class="wallet-pie-layout">
      ${renderWalletPieGroup("收入分类", incomeCategories, "income")}
      ${renderWalletPieGroup("支出分类", expenseCategories, "expense")}
    </div>
  `;
}

function attachmentKind(attachment) {
  const type = String(attachment.type || attachment.mime || "");
  if (type.startsWith("image/")) return "image";
  if (type.startsWith("audio/")) return "audio";
  if (type.startsWith("video/")) return "video";
  return "file";
}

function addAttachment(file) {
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
  renderAttachmentPreview();
}

function attachmentIcon(kind) {
  if (kind === "image") return "图";
  if (kind === "video") return "视";
  if (kind === "audio") return "音";
  return "文";
}

function attachmentLabel(kind) {
  if (kind === "image") return "图片";
  if (kind === "video") return "视频";
  if (kind === "audio") return "语音";
  return "文件";
}

function clearAttachments() {
  for (const attachment of state.attachments) {
    if (attachment.url && attachment.url.startsWith("blob:")) URL.revokeObjectURL(attachment.url);
  }
  state.attachments = [];
  renderAttachmentPreview();
}

function removeAttachment(id) {
  const attachment = state.attachments.find((item) => item.id === id);
  if (attachment?.url?.startsWith("blob:")) URL.revokeObjectURL(attachment.url);
  state.attachments = state.attachments.filter((item) => item.id !== id);
  renderAttachmentPreview();
}

function renderAttachmentPreview() {
  attachmentPreview.innerHTML = "";
  attachmentPreview.hidden = state.attachments.length === 0;
  for (const attachment of state.attachments) {
    const chip = document.createElement("div");
    chip.className = `attachment-chip ${attachment.kind === "image" ? "image-chip" : ""} ${attachment.kind === "video" ? "video-chip" : ""}`;
    if (attachment.kind === "image") {
      const img = document.createElement("img");
      img.src = attachment.url;
      img.alt = attachment.name;
      chip.appendChild(img);
    } else if (attachment.kind === "video") {
      const video = document.createElement("video");
      video.src = attachment.url;
      video.muted = true;
      video.playsInline = true;
      chip.appendChild(video);
      const badge = document.createElement("span");
      badge.className = "attachment-kind-badge";
      badge.textContent = attachmentIcon(attachment.kind);
      chip.appendChild(badge);
    } else {
      const icon = document.createElement("div");
      icon.className = `attachment-file-icon ${attachment.kind}`;
      icon.textContent = attachmentIcon(attachment.kind);
      const body = document.createElement("div");
      body.className = "attachment-body";
      const title = document.createElement("div");
      title.className = "attachment-title";
      title.textContent = attachment.name || "附件";
      const meta = document.createElement("div");
      meta.className = "attachment-meta";
      meta.textContent = fileSizeLabel(attachment.size);
      body.append(title, meta);
      chip.append(icon, body);
      if (attachment.kind === "audio") {
        const audio = document.createElement("audio");
        audio.src = attachment.url;
        audio.controls = true;
        chip.appendChild(audio);
      }
    }
    const remove = document.createElement("button");
    remove.className = "remove-attachment";
    remove.type = "button";
    remove.setAttribute("aria-label", "删除附件");
    remove.textContent = "×";
    remove.onclick = () => removeAttachment(attachment.id);
    chip.appendChild(remove);
    attachmentPreview.appendChild(chip);
  }
}

function renderMessageAttachments(container, attachments) {
  const items = Array.isArray(attachments) ? attachments.filter(Boolean) : [];
  if (!items.length) return;
  const grid = document.createElement("div");
  grid.className = `bubble-media-grid media-count-${Math.min(items.length, 4)}`;
  for (const attachment of items) {
    const kind = attachment.kind || attachmentKind(attachment);
    const url = attachment.url || attachment.preview_url || "";
    if (!url) continue;
    const card = document.createElement("div");
    card.className = "bubble-media-card";
    if (kind === "image") {
      const img = document.createElement("img");
      img.src = url;
      img.alt = attachment.name || "图片附件";
      card.appendChild(img);
    } else if (kind === "audio") {
      card.classList.add("audio-card");
      const audio = document.createElement("audio");
      audio.src = url;
      audio.preload = "metadata";
      card.appendChild(audio);
      const voice = document.createElement("button");
      voice.className = "voice-message";
      voice.type = "button";
      voice.setAttribute("aria-label", "播放语音消息");
      voice.innerHTML = `
        <span class="voice-message-play" aria-hidden="true"></span>
        <span class="voice-message-wave" aria-hidden="true"><i></i><i></i><i></i></span>
        <span class="voice-message-label">语音</span>
      `;
      voice.onclick = () => {
        if (audio.paused) {
          document.querySelectorAll(".bubble-media-card audio").forEach((item) => {
            if (item !== audio) item.pause();
          });
          audio.play().catch(() => {});
        } else {
          audio.pause();
        }
      };
      audio.onplay = () => {
        voice.classList.add("is-playing");
        voice.setAttribute("aria-label", "暂停语音消息");
      };
      audio.onpause = () => {
        voice.classList.remove("is-playing");
        voice.setAttribute("aria-label", "播放语音消息");
      };
      audio.onended = () => {
        voice.classList.remove("is-playing");
        voice.setAttribute("aria-label", "播放语音消息");
      };
      card.appendChild(voice);
    } else if (kind === "video") {
      const video = document.createElement("video");
      video.src = url;
      video.controls = true;
      card.appendChild(video);
      const caption = document.createElement("div");
      caption.className = "attachment-caption";
      caption.textContent = attachment.name || "视频附件";
      card.appendChild(caption);
    } else {
      const file = document.createElement("a");
      file.className = "bubble-file-link";
      file.href = url;
      file.target = "_blank";
      file.rel = "noreferrer";
      file.textContent = `${attachmentIcon(kind)} ${attachment.name || "文件附件"} · ${fileSizeLabel(attachment.size)}`;
      card.appendChild(file);
    }
    grid.appendChild(card);
  }
  if (grid.children.length) container.appendChild(grid);
}

function renderEmpty() {
  messageList.innerHTML = `
    <div class="empty-state">
      <div class="empty-mascot" aria-hidden="true">
        <video class="mascot-video" autoplay muted loop playsinline preload="metadata" poster="/static/assets/mascot-smile.png">
          <source src="/static/assets/character-loop.webm" type="video/webm" />
          <img src="/static/assets/mascot-smile.png" alt="" />
        </video>
      </div>
      <h1>聊聊您的生意和资金需求</h1>
      <div class="prompt-chips" aria-label="快捷指令">
        <button class="prompt-chip" type="button">我想了解贷款额度</button>
        <button class="prompt-chip" type="button">最近需要资金周转</button>
        <button class="prompt-chip" type="button">想看看适合的贷款方案</button>
        <button class="prompt-chip" type="button">开厂买设备需要一笔钱</button>
      </div>
    </div>
  `;
  bindPromptChips();
}

function renderMessages() {
  if (!state.messages.length) {
    renderEmpty();
    return;
  }
  messageList.innerHTML = "";
  for (const message of state.messages) {
    const node = messageTemplate.content.firstElementChild.cloneNode(true);
    node.dataset.role = message.role;
    const attachments = Array.isArray(message.attachments) ? message.attachments : [];
    if (attachments.length) node.classList.add("has-media");
    node.querySelector(".message-role").textContent = message.role === "user" ? "我" : "小微";
    const split = splitReasoning(message.content);
    const rawVisible = split.text || message.content;
    const visibleContent = message.role === "assistant" ? stripUploadRequestFence(rawVisible) : rawVisible;
    const bubble = node.querySelector(".bubble");
    if (attachments.length) {
      const text = document.createElement("div");
      text.className = "bubble-text";
      const cleanText = visibleAttachmentText(visibleContent, attachments);
      if (cleanText) {
        if (message.role === "assistant") {
          renderMarkdownInto(text, cleanText);
        } else {
          text.innerHTML = escapeHtml(cleanText).replaceAll("\n", "<br>");
        }
      } else {
        text.hidden = true;
      }
      bubble.appendChild(text);
      renderMessageAttachments(bubble, attachments);
    } else if (message.role === "assistant") {
      renderMarkdownInto(bubble, visibleContent);
    } else {
      bubble.innerHTML = escapeHtml(sanitizeVisibleText(visibleContent)).replaceAll("\n", "<br>");
    }
    if (message.role === "assistant") {
      node.querySelector(".avatar").style.backgroundImage = 'url("/static/assets/xiaowei-avatar-pro.png")';
      node.querySelector(".avatar").classList.add("has-image");
      const uploadCard = renderUploadRequestCard(message);
      if (uploadCard) bubble.appendChild(uploadCard);
      const bubbleWrap = node.querySelector(".bubble-wrap");
      appendProgress(bubbleWrap, message.progress, Boolean(message.streaming));
      if (!message.streaming) {
        const suggestions = renderSuggestions(message);
        if (suggestions) bubbleWrap.appendChild(suggestions);
      }
      if (SHOW_INTERNAL_PANELS) {
        const thinking = message.thinking || message.reasoning_summary || split.reasoning;
        appendDiffPanels(bubbleWrap, message.inline_diffs, Boolean(message.streaming));
        appendDetails(bubbleWrap, "risk-reasoning reasoning-details", "内部过程", thinking, Boolean(message.streaming));
      }
    } else {
      node.querySelector(".avatar").textContent = "";
    }
    messageList.appendChild(node);
  }
  messageList.scrollTop = messageList.scrollHeight;
}

function setBusy(value) {
  state.busy = value;
  sendButton.disabled = value;
  imageButton.disabled = value;
  micButton.disabled = value;
  messageInput.disabled = value;
}

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

function setSidebarCollapsed(collapsed) {
  appShell.classList.toggle("sidebar-collapsed", Boolean(collapsed));
  sidebarToggleButton.setAttribute("aria-label", collapsed ? "展开侧栏" : "收起侧栏");
  sidebarToggleButton.title = collapsed ? "展开侧栏" : "收起侧栏";
  sidebarToggleButton.textContent = collapsed ? "›" : "‹";
  localStorage.setItem("wewallet.sidebarCollapsed", collapsed ? "1" : "0");
}

function isMobileLayout() {
  return window.matchMedia("(max-width: 980px)").matches;
}

function setMobileSidebarOpen(open) {
  appShell.classList.toggle("sidebar-open", Boolean(open));
  mobileMenuButton?.setAttribute("aria-expanded", open ? "true" : "false");
}

function syncResponsiveCopy() {
  messageInput.placeholder = isMobileLayout() ? MOBILE_MESSAGE_PLACEHOLDER : DEFAULT_MESSAGE_PLACEHOLDER;
}

function syncComposerTextState() {
  const hasText = Boolean(messageInput.value.trim());
  messageInput.closest(".composer-inner")?.classList.toggle("has-text", hasText);
}

function showComingSoon(feature) {
  attachmentPopover.hidden = true;
  alert(`${feature}开发中，敬请期待`);
}

function initials(value) {
  const text = String(value || "").trim();
  return text ? text.slice(0, 1) : "企";
}

function setAvatarElement(element, url, fallback) {
  element.textContent = initials(fallback);
  if (url) {
    element.style.backgroundImage = `url("${url}")`;
    element.classList.add("has-image");
  } else {
    element.style.backgroundImage = "";
    element.classList.remove("has-image");
  }
}

function showAuthMessage(text, isError = false) {
  authMessage.textContent = text || "";
  authMessage.classList.toggle("is-error", Boolean(isError));
}

function showAccountMessage(text, isError = false) {
  accountProfileMessage.textContent = text || "";
  accountProfileMessage.classList.toggle("is-error", Boolean(isError));
}

function setLoginMode(mode) {
  state.loginMode = mode === "sms" ? "sms" : "password";
  const smsMode = state.loginMode === "sms";
  loginPasswordField.hidden = smsMode;
  loginSmsField.hidden = !smsMode;
  passwordLoginTab.classList.toggle("is-active", !smsMode);
  smsLoginTab.classList.toggle("is-active", smsMode);
  showAuthMessage("");
}

function showRegister(show) {
  loginForm.hidden = Boolean(show);
  registerForm.hidden = !show;
  enterpriseForm.hidden = true;
  showAuthMessage("");
}

function applyAuthState(auth) {
  state.auth = auth || { authenticated: false };
  const authenticated = Boolean(state.auth.authenticated) && !state.auth.needs_enterprise;
  authScreen.hidden = authenticated;
  if (!state.auth.authenticated) {
    loginForm.hidden = false;
    registerForm.hidden = true;
    enterpriseForm.hidden = true;
  } else {
    loginForm.hidden = true;
    registerForm.hidden = true;
    enterpriseForm.hidden = !state.auth.needs_enterprise;
  }
  const label = state.accountProfile?.nickname || state.auth.enterprise?.name || state.auth.user?.phone || "未登录";
  accountLabel.textContent = label;
  sessionStatus.textContent = state.auth.enterprise ? "企业专属档案" : "等待绑定企业";
  setAvatarElement(accountAvatar, state.accountProfile?.avatar_url || "", label);
  composerForm.hidden = !authenticated;
  openProfileButton.disabled = !authenticated;
  openWalletButton.disabled = !authenticated;
  openLoanButton.disabled = !authenticated;
}

function renderWallet(payload) {
  state.wallet = payload || state.wallet || { transactions: [], summary: {} };
  walletPeriodTabs.forEach((button) => {
    button.classList.toggle("is-active", button.dataset.walletPeriod === state.walletPeriod);
  });
  walletChartModeButtons.forEach((button) => {
    button.classList.toggle("is-active", button.dataset.walletChart === state.walletChartMode);
  });
  const transactionsForPeriod = state.wallet.transactions || [];
  const periodStats = walletPeriodStats(transactionsForPeriod, state.walletPeriod);
  const periodName = walletPeriodLabel(state.walletPeriod);
  const anchorText = periodStats.anchor.toLocaleDateString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
  });
  const summary = state.wallet.summary || {};
  const plan = summary.plan || {};
  walletSummary.innerHTML = `
    <div class="wallet-card"><span>${periodName}收入 · ${anchorText}</span><strong>${moneyLabel(periodStats.income)}</strong></div>
    <div class="wallet-card"><span>${periodName}支出 · ${anchorText}</span><strong>${moneyLabel(periodStats.expense)}</strong></div>
    <div class="wallet-card"><span>${periodName}净现金流</span><strong class="${periodStats.net >= 0 ? "income" : "expense"}">${moneyLabel(periodStats.net)}</strong></div>
    <div class="wallet-card"><span>${periodName}流水笔数</span><strong>${periodStats.count} 笔</strong></div>
  `;

  const buckets = walletTrendBuckets(transactionsForPeriod, state.walletPeriod);
  if (state.walletChartMode === "pie") {
    walletChart.className = "wallet-chart wallet-chart-pie";
    walletChart.innerHTML = renderWalletPieChart(periodStats.items);
  } else if (state.walletChartMode === "line") {
    walletChart.className = "wallet-chart wallet-chart-line";
    walletChart.innerHTML = renderWalletLineChart(buckets);
  } else {
    walletChart.className = "wallet-chart";
    walletChart.innerHTML = renderWalletBarChart(buckets);
  }

  walletPlan.innerHTML = `
    <div class="wallet-plan-row"><span>月均收入</span><strong>${moneyLabel(plan.avg_monthly_income)}</strong></div>
    <div class="wallet-plan-row"><span>月均支出</span><strong>${moneyLabel(plan.avg_monthly_expense)}</strong></div>
    <div class="wallet-plan-row"><span>3 个月备用金</span><strong>${moneyLabel(plan.suggested_reserve)}</strong></div>
    <div class="wallet-plan-row"><span>增长预算</span><strong>${moneyLabel(plan.suggested_reinvestment)}</strong></div>
  `;

  const transactions = [...(state.wallet.transactions || [])].slice(-8).reverse();
  walletTransactions.innerHTML = transactions.length ? transactions.map((item) => `
    <div class="wallet-row">
      <div>
        <strong>${escapeHtml(item.description || "流水")}</strong>
        <span>${escapeHtml(item.date || "")} · ${escapeHtml(item.category || "未分类")}</span>
      </div>
      <b class="${item.type === "income" ? "income" : "expense"}">${item.type === "income" ? "+" : "-"}${moneyLabel(item.amount)}</b>
    </div>
  `).join("") : '<div class="wallet-empty">暂无流水。</div>';
  walletMessage.textContent = plan.suggested_reinvestment
    ? `规划建议：可把月均净现金流中的 ${moneyLabel(plan.suggested_reinvestment)} 作为备货、投流或设备更新预算。`
    : "规划建议会在录入更多流水后生成。";
}

async function loadWallet() {
  if (!state.auth?.authenticated || state.auth?.needs_enterprise) return;
  renderWallet(await getJson("/api/wallet"));
}

async function openWallet() {
  if (!state.auth?.authenticated || state.auth?.needs_enterprise) return;
  walletBackdrop.hidden = false;
  walletDrawer.hidden = false;
  walletDrawer.setAttribute("aria-hidden", "false");
  walletEntryForm.hidden = true;
  walletDate.value = new Date().toISOString().slice(0, 10);
  try {
    await loadWallet();
  } catch (error) {
    walletMessage.textContent = `读取失败：${error.message}`;
  }
}

function closeWallet() {
  walletBackdrop.hidden = true;
  walletDrawer.hidden = true;
  walletDrawer.setAttribute("aria-hidden", "true");
}

function formatLoanAmount(value) {
  const num = Number(value) || 0;
  return Number.isInteger(num) ? String(num) : num.toFixed(1);
}

function formatLoanRate(value) {
  const num = Number(value) || 0;
  return Number.isInteger(num) ? String(num) : num.toFixed(2).replace(/0$/, "");
}

function renderLoanLoading() {
  loanBody.innerHTML = `
    <div class="loan-loading">
      <span class="loan-spinner" aria-hidden="true"></span>
      <span>正在根据您的风控画像和经营流水预估额度...</span>
    </div>`;
}

function formatLoanTimestamp(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function setLoanUpdatedAt(estimate) {
  loanUpdatedAt.textContent = estimate && estimate.generated_at
    ? `评估于 ${formatLoanTimestamp(estimate.generated_at)}`
    : "";
}

function renderLoanEstimate(estimate) {
  setLoanUpdatedAt(estimate);
  if (!estimate) {
    loanBody.innerHTML = `
      <div class="loan-empty">
        <div class="loan-empty-icon" aria-hidden="true">¥</div>
        <p>还没有评估记录，点右上角「更新评估额度」即可根据当前风控画像和经营流水生成。</p>
      </div>`;
    return;
  }
  if (estimate.insufficient) {
    loanBody.innerHTML = `
      <div class="loan-empty">
        <div class="loan-empty-icon" aria-hidden="true">¥</div>
        <p>${escapeHtml(estimate.insufficient_hint || "暂时还不够给出额度，先和小微多聊聊经营情况吧。")}</p>
      </div>`;
    return;
  }

  const grade = String(estimate.grade || "C");
  const reasons = Array.isArray(estimate.reasons) ? estimate.reasons : [];
  const materials = Array.isArray(estimate.missing_materials) ? estimate.missing_materials : [];

  const reasonsHtml = reasons.length
    ? `<ul class="loan-reasons">${reasons.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
    : `<p class="loan-section-empty">暂无更多说明。</p>`;

  const materialsHtml = materials.length
    ? `<div class="loan-section">
         <h3>补齐这些可提额 / 降息</h3>
         <ul class="loan-materials">
           ${materials.map((item) => `
             <li>
               <span class="loan-material-name">${escapeHtml(item.name || "")}</span>
               ${item.impact ? `<span class="loan-material-impact">${escapeHtml(item.impact)}</span>` : ""}
             </li>`).join("")}
         </ul>
       </div>`
    : "";

  loanBody.innerHTML = `
    <div class="loan-card">
      <div class="loan-card-top">
        <div class="loan-amount-label">预估可贷额度</div>
        <div class="loan-amount-value">
          <span class="loan-amount-symbol">¥</span>
          ${escapeHtml(formatLoanAmount(estimate.amount_min))} ~ ${escapeHtml(formatLoanAmount(estimate.amount_max))}
          <span class="loan-amount-unit">万</span>
        </div>
        <div class="loan-grade loan-grade-${escapeAttribute(grade)}">授信评级 ${escapeHtml(grade)} · ${escapeHtml(estimate.grade_label || "")}</div>
        <div class="loan-meta">
          <div class="loan-meta-item">
            <span>年化利率</span>
            <strong>${escapeHtml(formatLoanRate(estimate.rate_min))}% ~ ${escapeHtml(formatLoanRate(estimate.rate_max))}%</strong>
          </div>
          <div class="loan-meta-item">
            <span>最长期限</span>
            <strong>${escapeHtml(String(estimate.term_max_months || 0))} 个月</strong>
          </div>
        </div>
      </div>
      <div class="loan-section">
        <h3>评估依据</h3>
        ${reasonsHtml}
      </div>
      ${materialsHtml}
      <p class="loan-disclaimer">${escapeHtml(estimate.disclaimer || "预估结果，最终以实际审批为准。")}</p>
    </div>`;
}

// Open → show the last saved record (GET, no LLM call). Empty until the
// customer hits 更新评估额度 at least once.
async function loadSavedLoanEstimate() {
  loanMessage.textContent = "";
  renderLoanLoading();
  try {
    const payload = await getJson("/api/loan/estimate");
    renderLoanEstimate(payload.estimate);
  } catch (error) {
    loanUpdatedAt.textContent = "";
    loanBody.innerHTML = `<div class="loan-empty">读取失败：${escapeHtml(error.message)}</div>`;
  }
}

// 更新评估额度 → recompute via the gateway (POST), overwrite the saved record.
async function recomputeLoanEstimate() {
  loanMessage.textContent = "";
  renderLoanLoading();
  refreshLoanButton.disabled = true;
  try {
    const response = await fetch("/api/loan/estimate", { method: "POST" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "评估失败");
    renderLoanEstimate(payload.estimate);
  } catch (error) {
    loanBody.innerHTML = `<div class="loan-empty">评估失败：${escapeHtml(error.message)}</div>`;
  } finally {
    refreshLoanButton.disabled = false;
  }
}

function openLoan() {
  if (!state.auth?.authenticated || state.auth?.needs_enterprise) return;
  loanBackdrop.hidden = false;
  loanModal.hidden = false;
  loanModal.setAttribute("aria-hidden", "false");
  loadSavedLoanEstimate();
}

function closeLoan() {
  loanBackdrop.hidden = true;
  loanModal.hidden = true;
  loanModal.setAttribute("aria-hidden", "true");
}

// ============ 实时通话（豆包实时语音 / 视频通话 + Seed 视觉） ============
const RTC_CFG = window.RTC_PROXY || {
  wsUrl: "ws://localhost:8870/v1/realtime-voice/stream",
  apiBase: "http://localhost:8870"
};

function rtcStatusText(status) {
  if (status === "open") return "已接通";
  if (status === "mock") return "模拟";
  if (status === "error") return "连接异常";
  if (status === "closed") return "已结束";
  return "连接中";
}

// 把一帧 <video> 抽成 jpeg dataURL（移植自 lib/vision.ts）
function captureFrameDataUrl(video, maxWidth, quality) {
  maxWidth = maxWidth || 512;
  quality = quality || 0.5;
  if (!video || video.readyState < 2 || !video.videoWidth || !video.videoHeight) return null;
  const scale = Math.min(1, maxWidth / video.videoWidth);
  const width = Math.round(video.videoWidth * scale);
  const height = Math.round(video.videoHeight * scale);
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.drawImage(video, 0, 0, width, height);
  try {
    return canvas.toDataURL("image/jpeg", quality);
  } catch (e) {
    return null;
  }
}

// 把 dataURL 压成 256 维信号用于变化检测（移植自 scene-diff.ts）
function frameToSignal(frame) {
  const raw = frame.includes(",") ? frame.slice(frame.indexOf(",") + 1) : frame;
  const sampleSize = 256;
  const signal = new Array(sampleSize).fill(0);
  if (!raw.length) return signal;
  for (let i = 0; i < sampleSize; i += 1) {
    signal[i] = raw.charCodeAt(Math.floor((i / sampleSize) * raw.length)) % 256;
  }
  return signal;
}

function framesDiffer(a, b, threshold) {
  if (!a || a.length !== b.length || a.length === 0) return true;
  let total = 0;
  for (let i = 0; i < a.length; i += 1) total += Math.abs(a[i] - b[i]);
  return total / a.length > threshold;
}

function rtcCollapseCharRuns(text) {
  return String(text || "").replace(/([\u3400-\u9fff])\1{2,}/g, "$1");
}

function rtcCollapseAdjacentRepeats(text) {
  text = String(text || "");
  let changed = true;
  while (changed) {
    changed = false;
    const maxSize = Math.min(24, Math.floor(text.length / 2));
    for (let size = maxSize; size >= 2; size -= 1) {
      const out = [];
      let i = 0;
      while (i < text.length) {
        const frag = text.slice(i, i + size);
        if (frag.length < size) {
          out.push(text.slice(i));
          break;
        }
        let j = i + size;
        let count = 1;
        while (text.slice(j, j + size) === frag) {
          count += 1;
          j += size;
        }
        if (count >= 2) {
          out.push(frag);
          i = j;
          changed = true;
        } else {
          out.push(text[i]);
          i += 1;
        }
      }
      text = out.join("");
    }
  }
  return text;
}

function rtcTrimAsrPrefixAccumulation(text) {
  text = String(text || "");
  const n = text.length;
  if (n < 12) return text;
  for (let length = Math.min(n - 2, 80); length >= 4; length -= 1) {
    const suffix = text.slice(n - length);
    const prefix = text.slice(0, n - length);
    if (prefix.length < 4) continue;
    if (prefix.includes(suffix)) return suffix;
    let pos = 0;
    let covered = 0;
    let chunks = 0;
    while (pos < prefix.length) {
      let match = 0;
      const maxK = Math.min(length, prefix.length - pos);
      for (let k = maxK; k >= 2; k -= 1) {
        if (prefix.startsWith(suffix.slice(0, k), pos)) {
          match = k;
          break;
        }
      }
      if (match) {
        covered += match;
        chunks += 1;
        pos += match;
      } else {
        pos += 1;
      }
    }
    if (chunks >= 2 && covered >= 6 && covered / Math.max(1, prefix.length) >= 0.72) {
      return suffix;
    }
  }
  return text;
}

function rtcRestoreLeadingPolarity(original, cleaned) {
  const squashed = rtcCollapseAdjacentRepeats(
    rtcCollapseCharRuns(String(original || "").replace(/\s+/g, ""))
  );
  for (const prefix of ["不是", "没有", "对呀", "对啊", "是的", "嗯", "哦"]) {
    if (squashed.startsWith(prefix) && cleaned && !cleaned.startsWith(prefix)) {
      return `${prefix}，${cleaned}`;
    }
  }
  return cleaned;
}

function rtcRestoreLeadingPause(text) {
  for (const prefix of ["不是", "没有", "对呀", "对啊", "是的"]) {
    if (text.startsWith(prefix) && text.length > prefix.length && text[prefix.length] !== "，") {
      return `${prefix}，${text.slice(prefix.length)}`;
    }
  }
  return text;
}

function rtcNormalizeAsrText(text) {
  const raw = String(text || "").trim();
  if (!raw) return "";
  const canonical = raw
    .replace(/[，,]\s*/g, "，")
    .replace(/[。\.]+/g, "。")
    .replace(/[？?]+/g, "？")
    .replace(/[！!]+/g, "！");
  const parts = [];
  const re = /([^。！？]+)([。！？]?)/g;
  let match;
  while ((match = re.exec(canonical)) !== null) {
    const body = String(match[1] || "").replace(/^[\s，,]+|[\s，,]+$/g, "");
    const punct = match[2] || "";
    if (!body) continue;
    let cleaned = body.replace(/[，,]/g, "").replace(/\s+/g, "");
    for (let i = 0; i < 4; i += 1) {
      const prev = cleaned;
      cleaned = rtcCollapseCharRuns(cleaned);
      cleaned = rtcCollapseAdjacentRepeats(cleaned);
      cleaned = rtcTrimAsrPrefixAccumulation(cleaned);
      cleaned = rtcCollapseAdjacentRepeats(cleaned);
      if (cleaned === prev) break;
    }
    cleaned = rtcRestoreLeadingPause(rtcRestoreLeadingPolarity(body, cleaned)).replace(/^[\s，,]+|[\s，,]+$/g, "");
    if (cleaned) parts.push(`${cleaned}${punct}`);
  }
  const out = [];
  const keys = [];
  for (const part of parts) {
    const key = part.replace(/[。！？]$/, "").replace(/，/g, "");
    while (keys.length && key && keys[keys.length - 1] && key !== keys[keys.length - 1] && key.includes(keys[keys.length - 1])) {
      keys.pop();
      out.pop();
    }
    if (keys.length >= 2 && key.includes(`${keys[keys.length - 2]}${keys[keys.length - 1]}`)) {
      keys.pop();
      out.pop();
      keys.pop();
      out.pop();
    }
    if (keys.length && keys[keys.length - 1] === key) continue;
    out.push(part);
    keys.push(key);
  }
  return out.join("");
}

// 追加/续写一条对话气泡到 transcript 容器
function rtcPushTurn(container, openRoleRef, role, text, append, normalizeAsr) {
  const displayText = normalizeAsr ? rtcNormalizeAsrText(text) : String(text || "");
  // 追加内容前先判断用户是否本就贴着底部（容差 60px）；
  // 是则随对话自动翻滚到底，否则说明用户正上滑看历史，不强行拽回。
  const nearBottom =
    container.scrollHeight - container.scrollTop - container.clientHeight < 60;
  const last = container.lastElementChild;
  if (append && last && last.dataset.role === role) {
    last.textContent = role === "ai" ? (last.textContent || "") + displayText : displayText;
  } else {
    const bubble = document.createElement("div");
    bubble.className = `rtc-bubble rtc-${role}`;
    bubble.dataset.role = role;
    bubble.textContent = displayText || "…";
    container.appendChild(bubble);
    while (container.children.length > 50) container.removeChild(container.firstElementChild);
  }
  if (nearBottom) {
    // 等布局完成后再贴底，避免在新内容尺寸生效前就读到旧的 scrollHeight
    requestAnimationFrame(() => {
      container.scrollTop = container.scrollHeight;
    });
  }
}


// ---------- 语音通话 ----------
const voiceCall = {
  client: null,
  muted: false,
  openRole: null,
  // —— 共享长期记忆 + 跨渠道核验（与视频通话同源，纯语音无摄像头，仅做"口述 vs 档案"比对）——
  callId: null,
  startedAtMs: 0,
  transcriptLog: [], // [{role,text,ts}]
  memoryText: "", // 该企业的已知档案（画像+流水锚点），来自 /start
  sessionReady: false, // 上游实时会话是否已建立
  memoryInjected: false, // 是否已把档案喂进实时模型上下文
  pendingUtterance: "", // 当前用户这轮的口述缓冲，用于去抖检测
  checkTimer: null, // 矛盾检测去抖定时器
  checkInFlight: false,
  contradictionsLog: [] // [{field,stated,known,nudge,ts}] 累积，挂断回写待核验点
};
const voiceCallModal = document.getElementById("voiceCallModal");
const voiceCallBackdrop = document.getElementById("voiceCallBackdrop");

// 累积一轮对话转写（同角色连续增量并入上一条，换角色另起）。与视频通话 videoLogTurn 同构。
function voiceLogTurn(role, text, continuing) {
  if (!text) return;
  text = role === "user" ? rtcNormalizeAsrText(text) : text;
  if (!text) return;
  const log = voiceCall.transcriptLog;
  const last = log[log.length - 1];
  if (continuing && last && last.role === role) {
    last.text = role === "ai" ? last.text + text : text; // AI 增量追加；用户 ASR 回传累积全文则替换
  } else {
    log.push({ role, text, ts: Date.now() / 1000 });
  }
}

// 把该企业的已知档案（画像+流水锚点+其他渠道待核验点）静默喂进实时模型，作为通话背景与核验依据。
function voiceInjectMemory() {
  if (!voiceCall.client || !voiceCall.sessionReady || voiceCall.memoryInjected) return;
  const text = (voiceCall.memoryText || "").trim();
  if (!text) return;
  voiceCall.client.sendContext(
    `（这是这位客户的已知档案，请你默默记住，作为本次通话的背景与核验依据，不要主动念出来、不要复述：\n${text}）`
  );
  voiceCall.memoryInjected = true;
}

// 用户停顿后做一次"口述 vs 已知档案"比对（去抖，避免每个 ASR 增量都打一次）。
function voiceScheduleContradictionCheck() {
  if (voiceCall.checkTimer) clearTimeout(voiceCall.checkTimer);
  voiceCall.checkTimer = setTimeout(() => {
    const utterance = voiceCall.pendingUtterance.trim();
    voiceCall.pendingUtterance = "";
    if (utterance && voiceCall.memoryText) voiceRunContradictionCheck(utterance);
  }, 1400);
}

// 把当前用户口述 + 最近上下文 + 已知档案交给旁路检测器，命中则累积并引导 AI 当场核对。
async function voiceRunContradictionCheck(utterance) {
  utterance = (utterance || "").trim();
  if (!utterance || !voiceCall.memoryText || voiceCall.checkInFlight) return;
  voiceCall.checkInFlight = true;
  try {
    const recent = voiceCall.transcriptLog
      .slice(-6)
      .map((t) => `${t.role === "ai" ? "经理" : "用户"}：${t.text}`)
      .join("\n");
    const res = await fetch(`${RTC_CFG.apiBase}/api/contradiction-check`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ memory: voiceCall.memoryText, utterance, recent })
    });
    if (!res.ok) return;
    const data = await res.json().catch(() => ({}));
    for (const c of data.contradictions || []) voiceHandleContradiction(c);
  } catch (e) {
    // 检测失败不影响通话
  } finally {
    voiceCall.checkInFlight = false;
  }
}

function voiceHandleContradiction(c) {
  if (!c || (!c.field && !c.stated && !c.known)) return;
  const key = `${c.field || ""}|${c.known || ""}`;
  if (voiceCall.contradictionsLog.some((x) => `${x.field || ""}|${x.known || ""}` === key)) return; // 去重
  c.ts = Date.now() / 1000;
  voiceCall.contradictionsLog.push(c); // 累积，挂断时回写为跨渠道待核验点
  // best-effort：引导实时 AI 在接下来的回应里自然、不指控地当场核对
  if (voiceCall.client && c.nudge) {
    voiceCall.client.sendContext(
      `（风控提示，仅供你参考、不要照念也不要说"系统提示"：用户刚才的说法与已知档案不符——${c.field || "某项信息"}：用户说"${c.stated || ""}"，但档案里是"${c.known || ""}"。请你在接下来的回应里，用自然、不指控、给台阶的口吻顺势跟用户核对这处出入，例如："${c.nudge}"。）`
    );
  }
}

// 挂断时：向代理要风控总结（best-effort），合入实时检测到的矛盾，落库并回写跨渠道待核验点。
// 入参为快照，避免依赖随后被重置的 voiceCall 状态。复用视频通话的 videoMergeContradictions / videoBuildMetadata 纯函数。
async function voiceFinalizeCall(callId, transcript, startedAtMs, contradictions) {
  if (!callId) return;
  const flagged = Array.isArray(contradictions) ? contradictions : [];
  let risk = null;
  try {
    const r = await fetch(`${RTC_CFG.apiBase}/api/risk-summary`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transcript, observations: [], contradictions: flagged })
    });
    if (r.ok) risk = await r.json();
  } catch (e) {
    // 风控总结失败不阻塞落库
  }
  risk = videoMergeContradictions(risk, flagged);
  const metadata = videoBuildMetadata([], startedAtMs, "voice");
  try {
    await postJson(`/api/video-call/${callId}/complete`, { transcript, observations: [], risk, metadata, source: "语音通话" });
  } catch (e) {
    console.warn("语音通话记录保存失败", e);
  }
}

function openVoiceCall() {
  if (!state.auth?.authenticated || state.auth?.needs_enterprise) return;
  if (voiceCall.client) return;
  const transcript = document.getElementById("voiceCallTranscript");
  const statusEl = document.getElementById("voiceCallStatus");
  const orb = document.getElementById("voiceCallOrb");
  transcript.innerHTML = "";
  voiceCall.openRole = null;
  voiceCall.callId = null;
  voiceCall.startedAtMs = Date.now();
  voiceCall.transcriptLog = [];
  voiceCall.memoryText = "";
  voiceCall.sessionReady = false;
  voiceCall.memoryInjected = false;
  voiceCall.pendingUtterance = "";
  if (voiceCall.checkTimer) clearTimeout(voiceCall.checkTimer);
  voiceCall.checkTimer = null;
  voiceCall.checkInFlight = false;
  voiceCall.contradictionsLog = [];
  voiceCallBackdrop.hidden = false;
  voiceCallModal.hidden = false;
  voiceCallModal.setAttribute("aria-hidden", "false");

  voiceCall.client = window.createRealtimeVoiceClient({
    wsUrl: RTC_CFG.wsUrl,
    scene: "voice",
    video: false,
    onStatus(status) {
      statusEl.textContent = rtcStatusText(status);
      statusEl.classList.toggle("is-open", status === "open");
    },
    onSessionReady() {
      voiceCall.sessionReady = true;
      voiceInjectMemory(); // 若档案已取回，立即注入；否则 /start 回来时再注入
    },
    onAiText(text) {
      const continuing = voiceCall.openRole === "ai";
      voiceCall.openRole = "ai";
      voiceLogTurn("ai", text, continuing);
      rtcPushTurn(transcript, null, "ai", text, continuing);
    },
    onUserText(text, done) {
      // 豆包 ASR 每包回传“这句累积全文”，done 表示说完；故 user 按替换、done 时封口。
      if (done) { voiceCall.openRole = null; return; }
      const continuing = voiceCall.openRole === "user";
      voiceCall.openRole = "user";
      voiceLogTurn("user", text, continuing);
      rtcPushTurn(transcript, null, "user", text, continuing, true);
      voiceCall.pendingUtterance = rtcNormalizeAsrText(text); // 当前这句全文，去抖后做"口述 vs 档案"比对
      voiceScheduleContradictionCheck();
    },
    onAudioLevel(level) {
      if (orb) orb.style.transform = `scale(${0.9 + level * 0.22})`;
    }
  });
  voiceCall.muted = false;
  document.getElementById("voiceCallMuteButton").textContent = "静音";

  // 建一条 active 通话记录用于留痕，并取回该企业的已知档案（与视频通话同一份长期记忆）；失败不影响通话。
  postJson("/api/video-call/start")
    .then((res) => {
      voiceCall.callId = res.call_id || null;
      voiceCall.memoryText = (res.memory && res.memory.text) || "";
      voiceInjectMemory(); // 若会话已就绪，立即注入；否则 onSessionReady 时再注入
    })
    .catch(() => { /* 留痕不可用时静默降级 */ });

  voiceCall.client.start();
}

function closeVoiceCall() {
  if (voiceCall.client) {
    voiceCall.client.stop();
    voiceCall.client = null;
  }
  voiceCallBackdrop.hidden = true;
  voiceCallModal.hidden = true;
  voiceCallModal.setAttribute("aria-hidden", "true");

  if (voiceCall.checkTimer) clearTimeout(voiceCall.checkTimer);
  voiceCall.checkTimer = null;
  // 快照后落库 + 回写待核验点（异步，不阻塞 UI 关闭），随后清空内存缓冲。
  if (voiceCall.callId) {
    void voiceFinalizeCall(
      voiceCall.callId,
      voiceCall.transcriptLog,
      voiceCall.startedAtMs,
      voiceCall.contradictionsLog
    );
  }
  voiceCall.callId = null;
  voiceCall.transcriptLog = [];
  voiceCall.contradictionsLog = [];
  voiceCall.memoryText = "";
}

// ---------- 视频通话（实时语音 + Seed 视觉） ----------
const videoCall = {
  client: null,
  muted: false,
  openRole: null,
  cameraReady: false,
  visionDesc: "",
  latestObservation: null,
  latestObservationAt: 0, // 最新画面观测的时间戳，用于场景比对的新鲜度判断
  sampleTimer: null,
  lastSignal: null,
  visionInFlight: false,
  answering: false,
  lastFedDesc: "", // 最近喂给豆包的画面描述，去重避免重复注入
  aiSpeakingUntil: 0,
  userSpeakingUntil: 0,
  // —— 尽调留痕：通话过程中累积，挂断时落库 ——
  callId: null,
  startedAtMs: 0,
  transcriptLog: [], // [{role,text,ts}]
  observationsLog: [], // [{...结构化观察, ts}]
  usedVoice: false,
  usedText: false,
  // —— 记忆 + 实时矛盾检测 ——
  memoryText: "", // 该企业的已知档案（画像+流水锚点），来自 /start
  sessionReady: false, // 上游实时会话是否已建立（context 才能送达）
  memoryInjected: false, // 是否已把档案喂进实时模型上下文
  pendingUtterance: "", // 当前用户这轮的口述缓冲，用于去抖检测
  checkTimer: null, // 矛盾检测去抖定时器
  checkInFlight: false,
  contradictionsLog: [], // [{field,stated,known,nudge,ts}] 累积，挂断落库
  imageCheckInFlight: false, // 历史图档比对去重
  lastImageCheckAt: 0, // 图档比对节流
  imageHistorySeen: [], // 已提示过的历史材料名，去重
  // —— 画面欺骗升级状态机：场景与口述不符时 challenged→evidence_requested→flagged ——
  sceneDeception: { state: "none", hits: 0, lastHitAt: 0, flaggedLogged: false }
};
const VIDEO_OBSERVATION_CAP = 300; // 防止超长通话无界增长

// 累积一轮对话转写：同角色的连续增量并入上一条，换角色则新开一条。
function videoLogTurn(role, text, continuing, normalizeAsr) {
  if (!text) return;
  text = normalizeAsr ? rtcNormalizeAsrText(text) : text;
  if (!text) return;
  const log = videoCall.transcriptLog;
  const last = log[log.length - 1];
  if (continuing && last && last.role === role) {
    last.text = role === "ai" ? last.text + text : text; // AI 增量追加；用户 ASR 回传累积全文则替换
  } else {
    log.push({ role, text, ts: Date.now() / 1000 });
  }
}
const videoCallModal = document.getElementById("videoCallModal");
const videoCallBackdrop = document.getElementById("videoCallBackdrop");
const videoCallSelf = document.getElementById("videoCallSelf");

function describeObservation(o) {
  const parts = [];
  if (o.caption) parts.push(o.caption);
  if (o.person_description) parts.push(`人物：${o.person_description}`);
  if (o.notable_objects && o.notable_objects.length) parts.push(`可见：${o.notable_objects.join("、")}`);
  if (o.document_text) parts.push(`证件文字：${o.document_text}`);
  return parts.join("；") || "画面看不太清";
}

async function videoFetchVision(image) {
  const res = await fetch(`${RTC_CFG.apiBase}/api/vision?mode=structured`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ image, mode: "structured" })
  });
  const data = await res.json().catch(() => ({}));
  return data.observation || null;
}

// 每 2s 抓帧 → 变化检测 → Seed 结构化观察 → 后台静默喂给豆包当上下文。
// 这样豆包始终"看得见"当前画面，用户问什么都能立刻据此回答，不必现场注入再等。
async function videoSampleFrame() {
  if (!videoCall.cameraReady || videoCall.visionInFlight) return;
  const snapshot = captureFrameDataUrl(videoCallSelf, 512, 0.5);
  if (!snapshot) return;
  const signal = frameToSignal(snapshot);
  const changed = framesDiffer(videoCall.lastSignal, signal, 4);
  videoCall.lastSignal = signal;
  if (!changed) return;

  videoCall.visionInFlight = true;
  try {
    const observation = await videoFetchVision(snapshot);
    if (!observation) return;
    videoCall.latestObservation = observation;
    videoCall.latestObservationAt = Date.now();
    if (videoCall.observationsLog.length < VIDEO_OBSERVATION_CAP) {
      // 一并留存这帧画面（base64 dataURL），挂断时随 observations 落库为可访问的 image_url
      videoCall.observationsLog.push({ ...observation, image: snapshot, ts: Date.now() / 1000 });
    }
    const desc = describeObservation(observation).trim();
    if (!desc) return;
    videoCall.visionDesc = (observation.caption || desc).trim();
    const badge = document.getElementById("videoCallVisionBadge");
    if (badge) badge.hidden = false;

    // 画面里出现证件/材料时，拿这帧和该客户的历史上传材料比对（前后矛盾核验）。节流 6s。
    if (Array.isArray(observation.visible_documents) && observation.visible_documents.length) {
      void videoCheckImageHistory(snapshot);
    }

    // 画面有实质变化且当前空闲（AI/用户都没在说话）时，把最新画面喂进豆包上下文。
    // 喂进去的这条由代理静默吞掉播报，只更新"记忆"，不会让豆包自言自语。
    const now = Date.now();
    const idle = now >= videoCall.aiSpeakingUntil && now >= videoCall.userSpeakingUntil;
    if (videoCall.client && idle && desc !== videoCall.lastFedDesc) {
      videoCall.client.sendContext(`（画面信息：${desc}）`);
      videoCall.lastFedDesc = desc;
    }
  } catch (e) {
    // 视觉失败不影响语音
  } finally {
    videoCall.visionInFlight = false;
  }
}

function openVideoCall() {
  if (!state.auth?.authenticated || state.auth?.needs_enterprise) return;
  if (videoCall.client) return;
  const transcript = document.getElementById("videoCallTranscript");
  const statusEl = document.getElementById("videoCallStatus");
  const caption = document.getElementById("videoCallCaption");
  const hint = document.getElementById("videoCallCameraHint");
  transcript.innerHTML = "";
  caption.textContent = "";
  videoCall.openRole = null;
  videoCall.cameraReady = false;
  videoCall.visionDesc = "";
  videoCall.latestObservation = null;
  videoCall.latestObservationAt = 0;
  videoCall.lastSignal = null;
  videoCall.lastFedDesc = "";
  videoCall.aiSpeakingUntil = 0;
  videoCall.userSpeakingUntil = 0;
  videoCall.callId = null;
  videoCall.startedAtMs = Date.now();
  videoCall.transcriptLog = [];
  videoCall.observationsLog = [];
  videoCall.usedVoice = false;
  videoCall.usedText = false;
  videoCall.memoryText = "";
  videoCall.sessionReady = false;
  videoCall.memoryInjected = false;
  videoCall.pendingUtterance = "";
  if (videoCall.checkTimer) clearTimeout(videoCall.checkTimer);
  videoCall.checkTimer = null;
  videoCall.checkInFlight = false;
  videoCall.contradictionsLog = [];
  videoCall.sceneDeception = { state: "none", hits: 0, lastHitAt: 0, flaggedLogged: false };
  videoCall.imageCheckInFlight = false;
  videoCall.lastImageCheckAt = 0;
  videoCall.imageHistorySeen = [];
  const riskAlerts = document.getElementById("videoCallRiskAlerts");
  if (riskAlerts) { riskAlerts.innerHTML = ""; riskAlerts.hidden = true; }
  document.getElementById("videoCallVisionBadge").hidden = true;
  if (hint) hint.hidden = false;
  videoCallBackdrop.hidden = false;
  videoCallModal.hidden = false;
  videoCallModal.setAttribute("aria-hidden", "false");

  videoCall.client = window.createRealtimeVoiceClient({
    wsUrl: RTC_CFG.wsUrl,
    scene: "video",
    video: true,
    bargeIn: true,
    onStatus(status) {
      statusEl.textContent = rtcStatusText(status);
      statusEl.classList.toggle("is-open", status === "open");
    },
    onSessionReady() {
      videoCall.sessionReady = true;
      videoInjectMemory();
    },
    onAiText(text) {
      videoCall.aiSpeakingUntil = Date.now() + 1500; // AI 说话期间不喂画面，避免打断
      const continuing = videoCall.openRole === "ai";
      videoCall.openRole = "ai";
      videoCall.usedVoice = true;
      videoLogTurn("ai", text, continuing);
      caption.textContent = continuing ? caption.textContent + text : text;
      rtcPushTurn(transcript, null, "ai", text, continuing);
    },
    onUserText(text, done) {
      // 画面已在后台持续喂给豆包，这里只展示用户说的话，回答由豆包直接据上下文实时给出
      videoCall.userSpeakingUntil = Date.now() + 1200;
      // 豆包 ASR 每包回传的是“这句的累积全文”，不是增量；done 表示这句说完。
      if (done) { videoCall.openRole = null; return; } // 封口，下句另起一条
      const continuing = videoCall.openRole === "user";
      videoCall.openRole = "user";
      videoCall.usedVoice = true;
      // 用最新全文替换当前这句（continuing 时 videoLogTurn/rtcPushTurn 对 user 都按替换处理），避免重复堆叠
      videoLogTurn("user", text, continuing, true);
      rtcPushTurn(transcript, null, "user", text, continuing, true);
      videoCall.pendingUtterance = rtcNormalizeAsrText(text); // 当前这句全文，去抖后做记忆/场景比对
      videoScheduleContradictionCheck();
    },
    onAudioLevel() {}
  });
  videoCall.muted = false;
  document.getElementById("videoCallMuteButton").textContent = "静音";

  // 建一条 active 通话记录用于尽调留痕，并取回该企业的已知档案（记忆）；失败不影响通话。
  postJson("/api/video-call/start")
    .then((res) => {
      videoCall.callId = res.call_id || null;
      videoCall.memoryText = (res.memory && res.memory.text) || "";
      videoInjectMemory(); // 若会话已就绪，立即注入；否则 onSessionReady 时再注入
    })
    .catch(() => { /* 留痕不可用时静默降级 */ });

  videoCall.client.start().then((stream) => {
    if (!stream) return;
    videoCallSelf.srcObject = stream;
    videoCall.cameraReady = true;
    if (hint) hint.hidden = true;
    videoSampleFrame();
    videoCall.sampleTimer = setInterval(videoSampleFrame, 2000);
  });
}

function videoCallChannel() {
  if (videoCall.usedVoice && videoCall.usedText) return "mixed";
  if (videoCall.usedText) return "text";
  return "voice";
}

// 把该企业的已知档案（画像+流水锚点）静默喂进实时模型，作为通话背景与核验依据。
// 仅在上游会话就绪、有档案、且尚未注入时执行一次。
function videoInjectMemory() {
  if (!videoCall.client || !videoCall.sessionReady || videoCall.memoryInjected) return;
  const text = (videoCall.memoryText || "").trim();
  if (!text) return;
  videoCall.client.sendContext(
    `（这是这位客户的已知档案，请你默默记住，作为本次通话的背景与核验依据，不要主动念出来、不要复述：\n${text}）`
  );
  videoCall.memoryInjected = true;
}

// 口述里"我现在在某处"的当下定位线索；没有它就不做场景比对，避免把"昨天去餐厅""朋友在店里"误判。
const SCENE_SELF_LOCATION_CUE = /(我在|我人在|我这边|我这儿|我这是|我就在|现在.{0,4}在|这边就是|这儿就是|我们这边)/;
// 口述场景关键词 → 归一化场景桶（与视觉 place_type 对齐）。
const SCENE_CLAIM_PATTERNS = [
  { bucket: "经营场所", re: /(店里|店铺|门店|店面|餐厅|饭店|餐馆|饭馆|食堂|超市|便利店|商店|商铺|档口|柜台|摊位|铺子|仓库|车间|厂里|工厂|办公室|公司|写字楼|门市)/ },
  { bucket: "居住场所", re: /(家里|在家|宿舍|卧室|房间里|出租屋|住的地方|租的房)/ },
  { bucket: "户外", re: /(外面|路上|街上|马路|户外|在外边)/ },
  { bucket: "车内", re: /(车里|车上|在开车|副驾|驾驶座)/ }
];
// 视觉 place_type → 归一化场景桶（办公室/会议室/店铺都归为"经营场所"，避免店主说办公室被误判）。
function videoVisualSceneBucket(placeType) {
  switch (placeType) {
    case "店铺":
    case "办公室":
    case "会议室":
      return "经营场所";
    case "居住/宿舍":
      return "居住场所";
    case "户外":
      return "户外";
    case "车内":
      return "车内";
    default:
      return null; // 其他 / 看不清 → 不判，宁可漏不可错
  }
}
const SCENE_PLACE_LABEL = {
  "居住/宿舍": "住的地方/宿舍",
  "店铺": "店里",
  "办公室": "办公室",
  "会议室": "会议室",
  "户外": "户外",
  "车内": "车里"
};

// 本地确定性核验：用户口述的"我在某场景" vs 画面 place_type。
// 不符时按 challenged→evidence_requested→flagged 三级升级；对上了则回落状态。
function videoCheckSceneMismatch(utterance) {
  const obs = videoCall.latestObservation;
  if (!obs || !obs.place_type) return;
  // 画面太旧（>8s）不比，避免拿过期画面误判；刚切镜头时也给视觉留出刷新窗口。
  if (Date.now() - (videoCall.latestObservationAt || 0) > 8000) return;
  if (!SCENE_SELF_LOCATION_CUE.test(utterance)) return; // 没有当下定位线索就不判
  const visualBucket = videoVisualSceneBucket(obs.place_type);
  if (!visualBucket) return; // 画面场景看不清/其他
  const claim = SCENE_CLAIM_PATTERNS.find((p) => p.re.test(utterance));
  if (!claim) return; // 没说到场景
  const s = videoCall.sceneDeception;
  if (claim.bucket === visualBucket) {
    // 画面与口述对上了：若此前在升级中（且尚未坐实欺骗），视为已澄清，回落状态。
    if (s.state !== "none" && !s.flaggedLogged) { s.state = "none"; s.hits = 0; }
    return;
  }

  // —— 不符：推进状态机 ——
  const placeLabel = SCENE_PLACE_LABEL[obs.place_type] || obs.place_type;
  s.hits += 1;
  s.lastHitAt = Date.now();
  s.state = s.hits >= 3 ? "flagged" : s.hits === 2 ? "evidence_requested" : "challenged";

  if (s.state === "challenged") {
    // 首次：温和提示，复用既有管线（去重 + 渲染折叠提示 + 落库 + 引导 AI 当场核对）。
    videoHandleContradiction({
      field: "所在场景",
      stated: `用户称在「${claim.bucket}」`,
      known: `画面更像「${obs.place_type}」`,
      nudge: `诶，我这边画面看着更像是在${placeLabel}呢，跟${claim.bucket}好像对不太上，是镜头切到别处了吗？`
    });
  } else if (s.state === "evidence_requested") {
    // 二次仍不符：升级为请对方给佐证（绕开去重，直接喂 AI 一条升级提示）。
    if (videoCall.client) {
      videoCall.client.sendContext(
        `（风控升级提示，仅供你参考、不要照念也不要说"系统提示"：用户的所在场景说法（${claim.bucket}）与画面（${placeLabel}）仍然对不上。请你自然、客气地请对方给点能对上的佐证——比如把镜头慢慢转一圈看看周边、或念念门口的招牌/门牌，别指控、给台阶。）`
      );
    }
  } else if (s.state === "flagged" && !s.flaggedLogged) {
    // 三次仍说不通：坐实"疑似画面欺骗"，落库（distinct field 不会被去重）并提醒 AI 后续更谨慎。
    s.flaggedLogged = true;
    const finding = {
      field: "疑似画面欺骗",
      stated: `用户多次称在「${claim.bucket}」`,
      known: `画面始终更像「${obs.place_type}」，经提示与取证仍无法对上`,
      severity: "high",
      ts: Date.now() / 1000
    };
    videoRenderRiskAlert(finding);
    videoCall.contradictionsLog.push(finding);
    if (videoCall.client) {
      videoCall.client.sendContext(
        `（风控提示，仅供你参考、不要照念：用户所在场景（自称${claim.bucket}）与画面（${placeLabel}）经多次提示与取证仍对不上，疑似用画面或说法造假。请你后续核验更谨慎，口吻仍保持客气、不撕破脸、不直接指控。）`
      );
    }
  }
}

// 用户停顿后做一次比对（去抖，避免每个 ASR 增量都打一次）。
function videoScheduleContradictionCheck() {
  if (videoCall.checkTimer) clearTimeout(videoCall.checkTimer);
  videoCall.checkTimer = setTimeout(() => {
    const utterance = videoCall.pendingUtterance.trim();
    videoCall.pendingUtterance = "";
    if (!utterance) return;
    videoCheckSceneMismatch(utterance); // 本地：口述场景 vs 画面（确定性，不依赖档案）
    if (videoCall.memoryText) videoRunContradictionCheck(utterance); // 旁路：口述 vs 已知档案
  }, 1400);
}

// 文字通道按问题检索本地知识库（产品/材料/流程/口径），作为回答依据注入 /api/video-chat。
async function videoFetchKnowledge(query) {
  const res = await fetch("/api/video-call/knowledge", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query })
  });
  if (!res.ok) return "";
  const data = await res.json().catch(() => ({}));
  return data.block || "";
}

// 把当前用户口述 + 最近上下文 + 已知档案交给旁路检测器，命中则提醒并引导核对。
async function videoRunContradictionCheck(utterance) {
  utterance = (utterance || "").trim();
  if (!utterance || !videoCall.memoryText || videoCall.checkInFlight) return;
  videoCall.checkInFlight = true;
  try {
    const recent = videoCall.transcriptLog
      .slice(-6)
      .map((t) => `${t.role === "ai" ? "经理" : "用户"}：${t.text}`)
      .join("\n");
    const res = await fetch(`${RTC_CFG.apiBase}/api/contradiction-check`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ memory: videoCall.memoryText, utterance, recent })
    });
    if (!res.ok) return;
    const data = await res.json().catch(() => ({}));
    for (const c of data.contradictions || []) videoHandleContradiction(c);
  } catch (e) {
    // 检测失败不影响通话
  } finally {
    videoCall.checkInFlight = false;
  }
}

// 把当前画面（含证件/材料）和该客户历史上传过的材料做比对。命中历史相似材料时，
// 提示"客户曾上传过类似材料"并引导 AI 当场口头核对关键信息（前后矛盾核验）。
async function videoCheckImageHistory(snapshot) {
  const now = Date.now();
  if (videoCall.imageCheckInFlight || now - videoCall.lastImageCheckAt < 6000) return;
  videoCall.imageCheckInFlight = true;
  videoCall.lastImageCheckAt = now;
  try {
    const res = await fetch("/api/video-call/image-check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image: snapshot })
    });
    if (!res.ok) return;
    const data = await res.json().catch(() => ({}));
    for (const hit of data.hits || []) {
      const name = hit.original_name || "历史材料";
      if (videoCall.imageHistorySeen.includes(name)) continue; // 去重
      videoCall.imageHistorySeen.push(name);
      const when = (hit.captured_at || "").slice(0, 10);
      const finding = {
        field: "历史材料比对",
        stated: "当前画面出示的材料",
        known: `客户曾上传过相似材料「${name}」${when ? "（" + when + "）" : ""}`,
        ts: Date.now() / 1000
      };
      videoRenderRiskAlert(finding);
      videoCall.contradictionsLog.push(finding); // 一并落库 + 回写待核验点
      if (videoCall.client) {
        videoCall.client.sendContext(
          `（核验提示，仅供你参考、不要照念：客户现在出示的材料，与他过去上传过的「${name}」高度相似。请你自然地请客户念一下当前材料上的关键信息（如名称、编号、日期），和记录核对一下，口吻随和、不要指控。）`
        );
      }
    }
  } catch (e) {
    // 比对失败不影响通话
  } finally {
    videoCall.imageCheckInFlight = false;
  }
}

function videoHandleContradiction(c) {
  if (!c || (!c.field && !c.stated && !c.known)) return;
  const key = `${c.field || ""}|${c.known || ""}`;
  if (videoCall.contradictionsLog.some((x) => `${x.field || ""}|${x.known || ""}` === key)) return; // 去重
  c.ts = Date.now() / 1000;
  videoCall.contradictionsLog.push(c);
  // ① 确定性：通话界面弹出"前后不一致/与历史不符"提示，并累积落库
  videoRenderRiskAlert(c);
  // ② best-effort：引导实时 AI 在接下来的回应里自然、不指控地当场核对
  if (videoCall.client && c.nudge) {
    videoCall.client.sendContext(
      `（风控提示，仅供你参考、不要照念也不要说"系统提示"：用户刚才的说法与已知档案不符——${c.field || "某项信息"}：用户说"${c.stated || ""}"，但档案里是"${c.known || ""}"。请你在接下来的回应里，用自然、不指控、给台阶的口吻顺势跟用户核对这处出入，例如："${c.nudge}"。）`
    );
  }
}

function videoRenderRiskAlert(c) {
  const box = document.getElementById("videoCallRiskAlerts");
  if (!box) return;
  box.hidden = false;

  // 懒构建折叠结构（每次开新通话 box.innerHTML 会被清空，故在此重建）
  let summary = box.querySelector(".rtc-risk-summary");
  let list = box.querySelector(".rtc-risk-list");
  if (!summary || !list) {
    box.classList.add("collapsed"); // 默认折叠，避免挤压文字记录
    summary = document.createElement("button");
    summary.type = "button";
    summary.className = "rtc-risk-summary";
    summary.addEventListener("click", () => box.classList.toggle("collapsed"));
    list = document.createElement("div");
    list.className = "rtc-risk-list";
    box.appendChild(summary);
    box.appendChild(list);
  }

  const item = document.createElement("div");
  item.className = "rtc-risk-alert";
  const head = document.createElement("div");
  head.className = "rtc-risk-head";
  head.textContent = `前后不一致 · ${c.field || "信息核验"}`;
  const detail = document.createElement("div");
  detail.className = "rtc-risk-detail";
  detail.innerHTML = `本次：<b></b>　|　档案：<b></b>`;
  detail.querySelectorAll("b")[0].textContent = c.stated || "—";
  detail.querySelectorAll("b")[1].textContent = c.known || "—";
  item.appendChild(head);
  item.appendChild(detail);
  list.appendChild(item);
  while (list.children.length > 8) list.removeChild(list.firstElementChild); // 只留最近 8 条 DOM

  // 摘要条：总数 + 最新一处字段
  const total = videoCall.contradictionsLog.length || list.children.length;
  summary.innerHTML = "";
  const label = document.createElement("span");
  label.className = "rtc-risk-summary-label";
  label.textContent = `前后不一致 · ${total} 处`;
  const latest = document.createElement("span");
  latest.className = "rtc-risk-summary-latest";
  latest.textContent = `最新：${c.field || "信息核验"}`;
  const chevron = document.createElement("span");
  chevron.className = "rtc-risk-chevron";
  chevron.setAttribute("aria-hidden", "true");
  summary.appendChild(label);
  summary.appendChild(latest);
  summary.appendChild(chevron);

  if (!box.classList.contains("collapsed")) list.scrollTop = list.scrollHeight;
}

// 通话元数据（时长/通道/帧数）。挂断与异常关页两条路径共用。
function videoBuildMetadata(observations, startedAtMs, channel) {
  return {
    duration_sec: Math.max(0, Math.round((Date.now() - startedAtMs) / 1000)),
    channel,
    frame_count: observations.length
  };
}

// 把实时检测到的"与历史不符"明细并入风控结论；risk 缺失时按 medium 兜底，保住矛盾不丢。
function videoMergeContradictions(risk, contradictions) {
  const flagged = Array.isArray(contradictions) ? contradictions : [];
  if (!flagged.length) return risk;
  if (!risk) risk = { level: "medium", reasons: [], signals: {} };
  risk.contradictions = flagged;
  // 出现"疑似画面欺骗"等高危信号时，把等级抬到 high（不覆盖既有的 high 判定）。
  if (flagged.some((c) => c && c.severity === "high") && risk.level !== "high") {
    risk.level = "high";
    if (!Array.isArray(risk.reasons)) risk.reasons = [];
    risk.reasons.push("通话中检测到疑似画面欺骗（场景与口述多次不符，提示与取证后仍无法对上）");
  }
  return risk;
}

// 挂断时：先向代理要风控总结（best-effort），再把整段记录补全落库。
// 入参为快照，避免依赖随后被重置的 videoCall 状态。
async function videoFinalizeCall(callId, transcript, observations, startedAtMs, channel, contradictions) {
  if (!callId) return;
  const flagged = Array.isArray(contradictions) ? contradictions : [];
  // 风控总结只看结构化字段，不需要 base64 画面，剥掉以减小请求体。
  const leanObservations = (observations || []).map((o) => {
    const { image, ...rest } = o || {};
    return rest;
  });
  const frames = (observations || [])
    .map((o) => ({ ts: o && o.ts, image: o && o.image }))
    .filter((frame) => typeof frame.image === "string" && frame.image);
  let risk = null;
  try {
    const r = await fetch(`${RTC_CFG.apiBase}/api/risk-summary`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transcript, observations: leanObservations, contradictions: flagged })
    });
    if (r.ok) risk = await r.json();
  } catch (e) {
    // 风控总结失败不阻塞落库
  }
  risk = videoMergeContradictions(risk, flagged);
  const metadata = videoBuildMetadata(observations, startedAtMs, channel);
  try {
    await postJson(`/api/video-call/${callId}/complete`, { transcript, observations: leanObservations, frames, risk, metadata });
  } catch (e) {
    // 落库失败仅记录，不影响已结束的通话
    console.warn("视频通话记录保存失败", e);
  }
}

// 视频通话打字：走 /api/video-chat 流式（带视觉摘要）
async function videoSendText(text) {
  const transcript = document.getElementById("videoCallTranscript");
  const caption = document.getElementById("videoCallCaption");
  const visual = videoCall.visionDesc.trim();
  videoCall.openRole = "user";
  videoCall.usedText = true;
  videoLogTurn("user", text, false);
  rtcPushTurn(transcript, null, "user", text, false);
  videoCall.pendingUtterance += text;
  videoScheduleContradictionCheck();
  videoCall.answering = true;
  try {
    // 文字问答主战场：检索本地知识库，作为回答依据注入（产品/材料/流程/口径）。
    let knowledge = "";
    try { knowledge = await videoFetchKnowledge(text); } catch (e) { /* 检索失败照常作答 */ }
    const parts = [];
    if (visual) parts.push(`当前视频通话摄像头视觉摘要：${visual}`);
    if (knowledge) parts.push(`可参考的业务知识（据此作答，不要照念、不要提“知识库”）：\n${knowledge}`);
    parts.push(`用户问题：${text}`);
    const res = await fetch(`${RTC_CFG.apiBase}/api/video-chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        messages: [{ role: "user", content: parts.join("\n") }]
      })
    });
    if (!res.ok || !res.body) {
      rtcPushTurn(transcript, null, "ai", "（文字回复失败，请改用语音）", false);
      return;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let acc = "";
    videoCall.openRole = "ai";
    rtcPushTurn(transcript, null, "ai", "", false);
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      acc += decoder.decode(value, { stream: true });
      caption.textContent = acc;
      const last = transcript.lastElementChild;
      if (last && last.dataset.role === "ai") last.textContent = acc;
    }
    if (acc) videoLogTurn("ai", acc, false);
  } catch (e) {
    rtcPushTurn(transcript, null, "ai", "（文字回复失败，请改用语音）", false);
  } finally {
    videoCall.answering = false;
  }
}

function closeVideoCall() {
  if (videoCall.sampleTimer) clearInterval(videoCall.sampleTimer);
  videoCall.sampleTimer = null;
  videoCall.lastFedDesc = "";
  if (videoCall.client) {
    videoCall.client.stop();
    videoCall.client = null;
  }
  videoCallSelf.srcObject = null;
  videoCall.cameraReady = false;
  videoCallBackdrop.hidden = true;
  videoCallModal.hidden = true;
  videoCallModal.setAttribute("aria-hidden", "true");

  if (videoCall.checkTimer) clearTimeout(videoCall.checkTimer);
  videoCall.checkTimer = null;
  // 快照后落库（异步，不阻塞 UI 关闭），随后清空内存缓冲。
  if (videoCall.callId) {
    void videoFinalizeCall(
      videoCall.callId,
      videoCall.transcriptLog,
      videoCall.observationsLog,
      videoCall.startedAtMs,
      videoCallChannel(),
      videoCall.contradictionsLog
    );
  }
  videoCall.callId = null;
  videoCall.transcriptLog = [];
  videoCall.observationsLog = [];
  videoCall.contradictionsLog = [];
  videoCall.memoryText = "";
}

// 页面被直接关闭/刷新时的兜底：用 sendBeacon 把已有内容尽力补到 complete（跳过风控总结）。
window.addEventListener("beforeunload", () => {
  if (!videoCall.callId) return;
  const leanObservations = (videoCall.observationsLog || []).map((o) => {
    const { image, ...rest } = o || {};
    return rest;
  });
  const frames = (videoCall.observationsLog || [])
    .map((o) => ({ ts: o && o.ts, image: o && o.image }))
    .filter((frame) => typeof frame.image === "string" && frame.image);
  const body = JSON.stringify({
    transcript: videoCall.transcriptLog,
    observations: leanObservations,
    frames,
    risk: videoMergeContradictions(null, videoCall.contradictionsLog),
    metadata: videoBuildMetadata(videoCall.observationsLog, videoCall.startedAtMs, videoCallChannel())
  });
  try {
    navigator.sendBeacon(`/api/video-call/${videoCall.callId}/complete`, new Blob([body], { type: "application/json" }));
  } catch (e) {
    // 兜底失败无妨
  }
});

function setAccountTab(tab) {
  const enterprise = tab === "enterprise";
  accountTabUser.classList.toggle("is-active", !enterprise);
  accountTabEnterprise.classList.toggle("is-active", enterprise);
  accountUserPanel.hidden = enterprise;
  accountEnterprisePanel.hidden = !enterprise;
}

function fillAccountForm(profile) {
  const enterprise = profile?.enterprise || {};
  profilePhone.value = profile?.phone || "";
  profileNickname.value = profile?.nickname || "";
  profileRole.value = profile?.role || "";
  for (const [field, input] of Object.entries(accountEnterpriseFields)) {
    input.value = enterprise[field] || "";
  }
  const label = profile?.nickname || enterprise.name || state.auth?.user?.phone || "企";
  setAvatarElement(profileAvatarPreview, profile?.avatar_url || "", label);
  setAvatarElement(accountAvatar, profile?.avatar_url || "", label);
  accountLabel.textContent = label;
}

function collectAccountProfilePayload() {
  const enterprise = {};
  for (const [field, input] of Object.entries(accountEnterpriseFields)) {
    enterprise[field] = input.value.trim();
  }
  return {
    nickname: profileNickname.value.trim(),
    role: profileRole.value.trim(),
    enterprise,
  };
}

async function loadAccountProfile() {
  if (!state.auth?.authenticated || state.auth?.needs_enterprise) return null;
  const payload = await getJson("/api/account/profile");
  state.accountProfile = payload.profile || null;
  if (state.accountProfile) fillAccountForm(state.accountProfile);
  applyAuthState(state.auth);
  return state.accountProfile;
}

async function openAccountModal() {
  if (!state.auth?.authenticated || state.auth?.needs_enterprise) return;
  accountBackdrop.hidden = false;
  accountModal.hidden = false;
  accountModal.setAttribute("aria-hidden", "false");
  showAccountMessage("");
  setAccountTab("user");
  try {
    await loadAccountProfile();
  } catch (error) {
    showAccountMessage(`读取失败：${error.message}`, true);
  }
}

function closeAccountModal() {
  accountBackdrop.hidden = true;
  accountModal.hidden = true;
  accountModal.setAttribute("aria-hidden", "true");
}

async function loadMessages() {
  const payload = await getJson("/api/messages");
  state.messages = payload.messages || [];
  renderMessages();
  void ensureLatestSuggestions();
}

async function ensureLatestSuggestions() {
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
      renderMessages();
    }
  } catch (error) {
    // Recommendation chips are helpful, but chat history should still render normally.
  }
}

async function bootstrapApp() {
  try {
    const auth = await getJson("/api/auth/me");
    applyAuthState(auth);
    if (auth.authenticated && !auth.needs_enterprise) {
      await loadAccountProfile();
      await loadMessages();
      await loadProfile();
      await loadWalletPending();
      if (window.location.hash === "#wallet") {
        await openWallet();
      }
    } else {
      renderMessages();
    }
  } catch (error) {
    applyAuthState({ authenticated: false });
    showAuthMessage(error.message, true);
    renderMessages();
  }
}

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
      if (isThinkingStatus(text)) {
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
      renderWalletPending();
    }
    if (payload.auto_profile?.scheduled && profileSummary) {
      profileSummary.textContent = `已自动开始更新风控画像（第 ${payload.auto_profile.user_turn_count} 轮），稍后会自动刷新...`;
      startProfilePolling();
    } else if (payload.auto_profile?.in_progress && profileSummary) {
      startProfilePolling();
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
      renderMessages();
    }
  }

  const tail = buffer.trim();
  if (tail) {
    const event = JSON.parse(tail);
    applyChatStreamEvent(event);
    if (event.type === "message.complete") completed = true;
    renderMessages();
  }

  const assistant = lastAssistantMessage();
  if (assistant && assistant.role === "assistant") {
    assistant.streaming = false;
  }
  if (!completed) {
    appendUniqueProgress(assistant, "本轮连接已结束，未收到完成事件。");
  }
}

async function sendMessage(content) {
  const text = content.trim();
  const attachments = [...state.attachments];
  if ((!text && !attachments.length) || state.busy) return;
  const optimisticText = text;
  const optimisticAttachments = attachments.map((item) => ({
    kind: item.kind,
    name: item.name,
    size: item.size,
    type: item.type,
    url: item.url,
  }));
  state.messages.push({ role: "user", content: optimisticText, attachments: optimisticAttachments });
  state.messages.push({ role: "assistant", content: "正在分析客户需求...", thinking: "", progress: [], inline_diffs: [], streaming: true });
  renderMessages();
  messageInput.value = "";
  messageInput.style.height = "";
  syncComposerTextState();
  state.attachments = [];
  renderAttachmentPreview();
  setBusy(true);
  try {
    await postStreamingChat(text, attachments);
    renderMessages();
  } catch (error) {
    state.messages[state.messages.length - 1] = {
      role: "assistant",
      content: `调用失败：${error.message}`,
    };
    renderMessages();
  } finally {
    for (const attachment of attachments) {
      if (attachment.url && attachment.url.startsWith("blob:")) URL.revokeObjectURL(attachment.url);
    }
    setBusy(false);
  }
}

async function loadProfile() {
  if (!state.auth?.authenticated || state.auth?.needs_enterprise) return null;
  try {
    const response = await fetch("/api/profile");
    const payload = await response.json();
    renderMarkdownInto(profileMarkdown, payload.markdown || "暂无画像。");
    const profileState = payload.state || {};
    state.profileLastUpdatedAt = profileState.last_profile_updated_at || state.profileLastUpdatedAt || "";
    if (profileState.in_progress) {
      profileSummary.textContent = "企业画像正在后台更新，稍后会自动刷新...";
      startProfilePolling();
    } else if (profileState.last_error) {
      profileSummary.textContent = `上次更新失败：${profileState.last_error}`;
    } else {
      profileSummary.textContent = "查看当前企业的 MD 档案，画像会随对话自动更新。";
    }
    renderProfileDiff("", false, true);
    return payload;
  } catch (error) {
    profileSummary.textContent = `读取失败：${error.message}`;
    return null;
  }
}

function startProfilePolling() {
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
        renderMarkdownInto(profileMarkdown, payload.markdown || "暂无画像。");
        state.profileLastUpdatedAt = updatedAt;
        profileSummary.textContent = profileState.last_profile_changed
          ? "企业画像已更新。"
          : "企业画像本轮无新增变更。";
        stopProfilePolling();
        return;
      }
      if (profileState.last_error && !profileState.in_progress) {
        profileSummary.textContent = `更新失败：${profileState.last_error}`;
        stopProfilePolling();
        return;
      }
      if (Date.now() - startedAt > 5 * 60 * 1000) {
        profileSummary.textContent = "画像更新仍在进行，请稍后手动刷新。";
        stopProfilePolling();
      }
    } catch (error) {
      profileSummary.textContent = `轮询失败：${error.message}`;
      stopProfilePolling();
    }
  };
  state.profilePollTimer = window.setInterval(tick, 3000);
  tick();
}

function formatMoney(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value ?? "");
  return number.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function describePendingPayload(item) {
  const action = item.action;
  if (action === "add") {
    const p = item.payload || {};
    const typeLabel = p.type === "income" ? "收入" : "支出";
    return `新增${typeLabel} ¥${formatMoney(p.amount)}（${p.date || "日期未填"} · ${p.description || "无摘要"} · ${p.category || "未分类"}）`;
  }
  if (action === "update") {
    const before = item.before || {};
    const changes = item.payload || {};
    const parts = Object.entries(changes).map(([key, value]) => {
      const label = ({ type: "类型", amount: "金额", date: "日期", description: "摘要", category: "分类" })[key] || key;
      const fromValue = key === "amount" ? `¥${formatMoney(before[key])}` : (before[key] ?? "");
      const toValue = key === "amount" ? `¥${formatMoney(value)}` : value;
      return `${label} ${fromValue} → ${toValue}`;
    });
    return `修改 ${before.date || ""} ${before.description || item.target_id}：${parts.join("、")}`;
  }
  if (action === "delete") {
    const b = item.before || {};
    const typeLabel = b.type === "income" ? "收入" : "支出";
    return `删除一笔${typeLabel}：${b.date || ""} ${b.description || ""} ¥${formatMoney(b.amount)}（${b.category || ""}）`;
  }
  return `${action} ${item.target_id || ""}`;
}

function renderWalletPending() {
  if (!walletPendingBar) return;
  const items = state.walletPending || [];
  if (!items.length) {
    walletPendingBar.hidden = true;
    walletPendingList.innerHTML = "";
    return;
  }
  walletPendingBar.hidden = false;
  walletPendingCount.textContent = `${items.length} 条待你确认`;
  walletPendingList.innerHTML = "";
  for (const item of items) {
    const wrap = document.createElement("div");
    wrap.className = "wallet-pending-item";
    const left = document.createElement("div");
    left.className = "wallet-pending-summary";
    const actionLabel = ({ add: "新增", update: "修改", delete: "删除" })[item.action] || item.action;
    const tag = document.createElement("span");
    tag.className = `wallet-pending-action ${item.action}`;
    tag.textContent = actionLabel;
    left.appendChild(tag);
    left.appendChild(document.createTextNode(describePendingPayload(item)));
    if (item.explanation) {
      const note = document.createElement("span");
      note.className = "wallet-pending-explain";
      note.textContent = `理由：${item.explanation}`;
      left.appendChild(note);
    }
    const controls = document.createElement("div");
    controls.className = "wallet-pending-controls";
    const confirmBtn = document.createElement("button");
    confirmBtn.type = "button";
    confirmBtn.className = "confirm";
    confirmBtn.textContent = "确认";
    confirmBtn.disabled = state.walletPendingBusyIds.has(item.id);
    confirmBtn.onclick = () => resolveWalletPending(item.id, "confirm");
    const rejectBtn = document.createElement("button");
    rejectBtn.type = "button";
    rejectBtn.className = "reject";
    rejectBtn.textContent = "拒绝";
    rejectBtn.disabled = state.walletPendingBusyIds.has(item.id);
    rejectBtn.onclick = () => resolveWalletPending(item.id, "reject");
    controls.appendChild(confirmBtn);
    controls.appendChild(rejectBtn);
    wrap.appendChild(left);
    wrap.appendChild(controls);
    walletPendingList.appendChild(wrap);
  }
}

async function resolveWalletPending(pendingId, action) {
  if (!pendingId || state.walletPendingBusyIds.has(pendingId)) return;
  state.walletPendingBusyIds.add(pendingId);
  renderWalletPending();
  try {
    const response = await fetch(`/api/wallet/pending/${encodeURIComponent(pendingId)}/${action}`, {
      method: "POST",
    });
    const payload = await response.json();
    if (!response.ok) {
      alert(payload.error || `${action === "confirm" ? "确认" : "拒绝"}失败`);
      state.walletPending = state.walletPending.filter((item) => item.id !== pendingId);
    } else {
      state.walletPending = payload.pending || [];
      if (payload.transactions) {
        state.wallet = { transactions: payload.transactions, summary: payload.summary };
        if (walletDrawer && !walletDrawer.hidden) renderWallet();
      }
    }
  } catch (error) {
    alert(`网络错误：${error.message}`);
  } finally {
    state.walletPendingBusyIds.delete(pendingId);
    renderWalletPending();
  }
}

async function loadWalletPending() {
  if (!state.auth?.authenticated || state.auth?.needs_enterprise) return;
  try {
    const response = await fetch("/api/wallet/pending");
    if (!response.ok) return;
    const payload = await response.json();
    state.walletPending = payload.pending || [];
    renderWalletPending();
  } catch (_) {
    // silent — refreshed on next chat / page load
  }
}

function stopProfilePolling() {
  if (state.profilePollTimer) {
    window.clearInterval(state.profilePollTimer);
    state.profilePollTimer = null;
  }
}

async function refreshProfile() {
  if (!state.auth?.authenticated || state.auth?.needs_enterprise) return;
  if (!refreshProfileButton) return;
  const originalLabel = refreshProfileButton.textContent;
  refreshProfileButton.disabled = true;
  refreshProfileButton.textContent = "刷新中...";
  if (profileSummary) profileSummary.textContent = "正在检查画像状态...";
  try {
    const response = await fetch("/api/profile/refresh", { method: "POST" });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "刷新失败");
    }
    const message = payload.message || "";
    if (profileSummary) profileSummary.textContent = message;
    const profileState = payload.state || {};
    state.profileLastUpdatedAt = profileState.last_profile_updated_at || state.profileLastUpdatedAt || "";
    if (payload.status === "in_progress") {
      startProfilePolling();
    } else {
      await loadProfile();
      if (profileSummary && message) profileSummary.textContent = message;
    }
  } catch (error) {
    if (profileSummary) profileSummary.textContent = `刷新失败：${error.message}`;
  } finally {
    refreshProfileButton.disabled = false;
    refreshProfileButton.textContent = originalLabel || "刷新";
  }
}

function renderProfileDiff(diff, changed, hidden = false) {
  if (!profileDiffDetails || !profileDiff) return;
  profileDiffDetails.hidden = !SHOW_INTERNAL_PANELS || (hidden && !diff);
  profileDiffDetails.open = SHOW_INTERNAL_PANELS && Boolean(diff);
  profileDiff.textContent = diff || (changed ? "暂无变更记录。" : "本次无新增变更。");
}

function openProfile(load = true) {
  profileBackdrop.hidden = false;
  profileDrawer.classList.add("open");
  profileDrawer.setAttribute("aria-hidden", "false");
  if (load) loadProfile();
}

function closeProfile() {
  profileBackdrop.hidden = true;
  profileDrawer.classList.remove("open");
  profileDrawer.setAttribute("aria-hidden", "true");
}

function bindPromptChips() {
  document.querySelectorAll(".prompt-chip").forEach((button) => {
    button.onclick = () => sendMessage(button.textContent || "");
  });
}

composerForm.addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage(messageInput.value);
});

imageButton.addEventListener("click", () => {
  if (state.busy) return;
  attachmentPopover.hidden = !attachmentPopover.hidden;
});

pickImageButton.addEventListener("click", () => {
  attachmentPopover.hidden = true;
  imageInput.click();
});

pickFileButton.addEventListener("click", () => {
  showComingSoon("上传文件");
});

pickVideoButton.addEventListener("click", () => {
  showComingSoon("上传视频");
});

imageInput.addEventListener("change", () => {
  for (const file of Array.from(imageInput.files || [])) {
    addAttachment(file);
  }
  imageInput.value = "";
});

fileInput.addEventListener("change", () => {
  for (const file of Array.from(fileInput.files || [])) {
    addAttachment(file);
  }
  fileInput.value = "";
});

videoInput.addEventListener("change", () => {
  for (const file of Array.from(videoInput.files || [])) {
    addAttachment(file);
  }
  videoInput.value = "";
});

document.addEventListener("click", (event) => {
  if (!attachmentPopover.hidden && !event.target.closest(".attachment-menu")) {
    attachmentPopover.hidden = true;
  }
});

async function startVoiceInput() {
  if (state.busy || state.recorder) return;
  if (!window.isSecureContext) {
    throw new Error("手机通过局域网 HTTP 打开时，浏览器会禁止麦克风。需要 HTTPS 后才能直接语音输入。");
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error("当前浏览器不支持网页麦克风录音。");
  }
  if (!window.MediaRecorder) {
    throw new Error("当前浏览器不支持网页录音。");
  }
  state.recordingChunks = [];

  // Always upload the raw audio so the backend qwen3-asr-flash can
  // transcribe AND read emotion/language. Browser-side SpeechRecognition
  // is intentionally not used — it bypasses our ASR + emotion pipeline.
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const recorder = new MediaRecorder(stream);
  state.recorder = recorder;
  state.voiceMeter = startVoiceMeter(stream);
  micButton.classList.add("is-recording");
  recorder.ondataavailable = (event) => {
    if (event.data.size) state.recordingChunks.push(event.data);
  };
  recorder.onstop = () => {
    stream.getTracks().forEach((track) => track.stop());
    const voicePeak = stopVoiceMeter();
    micButton.classList.remove("is-recording");
    if (state.recordingChunks.length) {
      const blob = new Blob(state.recordingChunks, { type: recorder.mimeType || "audio/webm" });
      if (blob.size > 0 && voicePeak >= 0.0015) {
        addAttachment(new File([blob], `voice-${Date.now()}.webm`, { type: blob.type || "audio/webm" }));
      } else if (blob.size > 0) {
        const sendAnyway = confirm("录音音量很低，可能听不清。要仍然发送这段录音吗？\n\n如果你确定刚才说话了，请先检查浏览器麦克风权限和系统输入设备。");
        if (sendAnyway) {
          addAttachment(new File([blob], `voice-${Date.now()}.webm`, { type: blob.type || "audio/webm" }));
        }
      } else {
        alert("没有录到声音，请确认麦克风已对准并重试。");
      }
    } else {
      alert("没有录到声音，请确认麦克风已对准并重试。");
    }
    state.recorder = null;
    state.recordingChunks = [];
  };
  recorder.start();
}

function startVoiceMeter(stream) {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) return null;
  try {
    const context = new AudioContextClass();
    if (context.state === "suspended") {
      context.resume().catch(() => {});
    }
    const analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    const source = context.createMediaStreamSource(stream);
    source.connect(analyser);
    const data = new Uint8Array(analyser.fftSize);
    const meter = { context, source, analyser, data, peak: 0, timer: 0 };
    meter.timer = window.setInterval(() => {
      analyser.getByteTimeDomainData(data);
      let sum = 0;
      for (const value of data) {
        const centered = (value - 128) / 128;
        sum += centered * centered;
      }
      meter.peak = Math.max(meter.peak, Math.sqrt(sum / data.length));
    }, 120);
    return meter;
  } catch (_error) {
    return null;
  }
}

function stopVoiceMeter() {
  const meter = state.voiceMeter;
  state.voiceMeter = null;
  if (!meter) return Number.POSITIVE_INFINITY;
  window.clearInterval(meter.timer);
  try {
    meter.source.disconnect();
  } catch (_error) {}
  try {
    meter.context.close();
  } catch (_error) {}
  return meter.peak || 0;
}

function stopVoiceInput() {
  if (state.recorder && state.recorder.state !== "inactive") {
    state.recorder.stop();
  }
}

micButton.addEventListener("click", async () => {
  if (state.recorder) {
    stopVoiceInput();
    return;
  }
  try {
    await startVoiceInput();
  } catch (error) {
    micButton.classList.remove("is-recording");
    state.recorder = null;
    stopVoiceMeter();
    let hint = error.message || String(error);
    if (error.name === "NotAllowedError" || error.name === "SecurityError") {
      hint = "浏览器或系统没有授权麦克风。请在浏览器地址栏左侧的锁形图标里允许麦克风，并确认 macOS“系统设置 → 隐私与安全 → 麦克风”里勾上了 Chrome。";
    } else if (error.name === "NotFoundError" || error.name === "OverconstrainedError") {
      hint = "找不到可用的麦克风设备，请检查耳麦/外接麦克风是否插好。";
    } else if (error.name === "NotReadableError") {
      hint = "麦克风被其他应用占用，请关闭 Zoom/腾讯会议等程序后重试。";
    }
    alert(`无法启动语音输入：${hint}`);
  }
});

messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendMessage(messageInput.value);
  }
});

messageInput.addEventListener("input", () => {
  messageInput.style.height = "auto";
  messageInput.style.height = `${Math.min(messageInput.scrollHeight, 180)}px`;
  syncComposerTextState();
});

async function sendAuthCode(phone, targetInput, button) {
  showAuthMessage("");
  button.disabled = true;
  try {
    const payload = await postJson("/api/auth/sms/send", { phone });
    targetInput.focus();
    showAuthMessage("验证码已发送，请查收短信");
  } catch (error) {
    showAuthMessage(error.message, true);
  } finally {
    button.disabled = false;
  }
}

sendLoginCodeButton.onclick = () => sendAuthCode(loginPhone.value.trim(), loginCode, sendLoginCodeButton);
sendRegisterCodeButton.onclick = () => sendAuthCode(registerPhone.value.trim(), registerCode, sendRegisterCodeButton);

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  showAuthMessage("");
  try {
    const auth = state.loginMode === "sms"
      ? await postJson("/api/auth/sms/verify", {
          phone: loginPhone.value.trim(),
          code: loginCode.value.trim(),
        })
      : await postJson("/api/auth/password/login", {
          phone: loginPhone.value.trim(),
          password: loginPassword.value,
        });
    applyAuthState(auth);
    if (auth.needs_enterprise) {
      showAuthMessage("首次登录，请创建企业档案。");
      enterpriseName.focus();
    } else {
      showAuthMessage("");
      await loadAccountProfile();
      await loadMessages();
      await loadProfile();
    }
  } catch (error) {
    showAuthMessage(error.message, true);
  }
});

registerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  showAuthMessage("");
  try {
    const auth = await postJson("/api/auth/register", {
      phone: registerPhone.value.trim(),
      password: registerPassword.value,
      code: registerCode.value.trim(),
    });
    applyAuthState(auth);
    if (auth.needs_enterprise) {
      showAuthMessage("注册成功，请创建企业档案。");
      enterpriseName.focus();
    }
  } catch (error) {
    showAuthMessage(error.message, true);
  }
});

passwordLoginTab.onclick = () => setLoginMode("password");
smsLoginTab.onclick = () => setLoginMode("sms");
openRegisterButton.onclick = () => showRegister(true);
backToLoginButton.onclick = () => showRegister(false);

enterpriseForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  showAuthMessage("");
  try {
    const payload = await postJson("/api/enterprise/create", {
      name: enterpriseName.value.trim(),
      credit_code: enterpriseCreditCode.value.trim(),
    });
    applyAuthState(payload.auth);
    await loadAccountProfile();
    await loadMessages();
    await loadProfile();
    showAuthMessage("");
  } catch (error) {
    showAuthMessage(error.message, true);
  }
});

openProfileButton.onclick = openProfile;
closeProfileButton.onclick = closeProfile;
profileBackdrop.onclick = closeProfile;
refreshProfileButton.onclick = refreshProfile;
openWalletButton.onclick = openWallet;
closeWalletButton.onclick = closeWallet;
walletBackdrop.onclick = closeWallet;
openLoanButton.onclick = openLoan;
closeLoanButton.onclick = closeLoan;
loanBackdrop.onclick = closeLoan;
refreshLoanButton.onclick = recomputeLoanEstimate;
// 语音通话
openVoiceCallButton.addEventListener("click", openVoiceCall);
document.getElementById("closeVoiceCallButton").onclick = closeVoiceCall;
voiceCallBackdrop.onclick = closeVoiceCall;
document.getElementById("voiceCallEndButton").onclick = closeVoiceCall;
document.getElementById("voiceCallMuteButton").onclick = () => {
  if (!voiceCall.client) return;
  voiceCall.muted = !voiceCall.muted;
  voiceCall.client.setMuted(voiceCall.muted);
  document.getElementById("voiceCallMuteButton").textContent = voiceCall.muted ? "取消静音" : "静音";
};
document.getElementById("voiceCallForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = document.getElementById("voiceCallInput");
  const text = input.value.trim();
  if (!text || !voiceCall.client) return;
  voiceCall.client.sendText(text);
  voiceCall.openRole = "user";
  rtcPushTurn(document.getElementById("voiceCallTranscript"), null, "user", text, false);
  input.value = "";
});

// 视频通话
openVideoCallButton.addEventListener("click", openVideoCall);
document.getElementById("closeVideoCallButton").onclick = closeVideoCall;
videoCallBackdrop.onclick = closeVideoCall;
document.getElementById("videoCallEndButton").onclick = closeVideoCall;
document.getElementById("videoCallMuteButton").onclick = () => {
  if (!videoCall.client) return;
  videoCall.muted = !videoCall.muted;
  videoCall.client.setMuted(videoCall.muted);
  document.getElementById("videoCallMuteButton").textContent = videoCall.muted ? "取消静音" : "静音";
};
document.getElementById("videoCallForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = document.getElementById("videoCallInput");
  const text = input.value.trim();
  if (!text || !videoCall.client || videoCall.answering) return;
  input.value = "";
  videoSendText(text);
});
importWalletButton.onclick = () => walletCsvInput.click();
addWalletEntryButton.onclick = () => {
  walletEntryForm.hidden = !walletEntryForm.hidden;
  if (!walletEntryForm.hidden) walletAmount.focus();
};
walletPeriodTabs.forEach((button) => {
  button.onclick = () => {
    state.walletPeriod = button.dataset.walletPeriod || "day";
    renderWallet();
  };
});
walletChartModeButtons.forEach((button) => {
  button.onclick = () => {
    state.walletChartMode = button.dataset.walletChart || "bar";
    renderWallet();
  };
});
walletCsvInput.addEventListener("change", async () => {
  const [file] = Array.from(walletCsvInput.files || []);
  walletCsvInput.value = "";
  if (!file) return;
  const body = new FormData();
  body.append("file", file, file.name || "wallet.csv");
  walletMessage.textContent = "正在导入流水...";
  try {
    const response = await fetch("/api/wallet/import", { method: "POST", body });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "导入失败");
    renderWallet(payload);
  } catch (error) {
    walletMessage.textContent = error.message;
  }
});
walletEntryForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  walletMessage.textContent = "正在添加流水...";
  try {
    const payload = await postJson("/api/wallet/transaction", {
      date: walletDate.value,
      type: walletType.value,
      amount: walletAmount.value,
      category: walletCategory.value,
      description: walletDescription.value,
    });
    walletAmount.value = "";
    walletCategory.value = "";
    walletDescription.value = "";
    renderWallet(payload);
  } catch (error) {
    walletMessage.textContent = error.message;
  }
});
mobileMenuButton.onclick = () => setMobileSidebarOpen(!appShell.classList.contains("sidebar-open"));
sidebarToggleButton.onclick = () => {
  if (isMobileLayout()) {
    setMobileSidebarOpen(false);
    return;
  }
  setSidebarCollapsed(!appShell.classList.contains("sidebar-collapsed"));
};
openProfileButton.addEventListener("click", () => {
  if (isMobileLayout()) setMobileSidebarOpen(false);
});
openWalletButton.addEventListener("click", () => {
  if (isMobileLayout()) setMobileSidebarOpen(false);
});
openLoanButton.addEventListener("click", () => {
  if (isMobileLayout()) setMobileSidebarOpen(false);
});
document.addEventListener("click", (event) => {
  if (!isMobileLayout() || !appShell.classList.contains("sidebar-open")) return;
  if (event.target.closest(".sidebar") || event.target.closest(".mobile-menu-button")) return;
  setMobileSidebarOpen(false);
});
window.addEventListener("resize", () => {
  if (!isMobileLayout()) setMobileSidebarOpen(false);
  syncResponsiveCopy();
});
accountButton.onclick = () => {
  if (isMobileLayout()) setMobileSidebarOpen(false);
  openAccountModal();
};
closeAccountButton.onclick = closeAccountModal;
accountBackdrop.onclick = closeAccountModal;
accountTabUser.onclick = () => setAccountTab("user");
accountTabEnterprise.onclick = () => setAccountTab("enterprise");
avatarUploadButton.onclick = () => avatarInput.click();

avatarInput.addEventListener("change", async () => {
  const [file] = Array.from(avatarInput.files || []);
  avatarInput.value = "";
  if (!file) return;
  const body = new FormData();
  body.append("avatar", file, file.name || "avatar.png");
  showAccountMessage("正在上传头像...");
  try {
    const response = await fetch("/api/account/avatar", { method: "POST", body });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "上传失败");
    state.accountProfile = payload.profile || state.accountProfile;
    if (payload.auth) state.auth = payload.auth;
    fillAccountForm(state.accountProfile);
    applyAuthState(state.auth);
    showAccountMessage("头像已更新");
  } catch (error) {
    showAccountMessage(error.message, true);
  }
});

accountProfileForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  showAccountMessage("正在保存...");
  try {
    const payload = await postJson("/api/account/profile", collectAccountProfilePayload());
    state.accountProfile = payload.profile || state.accountProfile;
    if (payload.auth) state.auth = payload.auth;
    fillAccountForm(state.accountProfile);
    applyAuthState(state.auth);
    showAccountMessage("资料已保存");
  } catch (error) {
    showAccountMessage(error.message, true);
  }
});

logoutButton.onclick = async () => {
  await postJson("/api/auth/logout");
  state.auth = { authenticated: false };
  state.accountProfile = null;
  closeAccountModal();
  applyAuthState(state.auth);
};

document.querySelectorAll(".brand-mark").forEach((mark) => {
  mark.style.backgroundImage = 'url("/static/assets/customer-manager-plus.png")';
  mark.classList.add("has-image");
});
setSidebarCollapsed(localStorage.getItem("wewallet.sidebarCollapsed") === "1");
syncResponsiveCopy();
syncComposerTextState();
renderMessages();
bootstrapApp();

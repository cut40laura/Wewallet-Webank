/*
 * shared/format.js — 纯函数层（桌面端 / 手机端共用）。
 *
 * 规则：本文件禁止出现 document / window / state 等任何 DOM 与全局状态依赖，
 * 只能是「输入 → 输出」的纯函数或常量表。改动会同时影响两端，改前先打招呼。
 *
 * 加载顺序：必须先于 shared/core.js 与各端 view（chat.js）加载。
 */

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

function stripUploadRequestFence(value) {
  return String(value || "").replace(/```upload_request\s*\n[\s\S]*?\n```\s*/g, "").trim();
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

function isThinkingStatus(text) {
  const value = String(text || "").trim();
  return Boolean(value) && value.length <= 80 && !value.includes("\n");
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

function formatMoney(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value ?? "");
  return number.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
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

function walletLinePoints(values, maxValue, height) {
  const width = 100;
  const step = values.length > 1 ? width / (values.length - 1) : width;
  return values.map((value, index) => {
    const x = index * step;
    const y = height - (Number(value || 0) / maxValue) * (height - 8) - 4;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}

function attachmentKind(attachment) {
  const type = String(attachment.type || attachment.mime || "");
  if (type.startsWith("image/")) return "image";
  if (type.startsWith("audio/")) return "audio";
  if (type.startsWith("video/")) return "video";
  return "file";
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

function initials(value) {
  const text = String(value || "").trim();
  return text ? text.slice(0, 1) : "企";
}

function formatLoanAmount(value) {
  const num = Number(value) || 0;
  return Number.isInteger(num) ? String(num) : num.toFixed(1);
}

function formatLoanRate(value) {
  const num = Number(value) || 0;
  return Number.isInteger(num) ? String(num) : num.toFixed(2).replace(/0$/, "");
}

function formatLoanTimestamp(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
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

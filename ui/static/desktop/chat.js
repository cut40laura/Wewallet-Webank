/*
 * chat.js — 桌面端 view 层。
 *
 * 只负责 DOM 渲染与交互绑定。业务数据/网络/SSE 在 shared/core.js（全局 Core + state），
 * 纯函数在 shared/format.js。本文件通过 Core.on(事件) 订阅数据变化后渲染，
 * 通过 Core.xxx() 触发业务动作。事件契约见 shared/core.js 头部注释。
 *
 * 加载顺序：shared/format.js → shared/core.js → chat.js → voicecall.js。
 */

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
const closeVideoCallButton = document.getElementById("closeVideoCallButton");
const videoCallBackdrop = document.getElementById("videoCallBackdrop");
const videoCallModal = document.getElementById("videoCallModal");
const videoCallSelf = document.getElementById("videoCallSelf");
const videoCallSelfPlaceholder = document.getElementById("videoCallSelfPlaceholder");
const videoCallStatus = document.getElementById("videoCallStatus");
const videoCallStartButton = document.getElementById("videoCallStartButton");
const videoCallMuteButton = document.getElementById("videoCallMuteButton");
const videoCallEndButton = document.getElementById("videoCallEndButton");
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

function renderMarkdownInto(element, text) {
  const cleanText = sanitizeVisibleText(text);
  element.classList.add("markdown-body");
  element.innerHTML = cleanText ? renderMarkdown(cleanText) : "";
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
    remove.onclick = () => Core.removeAttachment(attachment.id);
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
        <video class="mascot-video" autoplay muted loop playsinline preload="metadata" poster="/static/shared/assets/mascot-smile.png">
          <source src="/static/shared/assets/character-loop.webm" type="video/webm" />
          <img src="/static/shared/assets/mascot-smile.png" alt="" />
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
    if (message.role === "assistant" && message.streaming) node.classList.add("is-streaming");
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
      node.querySelector(".avatar").style.backgroundImage = 'url("/static/shared/assets/xiaowei-avatar-pro.png")';
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

function applyBusy() {
  const value = state.busy;
  sendButton.disabled = value;
  imageButton.disabled = value;
  micButton.disabled = value;
  messageInput.disabled = value;
}

// 守卫通过（真的发出去了）才清空输入框；Core.sendMessage 在守卫不过时返回 null。
function sendMessage(content) {
  const pending = Core.sendMessage(content);
  if (!pending) return;
  messageInput.value = "";
  messageInput.style.height = "";
  syncComposerTextState();
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

function renderAuthState() {
  const auth = state.auth || { authenticated: false };
  const authenticated = Boolean(auth.authenticated) && !auth.needs_enterprise;
  authScreen.hidden = authenticated;
  if (!auth.authenticated) {
    loginForm.hidden = false;
    registerForm.hidden = true;
    enterpriseForm.hidden = true;
  } else {
    loginForm.hidden = true;
    registerForm.hidden = true;
    enterpriseForm.hidden = !auth.needs_enterprise;
  }
  const label = state.accountProfile?.nickname || auth.enterprise?.name || auth.user?.phone || "未登录";
  accountLabel.textContent = label;
  sessionStatus.textContent = auth.enterprise ? "企业专属档案" : "等待绑定企业";
  setAvatarElement(accountAvatar, state.accountProfile?.avatar_url || "", label);
  composerForm.hidden = !authenticated;
  openProfileButton.disabled = !authenticated;
  openWalletButton.disabled = !authenticated;
  openLoanButton.disabled = !authenticated;
}

function renderWallet() {
  const wallet = state.wallet || { transactions: [], summary: {} };
  walletPeriodTabs.forEach((button) => {
    button.classList.toggle("is-active", button.dataset.walletPeriod === state.walletPeriod);
  });
  walletChartModeButtons.forEach((button) => {
    button.classList.toggle("is-active", button.dataset.walletChart === state.walletChartMode);
  });
  const transactionsForPeriod = wallet.transactions || [];
  const periodStats = walletPeriodStats(transactionsForPeriod, state.walletPeriod);
  const periodName = walletPeriodLabel(state.walletPeriod);
  const anchorText = periodStats.anchor.toLocaleDateString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
  });
  const summary = wallet.summary || {};
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

  const transactions = [...(wallet.transactions || [])].slice(-8).reverse();
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

async function openWallet() {
  if (!state.auth?.authenticated || state.auth?.needs_enterprise) return;
  walletBackdrop.hidden = false;
  walletDrawer.hidden = false;
  walletDrawer.setAttribute("aria-hidden", "false");
  walletEntryForm.hidden = true;
  walletDate.value = new Date().toISOString().slice(0, 10);
  try {
    await Core.loadWallet();
  } catch (error) {
    walletMessage.textContent = `读取失败：${error.message}`;
  }
}

function closeWallet() {
  walletBackdrop.hidden = true;
  walletDrawer.hidden = true;
  walletDrawer.setAttribute("aria-hidden", "true");
}

function renderLoanLoading() {
  loanBody.innerHTML = `
    <div class="loan-loading">
      <span class="loan-spinner" aria-hidden="true"></span>
      <span>正在根据您的风控画像和经营流水预估额度...</span>
    </div>`;
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

const videoCallState = { stream: null, muted: false };

function setVideoCallStatus(text) {
  if (videoCallStatus) videoCallStatus.textContent = text;
}

function showVideoCallSelfPlaceholder(visible) {
  if (videoCallSelfPlaceholder) videoCallSelfPlaceholder.hidden = !visible;
  if (videoCallSelf) videoCallSelf.hidden = visible;
}

function openVideoCall() {
  if (!state.auth?.authenticated || state.auth?.needs_enterprise) return;
  videoCallBackdrop.hidden = false;
  videoCallModal.hidden = false;
  videoCallModal.setAttribute("aria-hidden", "false");
  showVideoCallSelfPlaceholder(!videoCallState.stream);
  setVideoCallStatus("正在接通…");
}

function stopVideoCallStream() {
  // 通话的媒体流/按钮状态现由 voicecall.js 统管，这里只清理 chat.js 自己开过的预览流。
  if (videoCallState.stream) {
    videoCallState.stream.getTracks().forEach((track) => track.stop());
    videoCallState.stream = null;
  }
  videoCallState.muted = false;
}

function closeVideoCall() {
  videoCallBackdrop.hidden = true;
  videoCallModal.hidden = true;
  videoCallModal.setAttribute("aria-hidden", "true");
  stopVideoCallStream();
}

async function startVideoCallPreview() {
  if (videoCallState.stream) return;
  if (!navigator.mediaDevices?.getUserMedia) {
    setVideoCallStatus("当前浏览器不支持 getUserMedia，无法预览摄像头。");
    return;
  }
  videoCallStartButton.disabled = true;
  setVideoCallStatus("正在请求摄像头与麦克风权限...");
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
    videoCallState.stream = stream;
    if (videoCallSelf) videoCallSelf.srcObject = stream;
    showVideoCallSelfPlaceholder(false);
    if (videoCallMuteButton) videoCallMuteButton.disabled = false;
    if (videoCallEndButton) videoCallEndButton.disabled = false;
    setVideoCallStatus("本地预览已开启。远端连接尚未接入，挂断仅关闭本地预览。");
  } catch (error) {
    videoCallStartButton.disabled = false;
    setVideoCallStatus(`无法开启摄像头：${error.message || error.name || "未知错误"}`);
  }
}

function toggleVideoCallMute() {
  if (!videoCallState.stream) return;
  videoCallState.muted = !videoCallState.muted;
  videoCallState.stream.getAudioTracks().forEach((track) => {
    track.enabled = !videoCallState.muted;
  });
  if (videoCallMuteButton) videoCallMuteButton.textContent = videoCallState.muted ? "取消静音" : "静音";
}

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

async function openAccountModal() {
  if (!state.auth?.authenticated || state.auth?.needs_enterprise) return;
  accountBackdrop.hidden = false;
  accountModal.hidden = false;
  accountModal.setAttribute("aria-hidden", "false");
  showAccountMessage("");
  setAccountTab("user");
  try {
    await Core.loadAccountProfile();
  } catch (error) {
    showAccountMessage(`读取失败：${error.message}`, true);
  }
}

function closeAccountModal() {
  accountBackdrop.hidden = true;
  accountModal.hidden = true;
  accountModal.setAttribute("aria-hidden", "true");
}

async function bootstrapApp() {
  try {
    const auth = await getJson("/api/auth/me");
    Core.setAuth(auth);
    if (auth.authenticated && !auth.needs_enterprise) {
      await Core.loadAccountProfile();
      await Core.loadMessages();
      await Core.loadProfile();
      await Core.loadWalletPending();
      if (window.location.hash === "#wallet") {
        await openWallet();
      }
    } else {
      renderMessages();
    }
  } catch (error) {
    Core.setAuth({ authenticated: false });
    showAuthMessage(error.message, true);
    renderMessages();
  }
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
    confirmBtn.onclick = () => Core.resolveWalletPending(item.id, "confirm");
    const rejectBtn = document.createElement("button");
    rejectBtn.type = "button";
    rejectBtn.className = "reject";
    rejectBtn.textContent = "拒绝";
    rejectBtn.disabled = state.walletPendingBusyIds.has(item.id);
    rejectBtn.onclick = () => Core.resolveWalletPending(item.id, "reject");
    controls.appendChild(confirmBtn);
    controls.appendChild(rejectBtn);
    wrap.appendChild(left);
    wrap.appendChild(controls);
    walletPendingList.appendChild(wrap);
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
  if (load) Core.loadProfile();
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
    Core.addAttachment(file);
  }
  imageInput.value = "";
});

fileInput.addEventListener("change", () => {
  for (const file of Array.from(fileInput.files || [])) {
    Core.addAttachment(file);
  }
  fileInput.value = "";
});

videoInput.addEventListener("change", () => {
  for (const file of Array.from(videoInput.files || [])) {
    Core.addAttachment(file);
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
        Core.addAttachment(new File([blob], `voice-${Date.now()}.webm`, { type: blob.type || "audio/webm" }));
      } else if (blob.size > 0) {
        const sendAnyway = confirm("录音音量很低，可能听不清。要仍然发送这段录音吗？\n\n如果你确定刚才说话了，请先检查浏览器麦克风权限和系统输入设备。");
        if (sendAnyway) {
          Core.addAttachment(new File([blob], `voice-${Date.now()}.webm`, { type: blob.type || "audio/webm" }));
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
    Core.setAuth(auth);
    if (auth.needs_enterprise) {
      showAuthMessage("首次登录，请创建企业档案。");
      enterpriseName.focus();
    } else {
      showAuthMessage("");
      await Core.loadAccountProfile();
      await Core.loadMessages();
      await Core.loadProfile();
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
    Core.setAuth(auth);
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
    Core.setAuth(payload.auth);
    await Core.loadAccountProfile();
    await Core.loadMessages();
    await Core.loadProfile();
    showAuthMessage("");
  } catch (error) {
    showAuthMessage(error.message, true);
  }
});

openProfileButton.onclick = openProfile;
closeProfileButton.onclick = closeProfile;
profileBackdrop.onclick = closeProfile;
refreshProfileButton.onclick = async () => {
  const originalLabel = refreshProfileButton.textContent;
  refreshProfileButton.disabled = true;
  refreshProfileButton.textContent = "刷新中...";
  try {
    await Core.refreshProfile();
  } finally {
    refreshProfileButton.disabled = false;
    refreshProfileButton.textContent = originalLabel || "刷新";
  }
};
openWalletButton.onclick = openWallet;
closeWalletButton.onclick = closeWallet;
walletBackdrop.onclick = closeWallet;
openLoanButton.onclick = openLoan;
closeLoanButton.onclick = closeLoan;
loanBackdrop.onclick = closeLoan;
refreshLoanButton.onclick = recomputeLoanEstimate;
openVideoCallButton.addEventListener("click", openVideoCall);
closeVideoCallButton.onclick = closeVideoCall;
videoCallBackdrop.onclick = closeVideoCall;
videoCallStartButton.onclick = startVideoCallPreview;
videoCallMuteButton.onclick = toggleVideoCallMute;
videoCallEndButton.onclick = stopVideoCallStream;
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
    Core.setWallet(payload);
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
    Core.setWallet(payload);
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
    fillAccountForm(state.accountProfile);
    Core.setAuth(payload.auth || state.auth);
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
    fillAccountForm(state.accountProfile);
    Core.setAuth(payload.auth || state.auth);
    showAccountMessage("资料已保存");
  } catch (error) {
    showAccountMessage(error.message, true);
  }
});

logoutButton.onclick = async () => {
  await postJson("/api/auth/logout");
  state.accountProfile = null;
  closeAccountModal();
  Core.setAuth({ authenticated: false });
};

// ---------- Core 事件订阅：数据变化 → 渲染 ----------

Core.on("messages", renderMessages);
Core.on("busy", applyBusy);
Core.on("attachments", renderAttachmentPreview);
Core.on("auth", renderAuthState);
Core.on("account-profile", () => {
  if (state.accountProfile) fillAccountForm(state.accountProfile);
});
Core.on("wallet", renderWallet);
Core.on("wallet-pending", renderWalletPending);
Core.on("profile-markdown", (text) => renderMarkdownInto(profileMarkdown, text));
Core.on("profile-status", (text) => {
  if (profileSummary) profileSummary.textContent = text;
});
Core.on("profile-diff", ({ diff, changed, hidden }) => renderProfileDiff(diff, changed, hidden));
Core.on("notify", (text) => alert(text));

// ---------- 启动 ----------

document.querySelectorAll(".brand-mark").forEach((mark) => {
  mark.style.backgroundImage = 'url("/static/shared/assets/customer-manager-plus.png")';
  mark.classList.add("has-image");
});
setSidebarCollapsed(localStorage.getItem("wewallet.sidebarCollapsed") === "1");
syncResponsiveCopy();
syncComposerTextState();
renderMessages();
bootstrapApp();

// 视频通话挂断、对话已并入会话时，自动重新拉取消息渲染（无需手动刷新浏览器）。
// voicecall.js 在 /api/voicecall/end 落库成功后派发此事件。
document.addEventListener("voicecall:saved", () => {
  Core.loadMessages().catch(() => {});
});

/*
 * 视频通话模块（通话版小微）。
 *
 * 独立于 chat.js 主线：只读已有弹窗的 DOM，用 addEventListener 追加监听，
 * 不覆盖 chat.js 已绑定的 onclick。
 *
 * 两套语音引擎，启动时按后端 /api/voicecall/realtime-config 自动选：
 *   1) realtime（首选）：端到端实时语音（豆包 openspeech 实时对话，或 StepFun stepaudio）。
 *      麦克风 → PCM16/16kHz → WebSocket 中继(/api/voicecall/realtime-config 给地址) → 上游 →
 *      回传 PCM16/24kHz 音频边收边放 + 字幕。服务端 VAD 自动断句、可打断。
 *      ⚠️ 采集 16kHz、播放 24kHz（豆包 ASR 收 16k、TTS 出 24k），故用两个 AudioContext。
 *      看画面：每轮你一开口就静默截一帧发 {type:"vision.frame"}，中继调多模态视觉描述后
 *      注入会话，小微"边看边聊"（无需手动按钮）。
 *   2) placeholder（回落）：浏览器原生 Web Speech API 做 STT/TTS（无 STEP_API_KEY 或
 *      浏览器不支持时）。即旧版形态。
 *
 * 仅在 localhost / https 下可用（getUserMedia + WebSocket/AudioContext 安全上下文）。
 */
(function () {
  "use strict";

  const modal = document.getElementById("videoCallModal");
  const selfVideo = document.getElementById("videoCallSelf");
  const caption = document.getElementById("videoCallCaption");
  const statusEl = document.getElementById("videoCallStatus");
  const talkButton = document.getElementById("videoCallTalkButton");
  const startButton = document.getElementById("videoCallStartButton"); // 现作"摄像头开关"
  const muteButton = document.getElementById("videoCallMuteButton");
  const endButton = document.getElementById("videoCallEndButton");
  const closeButton = document.getElementById("closeVideoCallButton");
  const listeningEl = document.getElementById("videoCallListening");
  const orbEl = document.getElementById("videoCallOrb");
  const backdrop = document.getElementById("videoCallBackdrop");

  if (!talkButton) return; // 没有按钮就不挂（防御）

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  // 上游 ASR 收 16kHz、TTS 出 24kHz：采集和播放用不同采样率的 AudioContext。
  const CAPTURE_RATE = 16000; // 麦克风采集 → 上行（豆包 ASR 要求 16k）
  const PLAYBACK_RATE = 24000; // 下行 TTS 音频（豆包/stepaudio 都出 24k）

  const call = {
    active: false,
    engine: null, // 当前引擎实例（realtime 或 placeholder）
    stream: null, // 仅当 chat.js 没开摄像头时我们自己开的流
  };

  function setStatus(text) {
    if (statusEl) statusEl.textContent = text;
  }

  let captionHideTimer = null;
  function showCaption(text) {
    if (!caption) return;
    if (captionHideTimer) { clearTimeout(captionHideTimer); captionHideTimer = null; }
    caption.classList.remove("is-fading");
    caption.textContent = text || "";
    caption.hidden = !text;
  }
  // 说完一句后让字幕淡出（先渐隐再隐藏），别一直压在画面上。
  function fadeCaptionSoon() {
    if (!caption || caption.hidden) return;
    if (captionHideTimer) clearTimeout(captionHideTimer);
    captionHideTimer = setTimeout(() => {
      caption.classList.add("is-fading");
      captionHideTimer = setTimeout(() => {
        caption.hidden = true;
        caption.classList.remove("is-fading");
        caption.textContent = "";
      }, 600);
    }, 2600);
  }

  // 通话状态 → 光球外观 + 聆听点显隐。state: connecting|listening|speaking|null
  function setCallState(state) {
    if (orbEl) orbEl.className = "vc-orb" + (state ? " is-" + state : "");
    if (listeningEl) listeningEl.style.visibility = state === "listening" ? "visible" : "hidden";
  }
  // 说话时由播放音量实时驱动光球脉动（0~1）。
  function setOrbLevel(level) {
    if (orbEl) orbEl.style.setProperty("--vc-level", String(Math.max(0, Math.min(1, level)) || 0));
  }

  function setListening(on) {
    if (listeningEl) listeningEl.style.visibility = on ? "visible" : "hidden";
  }

  // 当前正在用的媒体流（voicecall 自己开的，或 chat.js 开的）。
  function currentStream() {
    return (selfVideo && selfVideo.srcObject) || call.stream || null;
  }

  function toggleMute() {
    const stream = currentStream();
    if (!stream) return;
    const tracks = stream.getAudioTracks();
    if (!tracks.length) return;
    const muted = tracks[0].enabled; // 现在开着 → 点一下变静音
    tracks.forEach((t) => { t.enabled = !muted; });
    if (muteButton) {
      muteButton.classList.toggle("is-active", muted);
      const label = muteButton.querySelector(".vc-btn-label");
      if (label) label.textContent = muted ? "已静音" : "静音";
    }
  }

  function toggleCamera() {
    const stream = currentStream();
    if (!stream) return;
    const tracks = stream.getVideoTracks();
    if (!tracks.length) return;
    const on = tracks[0].enabled;
    tracks.forEach((t) => { t.enabled = !on; });
    if (startButton) startButton.classList.toggle("is-off", on);
    if (selfVideo) selfVideo.style.opacity = on ? "0" : "1";
  }

  // 复用 chat.js 已开的摄像头流；没有就自己开一路（带麦克风）。
  async function ensureStream() {
    if (selfVideo && selfVideo.srcObject) return selfVideo.srcObject;
    if (!navigator.mediaDevices?.getUserMedia) return null;
    const stream = await navigator.mediaDevices.getUserMedia({
      video: true,
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
    call.stream = stream;
    if (selfVideo) {
      selfVideo.srcObject = stream;
      selfVideo.hidden = false;
    }
    const ph = document.getElementById("videoCallSelfPlaceholder");
    if (ph) ph.hidden = true;
    return stream;
  }

  // 从摄像头画面截一帧，缩到 640 宽的 jpeg dataURL；画面没准备好返回 ""。
  function captureFrame() {
    if (!selfVideo || !selfVideo.videoWidth) return "";
    const maxW = 640;
    const scale = Math.min(1, maxW / selfVideo.videoWidth);
    const w = Math.round(selfVideo.videoWidth * scale);
    const h = Math.round(selfVideo.videoHeight * scale);
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(selfVideo, 0, 0, w, h);
    try {
      return canvas.toDataURL("image/jpeg", 0.6);
    } catch (e) {
      return ""; // 跨域污染等
    }
  }

  // ── PCM16 <-> base64 工具 ───────────────────────────────────────────────
  // worklet 已把麦克风转成 Int16 PCM16，这里只做 ArrayBuffer → base64。
  function pcm16BufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let bin = "";
    for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin);
  }

  function base64ToFloat32(b64) {
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    const i16 = new Int16Array(bytes.buffer, 0, Math.floor(bytes.length / 2));
    const f32 = new Float32Array(i16.length);
    for (let i = 0; i < i16.length; i++) f32[i] = i16[i] / 32768;
    return f32;
  }

  // 一帧 PCM16 的平均能量（0~1），用于 barge-in 判断用户是否在说话。
  function pcm16Level(int16) {
    if (!int16.length) return 0;
    let sum = 0;
    for (let i = 0; i < int16.length; i++) sum += Math.abs(int16[i]) / 32768;
    return Math.min(1, (sum / int16.length) * 5);
  }

  // ════════════════════════════════════════════════════════════════════════
  // 引擎 1：实时语音（stepaudio-2.5-realtime，经本地中继）
  // ════════════════════════════════════════════════════════════════════════
  function RealtimeEngine(wsUrl) {
    let ws = null;
    let captureCtx = null; // 麦克风采集上下文（16kHz）
    let playCtx = null; // TTS 播放上下文（24kHz）
    let micSource = null;
    let workletNode = null; // PCM 采集 worklet 节点（取代已废弃的 ScriptProcessor）
    let analyser = null; // 接在播放链路上，实时取小微声音的音量驱动光球脉动
    let levelRAF = 0; // requestAnimationFrame 句柄
    let nextPlayTime = 0; // 播放调度游标
    const sources = new Set(); // 已排期的播放节点，便于打断时停掉
    let selfCaption = ""; // 小微当前句子字幕累积
    let gotSubtitle = false; // 本轮是否收到过 TTS 字幕事件（有就不用文本兜底，避免字幕翻倍）
    let lastAutoVision = 0; // 上次自动看画面的时间戳（节流）
    let visionBusy = false; // 一次看画面在途，避免叠发
    const AUTO_VISION_MIN_GAP_MS = 3000; // 每轮看一眼，但最快 3 秒一次

    // ── 本地 barge-in 闸门 ──────────────────────────────────────────────────
    // 小微说话时，麦克风会录到她自己的声音（回声消除挡不全）。若原样上传，服务端 VAD
    // 会把这段回声当成"用户在说话"而误打断她。所以她说话期间默认把麦克风压成静音，只有
    // 用户**持续够响**（真想插话）才放行，并本地立即停播实现打断。
    let aiSpeakingUntil = 0; // 预计小微播放到的时间戳（>now 表示她正在说）
    let bargeFrames = 0; // 用户连续够响的帧数
    const BARGE_LEVEL = 0.14; // 判为"用户在说话"的能量阈值
    const BARGE_MIN_FRAMES = 2; // 需连续这么多帧（帧≈43ms，约 86ms）才放行打断，滤掉瞬态噪声

    // 每轮自动看一眼：你一开口就截一帧静默发给中继，等你说完小微回应时已看到当前画面。
    function autoVision() {
      const now = Date.now();
      if (visionBusy || now - lastAutoVision < AUTO_VISION_MIN_GAP_MS) return;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      const frame = captureFrame();
      if (!frame) return;
      lastAutoVision = now;
      visionBusy = true;
      ws.send(JSON.stringify({ type: "vision.frame", frame }));
    }

    function stopPlayback() {
      for (const s of sources) {
        try { s.stop(); } catch (e) {}
      }
      sources.clear();
      nextPlayTime = 0;
      aiSpeakingUntil = 0; // 已停播，立刻恢复正常上传麦克风
    }

    // 用播放链路上的 analyser 实时取音量 → 驱动光球脉动（比逐块算 RMS 更平滑、连续）。
    function pollLevel() {
      if (!analyser) return;
      const buf = new Uint8Array(analyser.fftSize);
      analyser.getByteTimeDomainData(buf);
      let s = 0;
      for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; s += v * v; }
      setOrbLevel(Math.min(1, Math.sqrt(s / buf.length) * 3.2));
      levelRAF = requestAnimationFrame(pollLevel);
    }

    function playDelta(f32) {
      if (!playCtx || !f32.length) return;
      const buf = playCtx.createBuffer(1, f32.length, PLAYBACK_RATE);
      buf.copyToChannel(f32, 0);
      const src = playCtx.createBufferSource();
      src.buffer = buf;
      src.connect(analyser || playCtx.destination); // 经 analyser 再到扬声器，便于取音量
      const now = playCtx.currentTime;
      if (nextPlayTime < now) nextPlayTime = now;
      src.start(nextPlayTime);
      nextPlayTime += buf.duration;
      sources.add(src);
      src.onended = () => sources.delete(src);
      // 标记小微预计播放到何时（+400ms 余量），barge-in 闸门据此判断她是否在说话。
      aiSpeakingUntil = Date.now() + Math.max(0, nextPlayTime - now) * 1000 + 400;
    }

    function handleEvent(ev) {
      switch (ev.type) {
        case "input_audio_buffer.speech_started":
          // 客户开口 → 打断小微正在播的话（barge-in）+ 顺手截一帧让她"看到"当前画面。
          stopPlayback();
          setCallState("listening");
          setOrbLevel(0);
          setStatus("在听您说...");
          autoVision();
          break;
        case "response.audio.delta":
          if (ev.delta) { setCallState("speaking"); playDelta(base64ToFloat32(ev.delta)); }
          break;
        case "response.audio_transcript.delta":
          gotSubtitle = true;
          selfCaption += ev.delta || "";
          showCaption("小微：" + selfCaption);
          break;
        case "response.text.delta":
          // 字幕兜底：豆包实时对话发的是文本(ChatResponse)而非 TTS 字幕事件，没有
          // audio_transcript.delta；本轮若没收到字幕事件，就用文本当字幕显示。
          if (!gotSubtitle) {
            selfCaption += ev.delta || "";
            showCaption("小微：" + selfCaption);
          }
          break;
        case "response.audio_transcript.done":
          if (ev.transcript) showCaption("小微：" + ev.transcript);
          selfCaption = "";
          gotSubtitle = false;
          break;
        case "response.done":
          // 一轮回复结束：清字幕累积，下一轮重新开始（豆包无 audio_transcript.done）。
          selfCaption = "";
          gotSubtitle = false;
          setCallState("listening");
          setOrbLevel(0);
          fadeCaptionSoon();
          break;
        case "conversation.item.input_audio_transcription.completed":
          if (ev.transcript) setStatus("我：" + ev.transcript);
          break;
        case "vision.described":
          // 每轮自动看画面是静默的：只复位单飞闸门，让下一轮可以再看；不打扰字幕/状态。
          visionBusy = false;
          break;
        case "error":
          setStatus("出错了：" + (ev.error?.message || ev.message || "未知"));
          break;
      }
    }

    async function start() {
      const stream = await ensureStream();
      if (!stream) throw new Error("无法获取摄像头/麦克风");
      const Ctx = window.AudioContext || window.webkitAudioContext;
      captureCtx = new Ctx({ sampleRate: CAPTURE_RATE });
      playCtx = new Ctx({ sampleRate: PLAYBACK_RATE });
      if (captureCtx.state === "suspended") await captureCtx.resume();
      if (playCtx.state === "suspended") await playCtx.resume();
      // 播放链路上接 analyser 取小微声音的实时音量（驱动光球脉动），再接到扬声器。
      analyser = playCtx.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.6;
      analyser.connect(playCtx.destination);
      pollLevel();
      // worklet 模块必须在建节点前加载好（异步）。
      await captureCtx.audioWorklet.addModule("/static/audio-worklet/pcm-recorder.js");

      ws = new WebSocket(wsUrl);
      ws.onopen = () => {
        setStatus("通话已接通，请直接说话，小微在听...");
        setCallState("listening");
        // 麦克风采集（worklet 音频线程）→ PCM16 块 → input_audio_buffer.append
        micSource = captureCtx.createMediaStreamSource(stream);
        workletNode = new AudioWorkletNode(captureCtx, "pcm-recorder");
        workletNode.port.onmessage = (e) => {
          if (!ws || ws.readyState !== WebSocket.OPEN) return;
          let outBuf = e.data; // 默认转发真实麦克风音频
          if (Date.now() < aiSpeakingUntil) {
            // 小微正在说话：默认压成静音，避免她的声音被麦克风录回去误触发打断。
            const level = pcm16Level(new Int16Array(e.data));
            if (level >= BARGE_LEVEL) {
              bargeFrames += 1;
              if (bargeFrames >= BARGE_MIN_FRAMES) {
                stopPlayback(); // 用户确实想插话 → 本地立即停播，本帧起转发真实音频
                bargeFrames = 0;
              } else {
                outBuf = new ArrayBuffer(e.data.byteLength); // 还没够帧，先发静音
              }
            } else {
              bargeFrames = 0;
              outBuf = new ArrayBuffer(e.data.byteLength); // 不够响：发静音
            }
          } else {
            bargeFrames = 0;
          }
          ws.send(JSON.stringify({
            type: "input_audio_buffer.append",
            audio: pcm16BufferToBase64(outBuf),
          }));
        };
        micSource.connect(workletNode);
        // worklet 不输出声音（process 不写 outputs），接到 destination 只为让它被调度、不会回放。
        workletNode.connect(captureCtx.destination);
      };
      ws.onmessage = (e) => {
        let data;
        try { data = JSON.parse(e.data); } catch (err) { return; }
        handleEvent(data);
      };
      ws.onerror = () => setStatus("连接出错，请稍后重试。");
      ws.onclose = () => { if (call.active) setStatus("连接已断开。"); };
    }

    function stop() {
      stopPlayback();
      if (levelRAF) { cancelAnimationFrame(levelRAF); levelRAF = 0; }
      analyser = null;
      try { workletNode && workletNode.disconnect(); } catch (e) {}
      try { micSource && micSource.disconnect(); } catch (e) {}
      if (workletNode) workletNode.port.onmessage = null;
      workletNode = null;
      micSource = null;
      if (ws) {
        try { ws.close(); } catch (e) {}
        ws = null;
      }
      if (captureCtx) {
        try { captureCtx.close(); } catch (e) {}
        captureCtx = null;
      }
      if (playCtx) {
        try { playCtx.close(); } catch (e) {}
        playCtx = null;
      }
    }

    return { start, stop };
  }

  // ════════════════════════════════════════════════════════════════════════
  // 引擎 2：浏览器原生语音占位（回落用，旧版形态）
  // 麦克风 → SpeechRecognition → POST /api/voicecall → Doubao/StepFun 文本 →
  // SpeechSynthesis 念出 + 字幕。看材料随每轮自动截帧。
  // ════════════════════════════════════════════════════════════════════════
  function PlaceholderEngine() {
    const state = { recognition: null, speaking: false, history: [], sending: false };

    function speak(text) {
      return new Promise((resolve) => {
        if (!window.speechSynthesis) { resolve(); return; }
        const utter = new SpeechSynthesisUtterance(text);
        utter.lang = "zh-CN";
        utter.rate = 1.05;
        const zh = window.speechSynthesis.getVoices().find((v) => /zh|Chinese/i.test(v.lang || v.name));
        if (zh) utter.voice = zh;
        utter.onend = resolve;
        utter.onerror = resolve;
        window.speechSynthesis.speak(utter);
      });
    }

    async function sendTurn(transcript) {
      if (state.sending) return;
      state.sending = true;
      setStatus("小微正在听...");
      const frame = captureFrame();
      try {
        const resp = await fetch("/api/voicecall", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ transcript, frame, history: state.history.slice(-8) }),
        });
        const data = await resp.json();
        if (!resp.ok || data.error) throw new Error(data.error || `HTTP ${resp.status}`);
        const reply = String(data.reply || "").trim();
        state.history.push({ role: "user", content: transcript });
        state.history.push({ role: "assistant", content: reply });
        showCaption("小微：" + reply);
        state.speaking = true;
        pauseRecognition();
        // 占位模式拿不到逐帧音量，用轻量起伏让光球"说话"时有动静。
        setCallState("speaking");
        let t = 0;
        const wiggle = setInterval(() => { t += 0.3; setOrbLevel(0.3 + 0.3 * Math.abs(Math.sin(t))); }, 110);
        await speak(reply);
        clearInterval(wiggle);
        setOrbLevel(0);
        state.speaking = false;
        if (call.active) { setStatus("请说话，小微在听..."); setCallState("listening"); fadeCaptionSoon(); startRecognition(); }
      } catch (e) {
        setStatus("网络好像有点慢：" + (e.message || e));
      } finally {
        state.sending = false;
      }
    }

    function buildRecognition() {
      const rec = new SpeechRecognition();
      rec.lang = "zh-CN";
      rec.continuous = true;
      rec.interimResults = true;
      rec.onresult = (event) => {
        if (state.speaking) return;
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const result = event.results[i];
          if (result.isFinal) {
            const text = (result[0].transcript || "").trim();
            if (text) sendTurn(text);
          }
        }
      };
      rec.onend = () => {
        if (call.active && !state.speaking) {
          try { rec.start(); } catch (e) {}
        }
      };
      rec.onerror = (e) => {
        if (e.error === "not-allowed" || e.error === "service-not-allowed") {
          setStatus("麦克风权限被拒绝，无法对话。");
          stopCall();
        }
      };
      return rec;
    }

    function startRecognition() {
      if (!state.recognition) state.recognition = buildRecognition();
      try { state.recognition.start(); } catch (e) {}
    }
    function pauseRecognition() {
      if (state.recognition) { try { state.recognition.stop(); } catch (e) {} }
    }

    async function start() {
      if (!SpeechRecognition) throw new Error("当前浏览器不支持语音识别（建议用 Chrome/Edge）。");
      await ensureStream();
      setStatus("通话已开始，请直接说话，小微在听...");
      setCallState("listening");
      sendTurn("（通话刚接通，请用一句话热情地跟客户打招呼并自我介绍）");
      startRecognition();
    }

    function stop() {
      state.speaking = false;
      pauseRecognition();
      state.recognition = null;
      if (window.speechSynthesis) window.speechSynthesis.cancel();
    }

    return { start, stop };
  }

  // ── 通话生命周期 ─────────────────────────────────────────────────────────
  async function fetchBackend() {
    try {
      const resp = await fetch("/api/voicecall/realtime-config");
      if (!resp.ok) return null;
      return await resp.json();
    } catch (e) {
      return null;
    }
  }

  function resolveWsUrl(cfg) {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    let base;
    if (cfg.ws_url) {
      base = cfg.ws_url; // 1) 完整地址
    } else if (cfg.relay_path) {
      base = `${proto}//${location.host}${cfg.relay_path}`; // 2) 同源路径（http→ws / https→wss）
    } else {
      base = `${proto}//${location.hostname}:${cfg.relay_port}`; // 3) 本地按端口直连
    }
    // 带上中继访问令牌（浏览器 WS 设不了 header，只能走 query）。
    if (cfg.token) base += (base.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(cfg.token);
    return base;
  }

  async function startCall() {
    if (call.active) return;
    call.active = true;
    talkButton.textContent = "结束对话";
    if (muteButton) muteButton.disabled = false;
    showCaption("");
    setStatus("正在接通…");
    setCallState("connecting");
    setListening(true);

    const cfg = await fetchBackend();
    const useRealtime = cfg && cfg.enabled && "WebSocket" in window &&
      (window.AudioContext || window.webkitAudioContext);

    try {
      call.engine = useRealtime ? RealtimeEngine(resolveWsUrl(cfg)) : PlaceholderEngine();
      await call.engine.start();
    } catch (e) {
      setStatus(e.message || String(e));
      stopCall();
    }
  }

  function stopCall() {
    if (!call.active && !call.stream && !call.engine) return;
    call.active = false;
    setListening(false);
    setCallState(null);
    setOrbLevel(0);
    if (call.engine) { try { call.engine.stop(); } catch (e) {} call.engine = null; }
    // 只关我们自己开的流；chat.js 开的留给它管。
    if (call.stream) {
      call.stream.getTracks().forEach((t) => t.stop());
      call.stream = null;
      if (selfVideo) selfVideo.srcObject = null;
    }
    talkButton.textContent = "和小微对话";
    if (muteButton) {
      muteButton.disabled = true;
      muteButton.classList.remove("is-active");
    }
    if (startButton) startButton.classList.remove("is-off");
    if (selfVideo) selfVideo.style.opacity = "1";
  }

  // 微信式体验：打开通话即自动接通（开摄像头+麦克风+连小微）。
  // 监听弹窗的 hidden 变化，由 chat.js 的 openVideoCall() 触发。
  if (modal && "MutationObserver" in window) {
    let wasHidden = modal.hidden;
    new MutationObserver(() => {
      const hidden = modal.hidden;
      if (hidden === wasHidden) return;
      wasHidden = hidden;
      if (!hidden) {
        showCaption("");
        startCall();
      } else {
        stopCall();
      }
    }).observe(modal, { attributes: true, attributeFilter: ["hidden"] });
  }

  // talkButton 已隐藏，仍保留点击=开始/结束，作回落入口。
  talkButton.addEventListener("click", () => {
    if (call.active) stopCall();
    else startCall();
  });

  // 接管"摄像头开关"和"静音"（覆盖 chat.js 的 onclick，避免重复开流/空操作）。
  if (startButton) startButton.onclick = toggleCamera;
  if (muteButton) muteButton.onclick = toggleMute;

  // 挂断：收尾对话并关闭整个通话界面。
  if (endButton) {
    endButton.addEventListener("click", () => {
      stopCall();
      if (closeButton) closeButton.click();
    });
  }
  // 关闭按钮/点遮罩：收尾对话（关闭弹窗由 chat.js 负责，observer 也会兜底 stop）。
  if (closeButton) closeButton.addEventListener("click", stopCall);
  if (backdrop) backdrop.addEventListener("click", stopCall);

  // 预热语音列表（部分浏览器首次为空）。
  if (window.speechSynthesis) {
    window.speechSynthesis.onvoiceschanged = () => {};
    window.speechSynthesis.getVoices();
  }
})();

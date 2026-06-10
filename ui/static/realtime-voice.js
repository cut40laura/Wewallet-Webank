// 实时语音客户端：纯 Web Audio + WebSocket，移植自 credit-agent-h5/lib/realtime-voice.ts。
// 语音/视频通话共用；通过 window.createRealtimeVoiceClient(options) 创建。
(function () {
  "use strict";

  const DEFAULT_WS_URL = "ws://localhost:8870/v1/realtime-voice/stream";
  const DEFAULT_WORKLET_URL = "/static/audio-worklet/pcm-recorder.js";

  // 打断（barge-in）本地 VAD 闸门。
  // 阈值调高、要求持续更久：AI 说长句时，回声/环境噪声不再被误判为"用户开口"而掐断播放。
  // 只有明显且持续的真人语音（≥0.22 连续 14 帧）才打断 AI。
  const BARGE_LEVEL = 0.22;
  const BARGE_MIN_FRAMES = 14;

  function createEventId(prefix) {
    return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
  }

  function createRealtimeVoiceClient(options) {
    let socket = null;
    let stream = null;
    let audioContext = null;
    let playbackContext = null;
    let playbackCursor = 0;
    let workletNode = null;
    let sourceNode = null;
    let muted = false;
    let mockTimer = null;
    let stopped = false;
    let aiSpeakingUntil = 0;
    let bargeFrames = 0;
    let audioSent = false;
    let scheduledSources = [];
    let holdPlayback = false;

    const workletUrl = options.workletUrl || DEFAULT_WORKLET_URL;

    async function start() {
      stopped = false;
      options.onStatus("connecting");
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: options.video !== false,
          audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
        });
      } catch (error) {
        options.onStatus("error", error instanceof Error ? error.message : "无法获取摄像头或麦克风权限");
        return null;
      }

      if (stopped) {
        stream.getTracks().forEach((track) => track.stop());
        stream = null;
        return null;
      }

      const baseWsUrl = options.wsUrl || DEFAULT_WS_URL;
      const wsUrl = options.scene
        ? baseWsUrl + (baseWsUrl.includes("?") ? "&" : "?") + "scene=" + encodeURIComponent(options.scene)
        : baseWsUrl;
      socket = new WebSocket(wsUrl);

      socket.onopen = async () => {
        options.onStatus("open");
        await startAudioPipeline(stream);
      };
      socket.onerror = async () => {
        options.onStatus("mock", "实时语音代理未启动，已进入本地模拟。");
        await startAudioPipeline(stream);
        startMockLoop();
      };
      socket.onclose = () => {
        if (!mockTimer) options.onStatus("closed");
      };
      socket.onmessage = (event) => {
        if (typeof event.data !== "string") return;
        const payload = parseJson(event.data);
        if (!payload) return;
        handleServerMessage(payload);
      };

      return stream;
    }

    async function startAudioPipeline(activeStream) {
      if (!activeStream || audioContext) return;
      audioContext = new AudioContext({ sampleRate: 16000 });
      await audioContext.audioWorklet.addModule(workletUrl);
      sourceNode = audioContext.createMediaStreamSource(activeStream);
      workletNode = new AudioWorkletNode(audioContext, "pcm-recorder");
      workletNode.port.onmessage = (event) => {
        const buffer = event.data;
        const level = calculateLevel(new Int16Array(buffer));
        options.onAudioLevel(level);
        if (muted || !socket || socket.readyState !== WebSocket.OPEN) return;
        const silence = new ArrayBuffer(buffer.byteLength);
        let outbound = buffer;
        if (Date.now() < aiSpeakingUntil) {
          if (options.bargeIn && level >= BARGE_LEVEL) {
            bargeFrames += 1;
            if (bargeFrames >= BARGE_MIN_FRAMES) {
              stopPlayback();
              bargeFrames = 0;
              outbound = buffer;
            } else {
              outbound = silence;
            }
          } else {
            bargeFrames = 0;
            outbound = silence;
          }
        } else {
          bargeFrames = 0;
        }
        socket.send(
          JSON.stringify({
            type: "input_audio_buffer.append",
            event_id: createEventId("audio"),
            audio: arrayBufferToBase64(outbound)
          })
        );
        audioSent = true;
      };
      sourceNode.connect(workletNode);
      workletNode.connect(audioContext.destination);
    }

    function commitTurn() {
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: "input_audio_buffer.commit", event_id: createEventId("commit") }));
        return;
      }
      options.onUserText("用户语音已提交");
      options.onAiText("我听到了。请继续展示经营场所，我会同步记录核验要点。");
    }

    function handleServerMessage(payload) {
      const type = String(payload.type || payload.event || "");
      if (type === "input_audio_buffer.speech_started") {
        if (options.bargeIn) stopPlayback();
        return;
      }
      if (type === "proxy.mock") {
        options.onStatus("mock", String(payload.message || "未配置豆包凭证"));
        return;
      }
      if (type === "proxy.error") {
        const message = String(payload.message || "豆包实时语音连接失败");
        if (/idle|timeout|空闲|超时/i.test(message)) {
          options.onStatus("open", "等待您说话…");
          return;
        }
        options.onStatus("error", message);
        return;
      }
      if (type === "proxy.upstream_session_started") {
        options.onStatus("open", "豆包实时语音会话已建立");
        if (typeof options.onSessionReady === "function") options.onSessionReady();
        return;
      }
      if (type === "response.audio.delta" && typeof payload.audio === "string") {
        if (holdPlayback) return;
        playPcmAudio(payload.audio, Number(payload.sample_rate || 24000));
        return;
      }
      if (type.startsWith("input_audio_transcription")) {
        // 豆包 ASR 每包回传的是“这句的累积全文”，不是增量；.done 标记这句说完。
        if (type === "input_audio_transcription.done") {
          options.onUserText("", true); // 封口当前这句，下句另起
          return;
        }
        const text = String(payload.delta || payload.text || "");
        if (text) options.onUserText(text, false); // 用最新全文替换当前这句
        return;
      }
      if (type === "response.text.delta") {
        if (holdPlayback) return;
        const text = String(payload.delta || payload.text || "");
        if (text) options.onAiText(text);
        return;
      }
    }

    function playPcmAudio(base64Audio, sampleRate) {
      playbackContext = playbackContext || new AudioContext();
      const bytes = base64ToUint8Array(base64Audio);
      const pcm = new Int16Array(bytes.buffer, bytes.byteOffset, Math.floor(bytes.byteLength / 2));
      const audioBuffer = playbackContext.createBuffer(1, pcm.length, sampleRate);
      const channel = audioBuffer.getChannelData(0);
      for (let i = 0; i < pcm.length; i += 1) {
        channel[i] = Math.max(-1, Math.min(1, pcm[i] / 32768));
      }

      const source = playbackContext.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(playbackContext.destination);
      scheduledSources.push(source);
      source.onended = () => {
        scheduledSources = scheduledSources.filter((item) => item !== source);
      };
      const startAt = Math.max(playbackContext.currentTime + 0.02, playbackCursor);
      source.start(startAt);
      playbackCursor = startAt + audioBuffer.duration;
      aiSpeakingUntil = Date.now() + Math.max(0, playbackCursor - playbackContext.currentTime) * 1000 + 400;
    }

    function stopPlayback() {
      scheduledSources.forEach((source) => {
        try {
          source.onended = null;
          source.stop();
        } catch (e) {
          // ignore
        }
      });
      scheduledSources = [];
      if (playbackContext) playbackCursor = playbackContext.currentTime;
      aiSpeakingUntil = 0;
    }

    function startMockLoop() {
      if (mockTimer) return;
      mockTimer = window.setInterval(() => {
        options.onAudioLevel(0.25 + Math.random() * 0.65);
      }, 140);
    }

    function stop() {
      stopped = true;
      aiSpeakingUntil = 0;
      audioSent = false;
      holdPlayback = false;
      scheduledSources = [];
      if (mockTimer) window.clearInterval(mockTimer);
      mockTimer = null;
      if (workletNode) workletNode.disconnect();
      if (sourceNode) sourceNode.disconnect();
      if (audioContext) audioContext.close();
      if (playbackContext) playbackContext.close();
      if (stream) stream.getTracks().forEach((track) => track.stop());
      if (socket) socket.close();
      socket = null;
      stream = null;
      audioContext = null;
      playbackContext = null;
      playbackCursor = 0;
      workletNode = null;
      sourceNode = null;
    }

    return {
      start,
      stop,
      commitTurn,
      setMuted(nextMuted) {
        muted = nextMuted;
        if (stream) {
          stream.getAudioTracks().forEach((track) => {
            track.enabled = !nextMuted;
          });
        }
      },
      sendVideoFrame(image) {
        if (!socket || socket.readyState !== WebSocket.OPEN || !audioSent) return;
        const base64 = image.includes("base64,") ? image.split("base64,")[1] : image;
        socket.send(JSON.stringify({ type: "input_image_buffer.append", image: base64 }));
      },
      sendText(text) {
        if (!socket || socket.readyState !== WebSocket.OPEN) return;
        const content = String(text || "").trim();
        if (!content) return;
        socket.send(JSON.stringify({ type: "input_text", text: content }));
      },
      // 静默喂上下文：豆包会收入对话记忆，但代理吞掉这条的播报（不让 AI 念出来）
      sendContext(text) {
        if (!socket || socket.readyState !== WebSocket.OPEN) return;
        const content = String(text || "").trim();
        if (!content) return;
        socket.send(JSON.stringify({ type: "context_text", text: content }));
      },
      interrupt() {
        stopPlayback();
        if (socket && socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: "response.cancel" }));
        }
      },
      setHoldPlayback(hold) {
        holdPlayback = hold;
        if (hold) stopPlayback();
      }
    };
  }

  function parseJson(value) {
    try {
      return JSON.parse(value);
    } catch (e) {
      return null;
    }
  }

  function arrayBufferToBase64(buffer) {
    let binary = "";
    const bytes = new Uint8Array(buffer);
    for (let i = 0; i < bytes.byteLength; i += 1) {
      binary += String.fromCharCode(bytes[i]);
    }
    return window.btoa(binary);
  }

  function base64ToUint8Array(value) {
    const binary = window.atob(value);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) {
      bytes[i] = binary.charCodeAt(i);
    }
    return bytes;
  }

  function calculateLevel(samples) {
    if (!samples.length) return 0;
    let sum = 0;
    for (let i = 0; i < samples.length; i += 1) {
      sum += Math.abs(samples[i]) / 32768;
    }
    return Math.min(1, (sum / samples.length) * 5);
  }

  window.createRealtimeVoiceClient = createRealtimeVoiceClient;
})();

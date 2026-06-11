/*
 * PCM 采集 worklet：在音频渲染线程把麦克风 float32 累积成定长块、转 Int16(PCM16) 后
 * 投递给主线程。取代旧的 ScriptProcessorNode——后者已废弃且跑在主线程，UI 一忙就爆音、
 * 加延迟。worklet 跑在独立音频线程，采集稳定。
 *
 * 采样率由创建 AudioContext 时决定（采集上下文是 16kHz，对齐豆包 ASR），这里不重采样。
 * 累积到 FRAME_SAMPLES 再投递：太碎会发出海量 WS 小消息，太大则增延迟、降打断灵敏度。
 * 1024@16kHz ≈ 64ms，兼顾低延迟、可接受的消息数，和 barge-in 的逐帧能量判断粒度。
 */
const FRAME_SAMPLES = 1024;

class PcmRecorderProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buf = new Float32Array(FRAME_SAMPLES);
    this._n = 0;
  }

  process(inputs) {
    const input = inputs[0] && inputs[0][0];
    if (!input) return true; // 麦克风暂无数据：保持节点存活
    for (let i = 0; i < input.length; i += 1) {
      this._buf[this._n] = input[i];
      this._n += 1;
      if (this._n === FRAME_SAMPLES) {
        const pcm = new Int16Array(FRAME_SAMPLES);
        for (let j = 0; j < FRAME_SAMPLES; j += 1) {
          const s = Math.max(-1, Math.min(1, this._buf[j]));
          pcm[j] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }
        // transfer 所有权，零拷贝交给主线程
        this.port.postMessage(pcm.buffer, [pcm.buffer]);
        this._n = 0;
      }
    }
    return true;
  }
}

registerProcessor("pcm-recorder", PcmRecorderProcessor);

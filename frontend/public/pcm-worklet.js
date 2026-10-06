/**
 * PCM 采集 AudioWorklet：把 128 帧的渲染量子攒成 512 帧（16k 下 32ms）一批回传主线程。
 *
 * 只做采集与批量搬运，VAD 判定全在主线程纯函数（src/utils/audioVad.js）里——worklet 是
 * 独立编译单元（不能有 import、无法被 node 单测），逻辑越薄越好。
 *
 * 放在 `public/` 而非 `src/utils/`：Vite 会把 4KB 以下资产内联成 base64 data URL，
 * 而 `audioWorklet.addModule()` 不接受 data URL（模块脚本要求同源脚本 URL）——
 * public 目录的文件原样伺服、不经构建处理，dev 与 build 行为一致。
 */
class PcmCollector extends AudioWorkletProcessor {
  constructor() {
    super()
    this._buf = []
    this._count = 0
    this._start = 0
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0]
    if (ch && ch.length) {
      this._buf.push(new Float32Array(ch))
      this._count += ch.length
      if (this._count >= 512) {
        const out = new Float32Array(this._count)
        let off = 0
        for (const b of this._buf) {
          out.set(b, off)
          off += b.length
        }
        this.port.postMessage({ samples: out, startSample: this._start }, [out.buffer])
        this._start += this._count
        this._buf = []
        this._count = 0
      }
    }
    return true
  }
}

registerProcessor('pcm-collector', PcmCollector)

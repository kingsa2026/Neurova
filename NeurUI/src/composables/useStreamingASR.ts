/**
 * useStreamingASR - 后端流式 ASR WebSocket 客户端（对照报告 B4-1 落地）。
 *
 * 协议（/api/v1/audio/asr/stream，token 走 query）：
 * - 上行：二进制帧 = PCM16LE 单声道 16kHz 原始字节；
 *   JSON 控制 {"type":"finish"}（终结当前轮）/ {"type":"stop"}（终结并关闭）。
 * - 下行：ready/partial/final/error/pong。
 *
 * 采集：getUserMedia → AudioContext → ScriptProcessor → 线性重采样 16k →
 * PCM16。服务端负责 turn 终结（说话后静默 ≥700ms 自动切轮），客户端只在
 * stop 时补发 finish 确保尾轮落 final。
 */

import { readAccessToken } from '@/utils/authSession'

export interface StreamingAsrCallbacks {
  onReady?: (engine: string) => void
  onPartial?: (text: string, turnId: number) => void
  onFinal?: (text: string, turnId: number, reason: string) => void
  onError?: (code: string, message: string) => void
  onClose?: () => void
}

/** 由 axios 同源 base 推导 WS 地址（与 useSessionSync 同一换算口径）；language 可选 zh/en */
export function buildAsrStreamUrl(language?: string): string {
  const base = import.meta.env.VITE_API_BASE_URL || '/api/v1'
  const wsBase = base.replace(/^http/, 'ws')
  const token = readAccessToken()
  const params: string[] = []
  if (token) params.push(`token=${encodeURIComponent(token)}`)
  if (language) params.push(`language=${encodeURIComponent(language)}`)
  return `${wsBase}/audio/asr/stream${params.length ? `?${params.join('&')}` : ''}`
}

/** Float32 采样 → PCM16LE 字节（限幅） */
export function floatToPcm16(input: Float32Array): ArrayBuffer {
  const buffer = new ArrayBuffer(input.length * 2)
  const view = new DataView(buffer)
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]))
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true)
  }
  return buffer
}

/** 线性插值重采样到目标采样率后转 PCM16LE */
export function resampleToPcm16(input: Float32Array, fromRate: number, toRate: number): ArrayBuffer {
  if (fromRate === toRate || fromRate <= 0) {
    return floatToPcm16(input)
  }
  const ratio = fromRate / toRate
  const outLen = Math.max(0, Math.floor(input.length / ratio))
  const out = new Float32Array(outLen)
  for (let i = 0; i < outLen; i++) {
    const pos = i * ratio
    const idx = Math.floor(pos)
    const frac = pos - idx
    const a = input[idx] ?? 0
    const b = input[idx + 1] ?? a
    out[i] = a + (b - a) * frac
  }
  return floatToPcm16(out)
}

export class StreamingAsrSession {
  private ws: WebSocket | null = null
  private audioContext: AudioContext | null = null
  private mediaStream: MediaStream | null = null
  private sourceNode: MediaStreamAudioSourceNode | null = null
  private processor: ScriptProcessorNode | null = null
  private readonly targetSampleRate = 16000
  private lastFinalAt = 0
  private closedByUser = false
  private stopped = false

  constructor(
    private readonly callbacks: StreamingAsrCallbacks,
    private readonly language?: string,
  ) {}

  /** 打开 WS（等 ready 帧）并开始麦克风采集 */
  async start(): Promise<void> {
    await this.openSocket()
    await this.openMic()
  }

  private openSocket(): Promise<void> {
    return new Promise((resolve, reject) => {
      let settled = false
      const ws = new WebSocket(buildAsrStreamUrl(this.language))
      ws.binaryType = 'arraybuffer'
      this.ws = ws
      ws.onmessage = (ev: MessageEvent) => {
        let frame: Record<string, unknown>
        try {
          frame = JSON.parse(String(ev.data)) as Record<string, unknown>
        } catch {
          return
        }
        const type = String(frame.type ?? '')
        if (type === 'ready') {
          if (!settled) {
            settled = true
            resolve()
          }
          this.callbacks.onReady?.(String(frame.engine ?? ''))
          return
        }
        if (type === 'partial') {
          this.callbacks.onPartial?.(String(frame.text ?? ''), Number(frame.turn_id ?? 0))
          return
        }
        if (type === 'final') {
          this.lastFinalAt = Date.now()
          this.callbacks.onFinal?.(String(frame.text ?? ''), Number(frame.turn_id ?? 0), String(frame.reason ?? ''))
          return
        }
        if (type === 'error') {
          const message = String(frame.message ?? '流式识别失败')
          this.callbacks.onError?.(String(frame.code ?? ''), message)
          if (!settled) {
            settled = true
            reject(new Error(message))
          }
        }
      }
      ws.onerror = () => {
        if (!settled) {
          settled = true
          reject(new Error('流式 ASR 连接失败'))
        }
      }
      ws.onclose = () => {
        this.cleanupAudio()
        this.callbacks.onClose?.()
      }
    })
  }

  private async openMic(): Promise<void> {
    const mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    })
    // 竞态防护：麦克风授权期间被 stop/abort → 立即还轨，不再进入采集
    if (this.stopped || this.closedByUser) {
      mediaStream.getTracks().forEach((t) => t.stop())
      throw new Error('流式识别已停止')
    }
    this.mediaStream = mediaStream
    const AudioCtor = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
    const ctx = new AudioCtor()
    this.audioContext = ctx
    const source = ctx.createMediaStreamSource(mediaStream)
    this.sourceNode = source
    // ScriptProcessor 虽被标记过时，但免 Worklet 模块文件即可跨端采集（保留至有 Worklet 管线为止）
    const processor = ctx.createScriptProcessor(4096, 1, 1)
    this.processor = processor
    processor.onaudioprocess = (e: AudioProcessingEvent) => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return
      const input = e.inputBuffer.getChannelData(0)
      const pcm = resampleToPcm16(input, ctx.sampleRate, this.targetSampleRate)
      if (pcm.byteLength > 0) {
        this.ws.send(pcm)
      }
    }
    source.connect(processor)
    processor.connect(ctx.destination)
  }

  /**
   * 停止采集并终结当前轮。服务端静默切轮可能早已发过 final（1s 内视为
   * 已终结，不再等待）；否则补发 finish 后等 final 至多 3s，随后 stop 关闭。
   */
  async stop(): Promise<void> {
    const ws = this.ws
    this.stopped = true
    this.cleanupAudio()
    if (!ws || ws.readyState !== WebSocket.OPEN || this.closedByUser) {
      this.hardClose()
      return
    }
    if (Date.now() - this.lastFinalAt > 1000) {
      await new Promise<void>((resolve) => {
        const timer = setTimeout(resolve, 3000)
        const prevFinal = this.callbacks.onFinal
        this.callbacks.onFinal = (text, turnId, reason) => {
          this.callbacks.onFinal = prevFinal
          prevFinal?.(text, turnId, reason)
          clearTimeout(timer)
          resolve()
        }
        ws.send(JSON.stringify({ type: 'finish' }))
      })
    }
    if (!this.closedByUser && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify({ type: 'stop' }))
      } catch {
        // 连接可能已被服务端关闭
      }
    }
    this.hardClose()
  }

  /** 立即放弃：不终结当前轮（取消录音用） */
  abort(): void {
    this.closedByUser = true
    this.stopped = true
    this.cleanupAudio()
    this.hardClose()
  }

  private hardClose(): void {
    try {
      this.ws?.close()
    } catch {
      // 忽略重复关闭
    }
    this.ws = null
  }

  private cleanupAudio(): void {
    try {
      this.processor?.disconnect()
    } catch {
      // 已断开
    }
    this.processor = null
    try {
      this.sourceNode?.disconnect()
    } catch {
      // 已断开
    }
    this.sourceNode = null
    try {
      this.mediaStream?.getTracks().forEach((t) => t.stop())
    } catch {
      // 已停止
    }
    this.mediaStream = null
    if (this.audioContext && this.audioContext.state !== 'closed') {
      this.audioContext.close().catch(() => {})
    }
    this.audioContext = null
  }
}

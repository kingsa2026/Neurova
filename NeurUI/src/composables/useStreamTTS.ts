/**
 * 流式 TTS（补课：LLM 流式实时语音）——句子级流水线。
 *
 * 工作方式：LLM 流式输出的文本增量喂入 feed()，按句末标点切出完整句，
 * 逐句（保序串行）请求 /audio/synthesize-stream 合成并顺序播放；
 * 全部句子的 blob URL 留在 urls 里供下方播放器回放（不重复合成）。
 *
 * 文本过滤（用户要求）：网址、代码块/行内代码、表情不转语音——
 * 过滤后为空的句子直接跳过（不产生音频，不影响其余句子顺序）。
 */
import { ref, type Ref } from 'vue'

/** ── 纯函数：语音文本清洗 ────────────────────────────────── */

/** 表情符号（含 ZWJ 序列/变体选择器） */
const EMOJI_RE = /[\p{Extended_Pictographic}\u{FE0F}\u{200D}\u{1F1E6}-\u{1F1FF}]/gu
/** URL：http(s) 与裸 www */
const URL_RE = /https?:\/\/\S+|www\.\S+/gi
/** 围栏代码块（含语言标注与内容） */
const FENCED_CODE_RE = /```[\s\S]*?```/g
/** 行内代码 */
const INLINE_CODE_RE = /`[^`\n]*`/g
/** markdown 图片 ![alt](url)（先于链接处理） */
const MD_IMAGE_RE = /!\[([^\]]*)\]\(([^)\s]+)[^)]*\)/g
/** markdown 视频常见外链（.mp4/.webm/.mov 结尾的链接） */
const VIDEO_URL_RE = /https?:\/\/\S+\.(?:mp4|webm|mov)(?:\?\S*)?/gi
/** markdown 链接 [text](url) → text */
const MD_LINK_RE = /\[([^\]]*)\]\(([^)]*)\)/g
/** markdown 残留符号 */
const MD_RESIDUE_RE = /[*`#>]+/g

/**
 * 语音预处理（用户要求）：代码/网址/图片/视频不读原文，改为播报提示。
 * - 围栏/行内代码 → "以下是代码"
 * - 网址 → "以下是网址"
 * - 图片 → "以下是图片"（有 alt 描述则附带）
 * - 视频外链 → "以下是视频"
 * 纯表情/markdown 残留仍清洗，不播报。返回空串表示无可读内容。
 */
export function prepareSpeechText(text: string): string {
  if (!text) return ''
  return text
    .replace(FENCED_CODE_RE, ' 以下是代码。 ')
    .replace(INLINE_CODE_RE, ' 以下是代码。 ')
    .replace(MD_IMAGE_RE, (_m, alt: string) => (alt ? ` 以下是图片：${alt}。 ` : ' 以下是图片。 '))
    .replace(VIDEO_URL_RE, ' 以下是视频。 ')
    .replace(MD_LINK_RE, '$1')
    .replace(URL_RE, ' 以下是网址。 ')
    .replace(EMOJI_RE, '')
    .replace(MD_RESIDUE_RE, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

/**
 * 语音清洗（旧契约，仍导出兼容既有测试/调用方）：全部剔除不播报。
 * 新代码请用 prepareSpeechText（内容改播报提示）。
 */
export function sanitizeForSpeech(text: string): string {
  if (!text) return ''
  return text
    .replace(FENCED_CODE_RE, ' ')
    .replace(INLINE_CODE_RE, ' ')
    .replace(MD_LINK_RE, '$1')
    .replace(URL_RE, ' ')
    .replace(EMOJI_RE, '')
    .replace(MD_RESIDUE_RE, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

/**
 * 空音频守卫：0 字节 blob 交给 <audio> 加载时 Chromium 会发
 * `Range: bytes=0-` 请求 → 416（ERR_REQUEST_RANGE_NOT_SATISFIABLE）。
 * 后端全链路失败时端点可能返回 200+空 body，这里绝对拒绝造 blob URL。
 */
export function requireNonEmptyAudioBlob(blob: Blob): Blob {
  if (!blob || blob.size === 0) {
    throw new Error('TTS 返回空音频（0 字节），已拒绝创建 blob URL')
  }
  return blob
}

/**
 * 播放器回放源选取：带句块列表时逐句取（ttsIdx 推进），
 * 否则回落单段 audioUrl。越界回落首块，避免 <audio> 拿空 src。
 */
export function audioSourceFor(msg: {
  audioUrl?: string | null
  ttsUrls?: string[] | null
  ttsIdx?: number | null
}): string {
  if (msg.ttsUrls && msg.ttsUrls.length) {
    return msg.ttsUrls[msg.ttsIdx ?? 0] ?? msg.ttsUrls[0]
  }
  return msg.audioUrl ?? ''
}

/** ── 工具调用语音提示 ────────────────────────────────────── */

/** 工具名 → 播报语（命令/终端类工具说"执行命令"，其余说"使用工具"） */
const COMMAND_TOOL_RE = /shell|terminal|command|exec|cmd|python|run_code|bash/i

export function toolAnnouncementText(toolName: string): string {
  return COMMAND_TOOL_RE.test(toolName) ? '正在执行命令，请稍等' : '正在使用工具，请稍等'
}

/** 单句提示音量级（防同轮多工具提示刷屏：同句 8s 内不重播） */
const ANNOUNCE_COOLDOWN_MS = 8000

export interface SpeechAnnouncer {
  announce: (text: string) => void
  dispose: () => void
}

/**
 * 独立语音提示合声器：与正文 TTS 分轨（不走 live 播放器队列），
 * 用一次性 synthesize-stream 请求 + 独立 Audio 播报。
 * 自动语音开启时由宿主创建；仅网络引擎可用（fetch 失败静默跳过）。
 */
export function createSpeechAnnouncer(
  synthesize: (text: string) => Promise<Blob>,
  opts: { enabled: () => boolean } = { enabled: () => true },
): SpeechAnnouncer {
  let lastAt = 0
  let lastText = ''
  let current: HTMLAudioElement | null = null

  return {
    announce(text: string): void {
      if (!opts.enabled() || !text) return
      const now = Date.now()
      // 同文本冷却（连续多个工具调用不逐个重播提示）
      if (text === lastText && now - lastAt < ANNOUNCE_COOLDOWN_MS) return
      lastAt = now
      lastText = text
      void (async () => {
        try {
          const blob = await synthesize(text)
          if (!blob || blob.size === 0) return
          // 台账 N6（2026-09-11）：被打断的上一条播报 pause 后 onended 永不
          // 触发——先显式停掉并回收其 object URL，否则每次打断泄漏一个 blob。
          if (current) {
            current.pause()
            if (current.src) URL.revokeObjectURL(current.src)
          }
          const audio = new Audio(URL.createObjectURL(blob))
          current = audio
          audio.onended = () => {
            URL.revokeObjectURL(audio.src)
            if (current === audio) current = null
          }
          audio.play().catch(() => {})
        } catch {
          // 提示播报失败静默跳过（不干扰正文）
        }
      })()
    },
    dispose(): void {
      if (current) {
        current.pause()
        if (current.src) URL.revokeObjectURL(current.src)
      }
      current = null
    },
  }
}

/** ── 纯函数：流式句子切分 ────────────────────────────────── */

const SENTENCE_END_RE = /([。！？!?；;…]+["'”’）)]*\s*|\n+)/

/** 短句滞留阈值：小于该长度的句末段与后续合并（避免碎请求）。 */
const MIN_SENTENCE_CHARS = 12

/**
 * 从流式缓冲提取完整句子。
 *
 * @param buffer 累积文本
 * @param force true=流结束，剩余全部输出（不再滞留）
 * @returns complete=可直接合成的句子；rest=滞留缓冲
 */
export function extractSentences(
  buffer: string,
  force = false,
): { complete: string[]; rest: string } {
  const parts = buffer.split(SENTENCE_END_RE)
  // split 带捕获组：[文本, 分隔符, 文本, 分隔符, ...]
  const complete: string[] = []
  let pending = ''
  for (let i = 0; i < parts.length; i += 2) {
    const seg = parts[i] ?? ''
    const delim = parts[i + 1] ?? ''
    pending += seg
    if (delim) {
      pending += delim
      // 句子足够长才放行；太短滞留给下一句合并
      if (sanitizeForSpeech(pending).length >= MIN_SENTENCE_CHARS) {
        complete.push(pending)
        pending = ''
      }
    }
  }
  if (force && pending.trim()) {
    complete.push(pending)
    pending = ''
  }
  return { complete: complete.map((s) => s.trim()).filter(Boolean), rest: pending }
}

/** ── 会话编排 ────────────────────────────────────────────── */

export interface StreamTTSHooks {
  /** 合成请求（注入 base URL/token 与音频元素创建），返回 blob URL；失败抛错 */
  synthesize: (text: string, signal: AbortSignal) => Promise<string>
  /** 顺序播放回调：由宿主驱动音频元素（live 播放） */
  onChunkReady: (url: string, index: number) => void
  /** 全部句子处理完毕（urls 定稿，回放可用） */
  onDone: (urls: string[]) => void
}

export class StreamTTSRunner {
  readonly urls: Ref<string[]> = ref([])
  private buffer = ''
  private chain: Promise<void> = Promise.resolve()
  private controller: AbortController | null = null
  private finished = false

  constructor(private readonly hooks: StreamTTSHooks) {}

  get isFinished(): boolean {
    return this.finished
  }

  /** 流开始/重置。 */
  begin(): void {
    this.abort()
    this.buffer = ''
    this.urls.value = []
    this.finished = false
    this.controller = new AbortController()
    this.chain = Promise.resolve()
  }

  /** 喂入 LLM 增量文本；切出的完整句进入合成链（保序串行）。 */
  feed(delta: string): void {
    if (this.finished || !delta) return
    this.buffer += delta
    const { complete, rest } = extractSentences(this.buffer)
    if (complete.length === 0) return
    // 消费边界直接用切分函数返回的滞留段 rest（相对原 buffer 精确对齐）。
    // 不得用 trim 后的 complete 拼接反查 indexOf：句间换行等空白会让
    // 拼接串与原 buffer 失配（indexOf=-1），旧实现此时整段清空 buffer，
    // 未分句的尾部文本被静默丢弃。
    this.buffer = rest
    for (const sentence of complete) {
      const text = prepareSpeechText(sentence)
      if (!text) continue // 纯表情/markdown 残留 → 不读
      this.enqueue(text)
    }
  }

  /** 流结束：滞留段强制出句，链完成后回调 onDone。 */
  end(): void {
    if (this.finished) return
    const { complete } = extractSentences(this.buffer, true)
    this.buffer = ''
    for (const sentence of complete) {
      const text = prepareSpeechText(sentence)
      if (!text) continue
      this.enqueue(text)
    }
    this.finished = true
    void this.chain.then(() => {
      this.hooks.onDone([...this.urls.value])
    })
  }

  /** 中止：断掉在途请求与合成链（已合成的 url 保留可回放）。 */
  abort(): void {
    this.finished = true
    this.controller?.abort()
    this.controller = null
  }

  private enqueue(text: string): void {
    const controller = this.controller
    if (!controller) return
    const signal = controller.signal
    this.chain = this.chain.then(async () => {
      if (signal.aborted) return
      try {
        const url = await this.hooks.synthesize(text, signal)
        if (signal.aborted) return
        this.urls.value = [...this.urls.value, url]
        this.hooks.onChunkReady(url, this.urls.value.length - 1)
      } catch (e) {
        if ((e as Error)?.name !== 'AbortError') {
          // 单句合成失败不拖垮后续句子（跳过该句）
        }
      }
    })
  }
}

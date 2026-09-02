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
/** markdown 链接 [text](url) → text */
const MD_LINK_RE = /\[([^\]]*)\]\(([^)]*)\)/g
/** markdown 残留符号 */
const MD_RESIDUE_RE = /[*`#>]+/g

/** 语音清洗：网址/代码/表情/markdown 残留全部剔除，收敛空白。 */
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
    const { complete } = extractSentences(this.buffer)
    if (complete.length === 0) return
    // 消费掉完整句（保留滞留段）
    const consumed = complete.join('')
    const idx = this.buffer.indexOf(consumed)
    this.buffer = idx >= 0 ? this.buffer.slice(idx + consumed.length) : ''
    for (const sentence of complete) {
      const text = sanitizeForSpeech(sentence)
      if (!text) continue // 纯网址/代码/表情 → 不读
      this.enqueue(text)
    }
  }

  /** 流结束：滞留段强制出句，链完成后回调 onDone。 */
  end(): void {
    if (this.finished) return
    const { complete } = extractSentences(this.buffer, true)
    this.buffer = ''
    for (const sentence of complete) {
      const text = sanitizeForSpeech(sentence)
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

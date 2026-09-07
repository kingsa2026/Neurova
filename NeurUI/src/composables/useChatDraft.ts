/**
 * 会话草稿持久化（补课 D：对齐 QP chatInputDraft 语义）。
 *
 * 按会话隔离存 localStorage：切换会话时保存旧会话草稿、恢复新会话草稿。
 * 存储上限 50 个会话（LRU 简化：超限删最旧 key）；单草稿上限 10k 字符。
 */
const KEY_PREFIX = 'nr_chat_draft:'
const MAX_DRAFTS = 50
const MAX_DRAFT_LEN = 10_000

function readAll(): Record<string, string> {
  try {
    const raw = localStorage.getItem(KEY_PREFIX + '_index')
    return raw ? (JSON.parse(raw) as Record<string, string>) : {}
  } catch {
    return {}
  }
}

function writeAll(all: Record<string, string>): void {
  // LRU：超限按 ts 删真正最旧（BUG-12：原按 key 字典序，key 是纯 sessionId）
  const keys = Object.keys(all)
  if (keys.length > MAX_DRAFTS) {
    const tsOf = (k: string): number => {
      try {
        const p = JSON.parse(all[k])
        return typeof p?.ts === 'number' ? p.ts : 0
      } catch {
        return 0 // 旧格式视为最旧
      }
    }
    keys.sort((a, b) => tsOf(a) - tsOf(b))
    for (const k of keys.slice(0, keys.length - MAX_DRAFTS)) delete all[k]
  }
  try {
    localStorage.setItem(KEY_PREFIX + '_index', JSON.stringify(all))
  } catch {
    // 存储满/隐私模式：草稿功能静默降级
  }
}

export function useChatDraft() {
  /** 保存会话草稿（空串=清除该会话草稿）。
   *  BUG-12 修复：value 记 {text, ts}，writeAll 按 ts 淘汰真正最旧
   *  （原实现按 sessionId 字典序淘汰，"最久未用"语义失效）。 */
  function save(sessionId: string, text: string): void {
    if (!sessionId) return
    const all = readAll()
    const t = (text || '').slice(0, MAX_DRAFT_LEN)
    if (t) all[sessionId] = JSON.stringify({ text: t, ts: Date.now() })
    else delete all[sessionId]
    writeAll(all)
  }

  /** 恢复会话草稿（无草稿返回空串；兼容旧纯文本格式）。 */
  function restore(sessionId: string): string {
    if (!sessionId) return ''
    const raw = readAll()[sessionId]
    if (!raw) return ''
    try {
      const parsed = JSON.parse(raw)
      if (typeof parsed === 'object' && parsed !== null && 'text' in parsed) {
        return String(parsed.text ?? '')
      }
    } catch { /* 旧格式纯文本 */ }
    return raw
  }

  return { save, restore }
}

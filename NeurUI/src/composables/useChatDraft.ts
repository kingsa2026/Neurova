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
  // LRU：超限按 key 排序删最旧（key 含时间戳前缀）
  const keys = Object.keys(all)
  if (keys.length > MAX_DRAFTS) {
    keys.sort()
    for (const k of keys.slice(0, keys.length - MAX_DRAFTS)) delete all[k]
  }
  try {
    localStorage.setItem(KEY_PREFIX + '_index', JSON.stringify(all))
  } catch {
    // 存储满/隐私模式：草稿功能静默降级
  }
}

export function useChatDraft() {
  /** 保存会话草稿（空串=清除该会话草稿）。 */
  function save(sessionId: string, text: string): void {
    if (!sessionId) return
    const all = readAll()
    const t = (text || '').slice(0, MAX_DRAFT_LEN)
    if (t) all[sessionId] = t
    else delete all[sessionId]
    writeAll(all)
  }

  /** 恢复会话草稿（无草稿返回空串）。 */
  function restore(sessionId: string): string {
    if (!sessionId) return ''
    return readAll()[sessionId] ?? ''
  }

  return { save, restore }
}

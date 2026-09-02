/**
 * 输入历史回溯（补课 C：对齐 QP useMessageHistoryNavigation 的轻量版）。
 *
 * 语义：
 * - record(text)：发送时记录（去重连续重复，上限 100 条）
 * - up(current)：仅当输入框为空时开始回溯（不覆盖正在打的字）；
 *   回溯中继续 up 向更旧移动，到最旧停住
 * - down(current)：回溯中向更新移动；越过最新 → 返回 live 草稿（''）
 * - 返回 null 表示不处理（调用方不改动输入框）
 */
export function useInputHistory(maxItems = 100) {
  const history: string[] = []
  let idx = -1 // -1 = 未在回溯（live 输入）

  function record(text: string): void {
    const t = (text || '').trim()
    if (!t) return
    if (history[history.length - 1] === t) return
    history.push(t)
    if (history.length > maxItems) history.shift()
    idx = -1
  }

  function up(current: string): string | null {
    if (history.length === 0) return null
    if (idx === -1) {
      if (current.trim()) return null // 正在打字不覆盖
      idx = history.length - 1
      return history[idx]
    }
    if (idx > 0) {
      idx -= 1
      return history[idx]
    }
    return history[idx] // 已到最旧，停住
  }

  function down(current: string): string | null {
    if (idx === -1) return null
    if (idx < history.length - 1) {
      idx += 1
      return history[idx]
    }
    // 越过最新 → 回到 live 输入（我们从空输入开始回溯，live 草稿即空）
    idx = -1
    return current
  }

  function size(): number {
    return history.length
  }

  return { record, up, down, size }
}

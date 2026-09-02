/**
 * 会话内消息搜索（补课 B：对齐 QP ChatSearchPanel 的匹配计算）。
 * 纯函数：返回命中消息的下标列表（大小写不敏感子串匹配）。
 */
export interface SearchableMessage {
  content?: string
  reasoning?: string
}

export function findMessageMatches(
  messages: SearchableMessage[],
  query: string,
): number[] {
  const q = (query || '').trim().toLowerCase()
  if (!q) return []
  const hits: number[] = []
  messages.forEach((m, idx) => {
    const content = (m.content || '').toLowerCase()
    const reasoning = (m.reasoning || '').toLowerCase()
    if (content.includes(q) || reasoning.includes(q)) hits.push(idx)
  })
  return hits
}

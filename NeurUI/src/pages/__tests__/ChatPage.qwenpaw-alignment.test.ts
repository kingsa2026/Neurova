/**
 * 聊天页对齐 QwenPaw — store 契约测试
 *
 * 锁定：
 * 1. applyTurnUsage：lastTurnUsage 更新 + per-session 累计 + 空 session 忽略累计；
 * 2. getSessionTokenUsage：无记录返回 null；
 * 3. applySessionOrder：按给定 id 序重排，未知 id 垫底不丢；
 * 4. KaTeX 数学公式渲染（markdown.ts）：$$..$$ / $..$ / \(..\) / \[..\] 四形态
 *   渲染为 katex span；代码段内 $ 不误判；未闭合半截不炸。
 */
import { describe, expect, it, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useChatStore } from '@/stores/chat'
import { renderMarkdown } from '@/utils/markdown'

describe('chat store — token 用量与会话排序', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('applyTurnUsage 累计到指定会话并更新 lastTurnUsage', () => {
    const store = useChatStore()
    store.applyTurnUsage('s1', { prompt: 100, completion: 20, total: 120, estimated: false })
    store.applyTurnUsage('s1', { prompt: 50, completion: 30, total: 80, estimated: true })

    expect(store.getSessionTokenUsage('s1')).toEqual({ prompt: 150, completion: 50, total: 200 })
    expect(store.lastTurnUsage).toEqual({ prompt: 50, completion: 30, total: 80, estimated: true })
  })

  it('空 sessionId 只更新 lastTurnUsage 不累计', () => {
    const store = useChatStore()
    store.applyTurnUsage(null, { prompt: 10, completion: 5, total: 15, estimated: false })
    expect(store.lastTurnUsage?.total).toBe(15)
    expect(store.getSessionTokenUsage(null)).toBeNull()
  })

  it('getSessionTokenUsage 无记录返回 null', () => {
    const store = useChatStore()
    expect(store.getSessionTokenUsage('ghost')).toBeNull()
  })

  it('applySessionOrder 按给定顺序重排且不丢会话', () => {
    const store = useChatStore()
    store.setSessions([
      { id: 'a', title: 'A' } as any,
      { id: 'b', title: 'B' } as any,
      { id: 'c', title: 'C' } as any,
    ])
    store.applySessionOrder(['c', 'a', 'b'])
    expect(store.sessions.map((s) => s.id)).toEqual(['c', 'a', 'b'])
  })

  it('applySessionOrder 未知 id 垫底且原顺序保留', () => {
    const store = useChatStore()
    store.setSessions([
      { id: 'a', title: 'A' } as any,
      { id: 'b', title: 'B' } as any,
      { id: 'x', title: 'X' } as any,
    ])
    store.applySessionOrder(['b'])
    // b 按给定序在前；a/x 不在列表 → 垫底（原相对顺序保持）
    expect(store.sessions.map((s) => s.id)).toEqual(['b', 'a', 'x'])
  })
})

describe('KaTeX 数学公式渲染（QwenPaw 对齐）', () => {
  it('$$..$$ display 公式渲染为 katex HTML', () => {
    const html = renderMarkdown('质能方程：$$E = mc^2$$')
    expect(html).toContain('katex')
    expect(html).toContain('E')
  })

  it('$..$ inline 公式渲染', () => {
    const html = renderMarkdown('半径 $r = 5$ 时')
    expect(html).toContain('katex')
  })

  it('\\(..\\) 与 \\[..\\] 形态渲染', () => {
    const html1 = renderMarkdown('值 \\(a + b\\) 合计')
    expect(html1).toContain('katex')
    const html2 = renderMarkdown('\\[x^2 + y^2 = z^2\\]')
    expect(html2).toContain('katex')
  })

  it('代码段内的美元符号不误判为公式', () => {
    const html = renderMarkdown('价格是 `100$ 至 200$` 之间')
    expect(html).not.toContain('katex-display')
    expect(html).toContain('100$ 至 200$')
  })

  it('未闭合的 $$ 流式半截不炸不渲染', () => {
    const html = renderMarkdown('公式开始 $$E = mc')
    expect(html).toContain('$$')
    expect(html).not.toContain('katex')
  })

  it('普通文本与代码块渲染不受影响', () => {
    const html = renderMarkdown('# 标题\n\n```js\nconst a = 1;\n```\n\n正文 **加粗**')
    expect(html).toContain('<h1>')
    expect(html).toContain('nr-code-wrap')
    expect(html).toContain('<strong>')
  })
})

import { beforeEach, describe, expect, it } from 'vitest'
import { useChatDraft } from '@/composables/useChatDraft'

describe('useChatDraft', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('save + restore roundtrip per session', () => {
    const d = useChatDraft()
    d.save('s1', 'draft for s1')
    d.save('s2', 'draft for s2')
    expect(d.restore('s1')).toBe('draft for s1')
    expect(d.restore('s2')).toBe('draft for s2')
    expect(d.restore('s3')).toBe('')
  })

  it('empty text clears draft', () => {
    const d = useChatDraft()
    d.save('s1', 'x')
    d.save('s1', '')
    expect(d.restore('s1')).toBe('')
  })

  it('truncates overly long drafts', () => {
    const d = useChatDraft()
    d.save('s1', 'x'.repeat(20_000))
    expect(d.restore('s1').length).toBe(10_000)
  })

  it('evicts oldest beyond 50 sessions', () => {
    const d = useChatDraft()
    for (let i = 0; i < 55; i++) d.save(`s${i}`, `draft-${i}`)
    expect(d.restore('s0')).toBe('') // 最旧被淘汰
    expect(d.restore('s54')).toBe('draft-54')
  })
})

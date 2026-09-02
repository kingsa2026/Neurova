import { describe, expect, it } from 'vitest'
import { useInputHistory } from '@/composables/useInputHistory'

describe('useInputHistory', () => {
  it('up from empty input returns newest, down past newest returns live draft', () => {
    const h = useInputHistory()
    h.record('first')
    h.record('second')
    expect(h.up('')).toBe('second')
    expect(h.up('')).toBe('first')
    expect(h.up('')).toBe('first') // 最旧停住
    expect(h.down('')).toBe('second')
    expect(h.down('')).toBe('') // 越过最新回到 live
    expect(h.down('')).toBeNull() // 已不在回溯中
  })

  it('up with non-empty input does not clobber typing', () => {
    const h = useInputHistory()
    h.record('sent')
    expect(h.up('typing...')).toBeNull()
  })

  it('records dedupe consecutive duplicates and cap size', () => {
    const h = useInputHistory(2)
    h.record('a')
    h.record('a')
    expect(h.size()).toBe(1)
    h.record('b')
    h.record('c')
    expect(h.size()).toBe(2)
    expect(h.up('')).toBe('c')
    expect(h.up('')).toBe('b') // a 已被挤出
  })

  it('record resets navigation index', () => {
    const h = useInputHistory()
    h.record('a')
    h.up('')
    h.record('b') // 发送新消息会重置回溯
    expect(h.up('')).toBe('b')
  })
})

import { describe, expect, it } from 'vitest'
import { findMessageMatches } from '@/utils/messageSearch'

const msgs = [
  { content: 'Hello World' },
  { content: 'foo bar', reasoning: 'mentioning hello here' },
  { content: 'nothing relevant' },
  { content: '' },
]

describe('findMessageMatches', () => {
  it('matches content case-insensitively', () => {
    expect(findMessageMatches(msgs, 'hello')).toEqual([0, 1])
  })
  it('matches reasoning too', () => {
    expect(findMessageMatches(msgs, 'mentioning')).toEqual([1])
  })
  it('returns empty for blank query', () => {
    expect(findMessageMatches(msgs, '')).toEqual([])
    expect(findMessageMatches(msgs, '   ')).toEqual([])
  })
  it('returns empty when nothing matches', () => {
    expect(findMessageMatches(msgs, 'zzz')).toEqual([])
  })
})

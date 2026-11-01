import { describe, expect, it } from 'vitest'
import { mergeWaitingHuman } from '../waitingHuman'

const NOW = Date.parse('2026-11-01T12:00:00.000Z')

describe('mergeWaitingHuman', () => {
  it('adds approval count and keeps the oldest wait across both sources', () => {
    const summary = mergeWaitingHuman(
      { count: 2, oldestWaitSeconds: 120 },
      ['2026-11-01T11:55:00.000Z', '2026-11-01T11:58:00.000Z'],
      NOW,
    )
    expect(summary.count).toBe(4)
    expect(summary.oldestWaitSeconds).toBe(300)
  })

  it('keeps the audit source when approvals are absent', () => {
    expect(mergeWaitingHuman({ count: 1, oldestWaitSeconds: 60 }, null, NOW))
      .toEqual({ count: 1, oldestWaitSeconds: 60 })
  })

  it('keeps approvals when the audit source is absent', () => {
    const summary = mergeWaitingHuman(null, ['2026-11-01T11:59:00.000Z'], NOW)
    expect(summary.count).toBe(1)
    expect(summary.oldestWaitSeconds).toBe(60)
  })

  it('ignores unparsable timestamps instead of inventing a wait', () => {
    const summary = mergeWaitingHuman(null, ['not-a-date', undefined, null], NOW)
    expect(summary).toEqual({ count: 0, oldestWaitSeconds: 0 })
  })

  it('never returns a negative wait for clock skew', () => {
    const summary = mergeWaitingHuman(null, ['2026-11-01T12:05:00.000Z'], NOW)
    expect(summary.oldestWaitSeconds).toBe(0)
  })
})

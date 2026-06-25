import { describe, it, expect, beforeEach } from 'vitest'
import { useASRRestartGuard } from '@/composables/useASRRestartGuard'

describe('useASRRestartGuard — FE-002: prevent infinite ASR restart loop', () => {
  let guard: ReturnType<typeof useASRRestartGuard>

  beforeEach(() => {
    guard = useASRRestartGuard(3) // max 3 restarts
  })

  it('allows restart when count is below limit', () => {
    expect(guard.canRestart()).toBe(true)
    expect(guard.limitReached.value).toBe(false)
  })

  it('records restarts and blocks after reaching the limit', () => {
    guard.recordRestart() // count = 1
    expect(guard.canRestart()).toBe(true)

    guard.recordRestart() // count = 2
    expect(guard.canRestart()).toBe(true)

    guard.recordRestart() // count = 3 → limit reached
    expect(guard.canRestart()).toBe(false)
    expect(guard.limitReached.value).toBe(true)
  })

  it('reset clears the count and re-enables restarts', () => {
    guard.recordRestart()
    guard.recordRestart()
    guard.recordRestart()
    expect(guard.canRestart()).toBe(false)

    guard.reset()
    expect(guard.restartCount.value).toBe(0)
    expect(guard.limitReached.value).toBe(false)
    expect(guard.canRestart()).toBe(true)
  })

  it('does not allow restart once limit reached even after extra recordRestart calls', () => {
    guard.recordRestart()
    guard.recordRestart()
    guard.recordRestart()
    // Extra calls should not revive restart capability without a reset
    guard.recordRestart()
    expect(guard.canRestart()).toBe(false)
    expect(guard.limitReached.value).toBe(true)
  })
})

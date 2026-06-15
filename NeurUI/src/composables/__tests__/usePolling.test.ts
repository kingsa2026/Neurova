import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { usePolling, useDebouncedSearch } from '@/composables/usePolling'

describe('usePolling', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('starts inactive', () => {
    const { active } = usePolling(async () => 'data', 1000)
    expect(active.value).toBe(false)
  })

  it('start activates polling and fetches immediately', async () => {
    const fetcher = vi.fn().mockResolvedValue('result')
    const { active, data, start } = usePolling(fetcher, 1000)

    start()
    expect(active.value).toBe(true)
    await vi.advanceTimersByTimeAsync(0)
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(data.value).toBe('result')
  })

  it('polls at interval', async () => {
    const fetcher = vi.fn().mockResolvedValue('ok')
    const { start } = usePolling(fetcher, 1000)

    start()
    await vi.advanceTimersByTimeAsync(0)
    expect(fetcher).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(1000)
    expect(fetcher).toHaveBeenCalledTimes(2)

    await vi.advanceTimersByTimeAsync(1000)
    expect(fetcher).toHaveBeenCalledTimes(3)
  })

  it('stop halts polling', async () => {
    const fetcher = vi.fn().mockResolvedValue('ok')
    const { active, start, stop } = usePolling(fetcher, 1000)

    start()
    await vi.advanceTimersByTimeAsync(0)
    stop()
    expect(active.value).toBe(false)

    await vi.advanceTimersByTimeAsync(3000)
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('start is idempotent', async () => {
    const fetcher = vi.fn().mockResolvedValue('ok')
    const { start } = usePolling(fetcher, 1000)

    start()
    start() // second call should be no-op
    await vi.advanceTimersByTimeAsync(0)
    expect(fetcher).toHaveBeenCalledTimes(1)
  })
})

describe('useDebouncedSearch', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('starts with empty query', () => {
    const { query, results } = useDebouncedSearch(async () => [])
    expect(query.value).toBe('')
    expect(results.value).toBe(null)
  })

  it('search sets query and triggers after debounce', async () => {
    const searcher = vi.fn().mockResolvedValue(['result1'])
    const { query, search } = useDebouncedSearch(searcher, 300)

    search('test')
    expect(query.value).toBe('test')
    expect(searcher).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(300)
    expect(searcher).toHaveBeenCalledWith('test')
  })

  it('clear resets state', async () => {
    const { query, results, search, clear } = useDebouncedSearch(async () => [], 300)

    search('test')
    clear()
    expect(query.value).toBe('')
    expect(results.value).toBe(null)
  })

  it('empty query clears results immediately', () => {
    const { results, search } = useDebouncedSearch(async () => [], 300)
    search('test')
    search('')
    expect(results.value).toBe(null)
  })

  it('new search cancels previous', async () => {
    const searcher = vi.fn()
      .mockResolvedValueOnce(['first'])
      .mockResolvedValueOnce(['second'])
    const { search } = useDebouncedSearch(searcher, 300)

    search('first')
    await vi.advanceTimersByTimeAsync(150)
    search('second')
    await vi.advanceTimersByTimeAsync(300)

    expect(searcher).toHaveBeenCalledTimes(1)
    expect(searcher).toHaveBeenCalledWith('second')
  })
})

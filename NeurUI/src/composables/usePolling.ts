import { ref, onMounted, onUnmounted } from 'vue'

/**
 * Composable for polling an API endpoint at a regular interval.
 *
 * Usage:
 * ```ts
 * const { data, active, start, stop } = usePolling(
 *   () => getHealthStatus(),
 *   30000 // poll every 30s
 * )
 * start()
 * ```
 */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs = 30000,
) {
  const data = ref<T | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const active = ref(false)

  let timer: ReturnType<typeof setInterval> | null = null

  async function poll() {
    loading.value = true
    error.value = null
    try {
      data.value = await fetcher()
    } catch (e: any) {
      error.value = e?.message || 'Polling error'
    } finally {
      loading.value = false
    }
  }

  function start() {
    if (active.value) return
    active.value = true
    poll() // immediate first call
    timer = setInterval(poll, intervalMs)
  }

  function stop() {
    active.value = false
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  // Auto-cleanup on unmount
  onUnmounted(() => stop())

  return { data, loading, error, active, start, stop, poll }
}

/**
 * Composable for debounced search.
 *
 * Usage:
 * ```ts
 * const { query, results, loading, search } = useDebouncedSearch(
 *   (q) => searchKnowledge(q),
 *   300
 * )
 * ```
 */
export function useDebouncedSearch<T>(
  searcher: (query: string) => Promise<T>,
  debounceMs = 300,
) {
  const query = ref('')
  const results = ref<T | null>(null)
  const loading = ref(false)

  let debounceTimer: ReturnType<typeof setTimeout> | null = null

  function search(q: string) {
    query.value = q
    if (debounceTimer) clearTimeout(debounceTimer)
    if (!q.trim()) {
      results.value = null
      return
    }
    debounceTimer = setTimeout(async () => {
      loading.value = true
      try {
        results.value = await searcher(q)
      } catch {
        results.value = null
      } finally {
        loading.value = false
      }
    }, debounceMs)
  }

  function clear() {
    query.value = ''
    results.value = null
    if (debounceTimer) clearTimeout(debounceTimer)
  }

  onUnmounted(() => {
    if (debounceTimer) clearTimeout(debounceTimer)
  })

  return { query, results, loading, search, clear }
}

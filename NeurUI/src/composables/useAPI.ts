import { ref, type Ref } from 'vue'
import type { ApiResponse, PaginatedData } from '@/types/response'

/**
 * Generic composable for API calls with loading, error, and data states.
 *
 * Usage:
 * ```ts
 * const { data, loading, error, execute } = useAPI(() => getAgents())
 * await execute()
 * ```
 */
export function useAPI<T>(apiCall: () => Promise<ApiResponse<T>>) {
  const data = ref<T | null>(null) as Ref<T | null>
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function execute(): Promise<T | null> {
    loading.value = true
    error.value = null
    try {
      const res = await apiCall()
      data.value = res.data
      return res.data
    } catch (e: any) {
      const msg = e?.response?.data?.message || e?.message || 'Unknown error'
      error.value = msg
      console.error('[useAPI]', msg)
      return null
    } finally {
      loading.value = false
    }
  }

  return { data, loading, error, execute }
}

/**
 * Composable for paginated API calls.
 *
 * Usage:
 * ```ts
 * const { items, total, page, size, loading, fetchPage, nextPage, prevPage } = usePagination(
 *   (params) => getAgents(params)
 * )
 * await fetchPage()
 * ```
 */
export function usePagination<T>(
  apiCall: (params: { page: number; size: number }) => Promise<ApiResponse<PaginatedData<T>>>,
  defaultSize = 20,
) {
  const items = ref<T[]>([]) as Ref<T[]>
  const total = ref(0)
  const page = ref(1)
  const size = ref(defaultSize)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const totalPages = ref(0)

  async function fetchPage(p?: number, s?: number): Promise<void> {
    if (p !== undefined) page.value = p
    if (s !== undefined) size.value = s
    loading.value = true
    error.value = null
    try {
      const res = await apiCall({ page: page.value, size: size.value })
      const d = res.data
      items.value = d.items
      total.value = d.total
      totalPages.value = d.pages || Math.ceil(d.total / size.value)
    } catch (e: any) {
      error.value = e?.response?.data?.message || e?.message || 'Unknown error'
    } finally {
      loading.value = false
    }
  }

  function nextPage(): void {
    if (page.value < totalPages.value) {
      fetchPage(page.value + 1)
    }
  }

  function prevPage(): void {
    if (page.value > 1) {
      fetchPage(page.value - 1)
    }
  }

  function goToPage(p: number): void {
    if (p >= 1 && p <= totalPages.value) {
      fetchPage(p)
    }
  }

  return {
    items,
    total,
    page,
    size,
    totalPages,
    loading,
    error,
    fetchPage,
    nextPage,
    prevPage,
    goToPage,
  }
}

/**
 * Composable for mutation-style API calls (create, update, delete).
 *
 * Usage:
 * ```ts
 * const { loading, error, execute } = useMutation((data) => createAgent(data))
 * await execute({ name: 'Test' })
 * ```
 */
export function useMutation<TInput, TOutput>(
  apiCall: (input: TInput) => Promise<ApiResponse<TOutput>>,
) {
  const loading = ref(false)
  const error = ref<string | null>(null)
  const result = ref<TOutput | null>(null) as Ref<TOutput | null>

  async function execute(input: TInput): Promise<TOutput | null> {
    loading.value = true
    error.value = null
    try {
      const res = await apiCall(input)
      result.value = res.data
      return res.data
    } catch (e: any) {
      error.value = e?.response?.data?.message || e?.message || 'Unknown error'
      return null
    } finally {
      loading.value = false
    }
  }

  return { loading, error, result, execute }
}

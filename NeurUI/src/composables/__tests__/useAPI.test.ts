import { describe, it, expect, vi } from 'vitest'
import { useAPI, usePagination, useMutation } from '@/composables/useAPI'
import type { ApiResponse, PaginatedData } from '@/types/response'

/** 构造完整的后端响应信封（mock 辅助） */
function ok<T>(data: T): ApiResponse<T> {
  return { code: 0, message: 'ok', data }
}

function paginated<T>(items: T[], total: number, pages: number, page = 1, size = items.length): ApiResponse<PaginatedData<T>> {
  return ok({ items, total, pages, page, size })
}

describe('useAPI', () => {
  it('starts with null data and no loading', () => {
    const { data, loading, error } = useAPI(async () => ok('test'))
    expect(data.value).toBe(null)
    expect(loading.value).toBe(false)
    expect(error.value).toBe(null)
  })

  it('execute returns data on success', async () => {
    const { data, execute } = useAPI(async () => ok('hello'))
    const result = await execute()
    expect(result).toBe('hello')
    expect(data.value).toBe('hello')
  })

  it('execute sets error on failure', async () => {
    const { error, execute } = useAPI(async () => { throw new Error('fail') })
    const result = await execute()
    expect(result).toBe(null)
    expect(error.value).toBe('fail')
  })

  it('execute sets loading during call', async () => {
    const { loading, execute } = useAPI(async () => {
      expect(loading.value).toBe(true)
      return ok('ok')
    })
    await execute()
    expect(loading.value).toBe(false)
  })
})

describe('usePagination', () => {
  it('starts with empty items', () => {
    const { items, total, page } = usePagination(async () => paginated([], 0, 0))
    expect(items.value).toEqual([])
    expect(total.value).toBe(0)
    expect(page.value).toBe(1)
  })

  it('fetchPage loads items', async () => {
    const { items, total, fetchPage } = usePagination(async () => paginated([{ id: 1 }, { id: 2 }], 2, 1))
    await fetchPage()
    expect(items.value).toHaveLength(2)
    expect(total.value).toBe(2)
  })

  it('nextPage increments page', async () => {
    const apiCall = vi.fn()
      .mockResolvedValueOnce(paginated([], 50, 3))
      .mockResolvedValueOnce(paginated([], 50, 3))
    const { page, totalPages, fetchPage, nextPage } = usePagination(apiCall)
    await fetchPage()
    expect(totalPages.value).toBe(3)
    expect(page.value).toBe(1)
    await nextPage()
    expect(page.value).toBe(2)
  })
})

describe('useMutation', () => {
  it('starts with null result', () => {
    const { result, loading } = useMutation(async (input: string) => ok(input))
    expect(result.value).toBe(null)
    expect(loading.value).toBe(false)
  })

  it('execute returns result', async () => {
    const { result, execute } = useMutation(async (input: string) => ok(`created: ${input}`))
    const res = await execute('agent')
    expect(res).toBe('created: agent')
    expect(result.value).toBe('created: agent')
  })

  it('execute sets error on failure', async () => {
    const { error, execute } = useMutation(async () => { throw new Error('bad') })
    const res = await execute('x')
    expect(res).toBe(null)
    expect(error.value).toBe('bad')
  })
})

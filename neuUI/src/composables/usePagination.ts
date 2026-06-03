import { ref, computed, watch } from 'vue'
import type { Ref } from 'vue'
 
export interface PaginationOptions {
  pageSize?: number
  current?: number
  total?: number
}
 
export interface PaginationReturn {
  current: Ref<number>
  pageSize: Ref<number>
  total: Ref<number>
  pageSizeOptions: Ref<number[]>
  showSizeChanger: Ref<boolean>
  showQuickJumper: Ref<boolean>
  onChange: (page: number, size: number) => void
  onShowSizeChange: (current: number, size: number) => void
  reset: () => void
}
 
export function usePagination(options?: PaginationOptions): PaginationReturn {
  const current = ref<number>(options?.current || 1)
  const pageSize = ref<number>(options?.pageSize || 10)
  const total = ref<number>(options?.total || 0)
  const pageSizeOptions = ref<number[]>([10, 20, 50, 100])
  const showSizeChanger = ref<boolean>(true)
  const showQuickJumper = ref<boolean>(true)
 
  const totalPages = computed<number>(() => {
    return Math.ceil(total.value / pageSize.value)
  })
 
  function onChange(page: number, size: number): void {
    current.value = page
    pageSize.value = size
  }
 
  function onShowSizeChange(_current: number, size: number): void {
    pageSize.value = size
    // 重置到第一页
    current.value = 1
  }
 
  function reset(): void {
    current.value = 1
    pageSize.value = options?.pageSize || 10
    total.value = options?.total || 0
  }
 
  return {
    current,
    pageSize,
    total,
    pageSizeOptions,
    showSizeChanger,
    showQuickJumper,
    onChange,
    onShowSizeChange,
    reset
  }
}
 
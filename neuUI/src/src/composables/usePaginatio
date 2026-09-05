import { ref, computed, watch } from 'vue'
import type { Ref } from 'vue'
&nbsp;
export interface PaginationOptions {
  pageSize?: number
  current?: number
  total?: number
}
&nbsp;
export interface PaginationReturn {
  current: Ref&lt;number&gt;
  pageSize: Ref&lt;number&gt;
  total: Ref&lt;number&gt;
  pageSizeOptions: Ref&lt;number[]&gt;
  showSizeChanger: Ref&lt;boolean&gt;
  showQuickJumper: Ref&lt;boolean&gt;
  onChange: (page: number, size: number) =&gt; void
  onShowSizeChange: (current: number, size: number) =&gt; void
  reset: () =&gt; void
}
&nbsp;
export function usePagination(options?: PaginationOptions): PaginationReturn {
  const current = ref&lt;number&gt;(options?.current || 1)
  const pageSize = ref&lt;number&gt;(options?.pageSize || 10)
  const total = ref&lt;number&gt;(options?.total || 0)
  const pageSizeOptions = ref&lt;number[]&gt;([10, 20, 50, 100])
  const showSizeChanger = ref&lt;boolean&gt;(true)
  const showQuickJumper = ref&lt;boolean&gt;(true)
&nbsp;
  const totalPages = computed&lt;number&gt;(() =&gt; {
    return Math.ceil(total.value / pageSize.value)
  })
&nbsp;
  function onChange(page: number, size: number): void {
    current.value = page
    pageSize.value = size
  }
&nbsp;
  function onShowSizeChange(_current: number, size: number): void {
    pageSize.value = size
    // 重置到第一页
    current.value = 1
  }
&nbsp;
  function reset(): void {
    current.value = 1
    pageSize.value = options?.pageSize || 10
    total.value = options?.total || 0
  }
&nbsp;
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
&nbsp;
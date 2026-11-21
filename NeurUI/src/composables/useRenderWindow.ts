import { computed, ref, watch, type Ref } from 'vue'

/**
 * 列表渲染窗口（E3 勘察：长列表全量 v-for → DOM 行数有界）。
 *
 * 数据仍整表持有（store / 事件账本），只对「进入 DOM 的行」开窗：
 * - mode='head'：从头渲染（会话侧栏 / 历史列表，首部为最新）；
 * - mode='tail'：渲染最近 batch 条（事件账本为追加序，尾部为最新）。
 *
 * 超出窗口的条目由调用方折叠为计数入口，点击 loadMore() 按批放量
 * （展开后仍有界）；resetKey 变化（整表重载 / 切换子代理）把窗口归位首屏。
 * LIST_RENDER_BATCH 为全站列表渲染的统一批大小（单一取值，便于容量推算）。
 */
export const LIST_RENDER_BATCH = 50

export interface RenderWindowOptions {
  /** 每批渲染条数（首屏同值） */
  batch: number
  /** head=从头渲染；tail=渲染最近 batch 条。缺省 head */
  mode?: 'head' | 'tail'
  /** 窗口重置信号源：返回值变化即把窗口归位到首屏 */
  resetKey?: () => unknown
}

export interface RenderWindow<T> {
  /** 当前进入 DOM 的条目（head=前 N 条 / tail=最近 N 条） */
  visibleItems: Ref<T[]>
  /** 窗口外条目数（折叠入口的计数） */
  hiddenCount: Ref<number>
  /** 数据总条数 */
  total: Ref<number>
  /** 当前窗口大小（调用方按此预算切自定义结构，如分组列表） */
  visibleCount: Ref<number>
  /** 放量一批（「加载更多 / 查看更早」入口的点击处理） */
  loadMore: () => void
}

export function useRenderWindow<T>(source: Ref<T[]> | (() => T[]), options: RenderWindowOptions): RenderWindow<T> {
  const mode = options.mode ?? 'head'
  const visibleCount = ref(options.batch)
  const items = computed<T[]>(() => (typeof source === 'function' ? source() : source.value))
  const total = computed(() => items.value.length)

  const visibleItems = computed<T[]>(() => {
    if (mode === 'tail') return items.value.slice(Math.max(0, total.value - visibleCount.value))
    return items.value.slice(0, visibleCount.value)
  })

  const hiddenCount = computed(() => Math.max(0, total.value - visibleCount.value))

  function loadMore(): void {
    visibleCount.value += options.batch
  }

  if (options.resetKey) {
    watch(options.resetKey, () => {
      visibleCount.value = options.batch
    })
  }

  return { visibleItems, hiddenCount, total, visibleCount, loadMore }
}

/**
 * 轨迹状态 → 标签配色（单一事实源）。
 *
 * 轨迹列表页与轨迹详情页对同一份后端状态枚举（`trace.py::_derive_status`
 * 的 completed / running / failed，外加 pending）各写一份相同的映射表。
 * 两份一旦分叉，同一状态在两个页面会是两种颜色。
 *
 * 与其它页面的同名 `statusColor` 不是同一契约：AgentListPage 是 Agent 状态
 * （active/sleeping/inactive/error）、AigcHistoryList 是任务状态
 * （submitted/…/succeeded/failed），各自保留。
 */
const TRACE_STATUS_TAG_COLOR: Record<string, string> = {
  completed: 'green',
  running: 'blue',
  failed: 'red',
  pending: 'default',
}

export function traceStatusTagColor(status: string): string {
  return TRACE_STATUS_TAG_COLOR[status] || 'default'
}

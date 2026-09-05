/**
 * 知识图谱 ECharts force 图配置（从 KnowledgeGraphPage 抽出的纯函数，供单测）。
 *
 * 修复两个实测问题（2026-09-05 用户截图反馈）：
 * 1. tooltip 长描述单行溢出容器边界 → confine + 固定宽度 + word-break
 * 2. label `color: 'inherit'` 继承节点色（青色节点=青色文字），深浅两种
 *    主题下辨识性都差 → 按主题取固定高对比色 + textBorderColor 反底描边
 */

export interface ChartTheme {
  isDark: boolean
}

/** 节点分类 → 主色（页面 categoryColorMap 同源，供 label 对比色计算）。 */
const CATEGORY_COLORS: Record<string, string> = {
  default: '#6366f1',
  concept: '#8b5cf6',
  entity: '#06b6d4',
  memory: '#22c55e',
  knowledge: '#f59e0b',
}

export function categoryColor(category: string | undefined): string {
  return CATEGORY_COLORS[category ?? 'default'] ?? CATEGORY_COLORS.default
}

/** tooltip： confined 在容器内、固定最大宽、长描述自动换行。 */
export function buildTooltipOption() {
  return {
    confine: true,
    appendToBody: false,
    renderMode: 'html' as const,
    className: 'kg-graph-tooltip',
    extraCssText:
      'max-width:320px;white-space:normal;word-break:break-word;line-height:1.5;border-radius:8px;overflow:hidden;',
    enterable: false,
    textStyle: { fontSize: 12 },
  }
}

/**
 * 节点 label：按主题给高对比固定色（不随节点色 inherit），
 * textBorder 与文字色反相（描边=底色），任何节点色上都可读。
 */
export function buildNodeLabelOption(theme: ChartTheme) {
  return {
    show: true,
    fontSize: 11,
    color: theme.isDark ? '#e2e8f0' : '#1e293b',
    textBorderColor: theme.isDark ? 'rgba(15,23,42,0.85)' : 'rgba(255,255,255,0.9)',
    textBorderWidth: 2,
  }
}

/** 边 label（hover 时显示 relation）：同主题规则。 */
export function buildEdgeLabelOption(theme: ChartTheme) {
  return {
    show: false,
    fontSize: 10,
    color: theme.isDark ? '#cbd5e1' : '#475569',
    textBorderColor: theme.isDark ? 'rgba(15,23,42,0.85)' : 'rgba(255,255,255,0.9)',
    textBorderWidth: 2,
  }
}

/** tooltip 内嵌 HTML 的文本主题色（className 由 buildTooltipOption 挂出）。 */
export function tooltipTextClass(theme: ChartTheme): string {
  return theme.isDark ? 'kg-tooltip--dark' : 'kg-tooltip--light'
}

const _ENTITY_MAP: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
}

/** tooltip formatter 输出 HTML，节点名/描述来自知识库内容，必须转义。 */
export function escapeHtml(text: unknown): string {
  return String(text ?? '').replace(/[&<>"']/g, (ch) => _ENTITY_MAP[ch])
}

/** 长描述截断（graph_bridge 侧 description 存正文前 200 字，tooltip 内再收一档）。 */
export function truncateText(text: unknown, max = 160): string {
  const s = String(text ?? '').trim()
  return s.length > max ? s.slice(0, max) + '…' : s
}

interface TooltipDatum {
  name?: string
  category?: string
  description?: string
  source?: string
  target?: string
  relation?: string
}

/** tooltip formatter：节点（转义+截断+换行）/ 边（source→target+relation）。 */
export function buildTooltipFormatter() {
  return (p: { dataType?: string; name?: string; data?: TooltipDatum }): string => {
    const d = p.data ?? {}
    if (p.dataType === 'edge') {
      const relation = d.relation ? ` (${escapeHtml(d.relation)})` : ''
      return `${escapeHtml(d.source)} → ${escapeHtml(d.target)}${relation}`
    }
    const title = escapeHtml(truncateText(p.name ?? d.name, 48))
    const category = d.category ? escapeHtml(d.category) : ''
    const description = d.description
      ? `<div style="margin-top:4px;opacity:.85;">${escapeHtml(truncateText(d.description))}</div>`
      : ''
    const tag = category
      ? `<span style="display:inline-block;margin-top:2px;padding:0 6px;border-radius:4px;font-size:11px;opacity:.9;">${category}</span>`
      : ''
    return `<b>${title}</b>${tag}${description}`
  }
}

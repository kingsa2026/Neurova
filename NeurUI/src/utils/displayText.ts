/**
 * 展示层文案格式化（单一事实源）。
 *
 * 这几支函数此前在 15 个页面里各写一份逐字相同的实现（`formatTime` 9 份、
 * `formatPercent` 3 份、`formatTokens` 2 份、`truncate` 2 份……）。名字相同、
 * 体逐字相同、互不引用 —— 属修复教义第 6 条点名的平行定义：任何一页改了
 * 档位或占位符，其余页面不会跟着改，UI 对同一份数据给出不同文案。
 *
 * 收口口径（只收「体逐字相同」的那一类，同名异体一律不动）：
 *   - 入参量纲不同（epoch 秒 vs ISO 字符串）分开成两支，不合并成开关函数；
 *   - 空值占位不同（`''` / `'-'` / `'N/A'` / `'—'`）不在此模块兜底，
 *     由调用方 `|| 占位符` 表达 —— 收口不得改变任何一处既有显示。
 */

/**
 * ISO 时间串 → 本地时间文案；空值/假值 → 空串。
 * 仅接受后端以 ISO 字符串下发的时间字段（如审核记录 timestamp、
 * 轨迹 started_at）。epoch 秒字段请用 {@link formatEpochSecondText}。
 */
export function formatTimestampText(value?: string | null): string {
  return value ? new Date(value).toLocaleString() : ''
}

/**
 * epoch 秒 → 本地时间文案；空值/假值 → 空串。
 * 仅接受后端以秒级数字下发的时间字段（如项目/画布 updated_at）。
 */
export function formatEpochSecondText(value?: number | null): string {
  return value ? new Date(value * 1000).toLocaleString() : ''
}

/**
 * 0~1 的比例 → 百分比文案；null / undefined → `'-'`。
 * 注意 `0` 是合法比例，必须显示成 `0%` 而不是占位符，故判空只认 null/undefined。
 */
export function formatPercentText(value?: number | null): string {
  return value !== undefined && value !== null ? `${Math.round(value * 100)}%` : '-'
}

/** 大数值 token 计数 → 紧凑文案（1.2M / 1.2K / 原值）。 */
export function formatTokenCount(value: number): string {
  if (value >= 1_000_000) return (value / 1_000_000).toFixed(1) + 'M'
  if (value >= 1_000) return (value / 1_000).toFixed(1) + 'K'
  return String(value)
}

/**
 * 超长文本截断加省略号；`maxLength` 以内原样返回，空值 → 空串。
 * 与「保留尾部」「按词截断」等其它截断口径不同，不要混用。
 */
export function truncateText(text: string, maxLength: number): string {
  return text && text.length > maxLength ? text.slice(0, maxLength) + '...' : text || ''
}

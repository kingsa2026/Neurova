/**
 * 本体语义栈共用格式化工具（UI-0–UI-2）。
 *
 * 收口说明：jsonOrDash / formatConfidence 原本在三个页面各留一份同体定义，
 * 被 duplicate-function-inventory 守卫判为 A 类（同名同体无局部耦合）——
 * 按教义第 7 条收口到此单一属主，调用方只 import。
 */

/** 空容器/空值显示为连字符；其余 JSON 序列化（面向只读详情展示）。 */
export function jsonOrDash(value: unknown): string {
  if (value === null || value === undefined) return '-'
  const text = JSON.stringify(value)
  if (!text || text === '{}' || text === '[]') return '-'
  return text
}

/** 置信度格式化：千分位截断；空值连字符。 */
export function formatConfidence(value: number | null | undefined): string {
  if (value === null || value === undefined) return '-'
  return String(Math.round(value * 1000) / 1000)
}

/** 逗号分隔表单项 → 去空清单（中英文逗号都收；术语声明与企业源列声明共用同一口径）。 */
export function splitList(text: string): string[] {
  return text
    .split(/[,，]/)
    .map((item) => item.trim())
    .filter(Boolean)
}

/** severity 三级 → a-tag 预设色（校验分级闭集，与 §15.4 同一口径）。 */
export function severityColor(severity: string): string {
  if (severity === 'violation') return 'red'
  if (severity === 'warning') return 'gold'
  return 'default'
}

/**
 * 后端拒因（400/409 的 `detail`）取法单点。
 *
 * 两种真实形态都在这收口，不在页面里各写一遍：
 * - 字符串：编译期校验原话（企业源描述符、术语声明未登记的谓词等）；
 * - 对象：`{message, impact}`——`impact` 由 `knowledge_ontology._fullImpact` 组装
 *   （fact_count／typed_subject_count／child_terms／referencing_rules）。
 *
 * 取不到就返回空串与 null，由调用方决定兜底文案；这里不猜、不编计数。
 */
export function ontologyErrorDetail(error: unknown): { message: string; impact: Record<string, unknown> | null } {
  const detail = (error as { response?: { data?: { detail?: unknown } } } | null)?.response?.data?.detail
  if (typeof detail === 'string') return { message: detail.trim(), impact: null }
  if (detail && typeof detail === 'object') {
    const shaped = detail as { message?: unknown; impact?: unknown }
    const message = typeof shaped.message === 'string' ? shaped.message.trim() : ''
    const impact = shaped.impact && typeof shaped.impact === 'object'
      ? (shaped.impact as Record<string, unknown>)
      : null
    return { message, impact }
  }
  return { message: '', impact: null }
}

/** impact 容器字段计数（数组取长度，标量取真值），非数组的脏形状一律记 0。 */
export function impactCount(impact: Record<string, unknown> | null, key: string): number {
  if (!impact) return 0
  const value = impact[key]
  if (Array.isArray(value)) return value.length
  if (typeof value === 'number') return value
  return 0
}

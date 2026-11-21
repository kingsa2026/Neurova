/**
 * 审批裁决「记忆放行」识别（D1 记忆式批准的展示层读数，审批轨迹/协作档案共用）。
 *
 * 后端事实（neurova/agent/approval_chain.py，单源）：
 * - 命中 grant 时 run.approvals 条目写 `decision_source="memory_grant"` + `grant_id`
 *   （projectRunApprovals 投影），同时裁决人记为 `"memory_grant:<grant_id>"`
 *   （GRANT_SOURCE_MARKER 前缀拼装），审计轨迹与项目档案投出的就是这份 decided_by。
 * - 因此展示面按两条证据识别：显式 `decision_source` 字段（新投影带上时直接命中），
 *   或 `decided_by` 的 `memory_grant:` 前缀标记（现行审计面形状）。两者皆无 → null，
 *   调用面不渲染徽标（向后兼容：普通链路裁决/旧数据不受影响）。
 */

/** 与后端 approval_chain.GRANT_SOURCE_MARKER 同词值（唯一出处在那边，此处只作展示识别） */
export const MEMORY_GRANT_SOURCE = 'memory_grant'

export interface MemoryGrantBadge {
  /** 命中的授权单编号（title 提示用；审计面形状下从 decided_by 尾段提取） */
  grantId: string
}

function grantIdFromDecidedBy(decidedBy: string): string {
  const prefix = `${MEMORY_GRANT_SOURCE}:`
  if (!decidedBy.startsWith(prefix)) return ''
  return decidedBy.slice(prefix.length).trim()
}

/**
 * 判定一条审批裁决记录是否记忆式放行。
 * @param record 审批轨迹行 / 项目档案审批行（decision_source/grant_id/decided_by 任一形状）
 */
export function memoryGrantOf(record: Record<string, unknown> | null | undefined): MemoryGrantBadge | null {
  if (!record || typeof record !== 'object') return null
  const source = String(record.decision_source ?? '')
  const decidedBy = String(record.decided_by ?? '')
  if (source === MEMORY_GRANT_SOURCE) {
    const grantId = String(record.grant_id ?? '').trim() || grantIdFromDecidedBy(decidedBy)
    return { grantId }
  }
  const grantId = grantIdFromDecidedBy(decidedBy)
  return grantId ? { grantId } : null
}

/**
 * 徽标 title 文案（审批轨迹/协作档案共用，单一实现）：带授权单编号时提示编号，
 * 否则退回徽标文案。`t` 由调用面注入，util 不依赖 i18n 实例。
 */
export function memoryGrantTitleOf(
  record: Record<string, unknown> | null | undefined,
  t: (key: string, params?: Record<string, unknown>) => string,
): string {
  const grant = memoryGrantOf(record)
  if (!grant) return ''
  return grant.grantId ? t('audit.memoryGrantTitle', { id: grant.grantId }) : t('audit.memoryGrantBadge')
}

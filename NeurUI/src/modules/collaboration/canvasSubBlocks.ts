/**
 * 画布 sub_block 条件可见性（联动下拉）— 纯函数层
 *
 * 契约对齐后端 models.SubBlockConfig.condition: {field, operator, value}：
 * - operator 'eq'（缺省）：config[field] === value 时可见
 * - operator 'neq'：config[field] !== value 时可见
 * - operator 'in'：value 为数组，config[field] 命中任一成员时可见
 *
 * 典型场景：电商节点选择「平台」后联动显示对应平台的 API 参数
 * （亚马逊 → MarketplaceId/SP-API 区域；淘宝 → num_iid 等）。
 * 隐藏字段的值保留在 config 中不清除，执行器行为不受可见性影响。
 */

export interface SubBlockCondition {
  /** 依赖的 config 键，如 'platform' */
  field: string
  operator?: 'eq' | 'neq' | 'in'
  value?: unknown
}

export interface SubBlockLike {
  id: string
  title?: string
  condition?: SubBlockCondition | null
}

/** 数字/字符串宽松比较（slider 数值 vs 字符串条件值） */
function looseEqual(a: unknown, b: unknown): boolean {
  return String(a) === String(b)
}

/**
 * 评估单个 sub_block 的可见性条件。
 * 无条件 / condition 缺少 field 时视为可见（fail-open，避免字段静默消失）。
 */
export function evalSubBlockCondition(
  condition: SubBlockCondition | null | undefined,
  config: Record<string, unknown>,
): boolean {
  if (!condition) return true
  const { field } = condition
  if (!field) return true

  const current = config[field]
  const operator = condition.operator ?? 'eq'

  if (operator === 'in') {
    const list = Array.isArray(condition.value) ? condition.value : [condition.value]
    return current !== undefined && list.some(v => looseEqual(current, v))
  }
  if (operator === 'neq') {
    return current === undefined || !looseEqual(current, condition.value)
  }
  // eq（缺省）
  return current !== undefined && looseEqual(current, condition.value)
}

/** 按 config 现状过滤出可见的 sub_blocks（保持原顺序） */
export function filterVisibleSubBlocks<T extends SubBlockLike>(
  blocks: T[],
  config: Record<string, unknown>,
): T[] {
  return blocks.filter(b => evalSubBlockCondition(b.condition, config))
}

/**
 * 工单 015 · 经验处置 API 客户端 + 记忆类型词表（前端唯一事实源）。
 *
 * 两个断言点：
 * 1. 处置必须打后端 `PUT /experience/{id}/disposition`，恢复用 null 表达
 *    （不是 "none"/"restore" 之类的魔法串——后端 Literal 只认三态加 null）；
 * 2. 记忆类型清单收拢成 `MEMORY_TYPES` 一份（012 登记的欠账：类型值在页签、
 *    新建下拉、色板里各抄了一份，谁都可能漏改）。`workflow_experience` 后端
 *    早已能存能检，界面筛不出来就是因为这三份各自漂移。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/api', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    post: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    put: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    delete: vi.fn().mockResolvedValue({ code: 0, data: {} }),
  },
}))

import api from '@/api'
import { setExperienceDisposition } from '@/api/modules/experience'
import { MEMORY_TYPES, MEMORY_TYPE_BY_TAB, type MemoryTypeValue } from '@/api/modules/memory'
import zhCN from '@/i18n/locales/zh-CN'

const put = api.put as unknown as ReturnType<typeof vi.fn>

describe('setExperienceDisposition', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it.each(['endorsed', 'demoted', 'suppressed'] as const)('PUT %s 打到处置端点', async (state) => {
    await setExperienceDisposition('42', state)
    expect(put).toHaveBeenCalledWith('/experience/42/disposition', { disposition: state })
  })

  it('恢复用 null 表达，不是魔法字符串', async () => {
    await setExperienceDisposition('42', null)
    expect(put).toHaveBeenCalledWith('/experience/42/disposition', { disposition: null })
  })
})

describe('MEMORY_TYPES（类型词表唯一事实源）', () => {
  const values = () => MEMORY_TYPES.map((m) => m.value)

  it('包含后端 MemoryType 枚举的全部取值（012 补的 workflow_experience 在内）', () => {
    expect(values().sort()).toEqual(
      [
        'emotional',
        'episodic',
        'pattern',
        'procedural',
        'semantic',
        'workflow_experience',
        'working',
      ].sort(),
    )
  })

  it('workflow_experience 只登记一次（重复项会让下拉出现两个同名选项）', () => {
    expect(values().filter((v) => v === 'workflow_experience')).toHaveLength(1)
  })

  it.each(MEMORY_TYPES.map((m) => [m.value, m.labelKey] as const))(
    '%s 的标签键在 zh-CN 里存在',
    (_value, labelKey) => {
      const [section, key] = labelKey.split('.')
      expect((zhCN as Record<string, any>)[section]?.[key], `zhCN.${labelKey} 缺失`).toBeTruthy()
    },
  )

  it.each(MEMORY_TYPES.map((m) => [m.value, m.color] as const))('%s 有色板取值', (_value, color) => {
    expect(color).toMatch(/^#[0-9a-f]{6}$/i)
  })

  it('工作流经验可按类型检索（页签映射与长期记忆清单都收得进）', () => {
    expect(MEMORY_TYPE_BY_TAB.workflow_experience).toBe('workflow_experience')
    expect((MEMORY_TYPE_BY_TAB.long_term ?? '').split(',')).toContain('workflow_experience')
  })

  it('词表值可赋给 MemoryTypeValue（类型联合与常量不得两份口径）', () => {
    const one: MemoryTypeValue = 'workflow_experience'
    expect(MEMORY_TYPES.map((m) => m.value)).toContain(one)
  })
})

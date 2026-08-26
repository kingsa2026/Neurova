import { beforeEach, describe, expect, it } from 'vitest'
import {
  useThinkingEffort,
  _resetThinkingEffortForTest,
  THINKING_EFFORTS,
} from '@/composables/useThinkingEffort'

describe('useThinkingEffort', () => {
  beforeEach(() => {
    localStorage.clear()
    _resetThinkingEffortForTest()
  })

  it('提供三档思考程度', () => {
    expect(THINKING_EFFORTS).toEqual(['light', 'standard', 'deep'])
  })

  it('默认 standard', () => {
    const { effort } = useThinkingEffort()
    expect(effort.value).toBe('standard')
  })

  it('setEffort 更新并持久化到 localStorage', () => {
    const { effort, setEffort } = useThinkingEffort()
    setEffort('deep')
    expect(effort.value).toBe('deep')
    expect(localStorage.getItem('neurova.thinkingEffort')).toBe('deep')
  })

  it('重新挂载时从 localStorage 恢复', () => {
    localStorage.setItem('neurova.thinkingEffort', 'light')
    _resetThinkingEffortForTest() // 模拟重新挂载
    const { effort } = useThinkingEffort()
    expect(effort.value).toBe('light')
  })

  it('localStorage 中的非法值回退为 standard', () => {
    localStorage.setItem('neurova.thinkingEffort', 'maximun')
    const { effort } = useThinkingEffort()
    expect(effort.value).toBe('standard')
  })

  it('setEffort 忽略非法档位', () => {
    const { effort, setEffort } = useThinkingEffort()
    // @ts-expect-error 故意传非法值
    setEffort('ultra')
    expect(effort.value).toBe('standard')
  })
})

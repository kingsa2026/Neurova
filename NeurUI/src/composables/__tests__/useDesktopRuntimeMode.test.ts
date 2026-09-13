import { beforeEach, describe, expect, it, vi } from 'vitest'

const getSettings = vi.fn()
const updateSettings = vi.fn()

vi.mock('@/api/modules/settings', () => ({
  getSettings: (...args: unknown[]) => getSettings(...args),
  updateSettings: (...args: unknown[]) => updateSettings(...args),
}))

import {
  useDesktopRuntimeMode,
  DESKTOP_RUNTIME_MODES,
  _resetDesktopRuntimeModeForTest,
} from '@/composables/useDesktopRuntimeMode'

describe('useDesktopRuntimeMode', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    _resetDesktopRuntimeModeForTest()
  })

  it('提供四档运行权限（沙箱运行/审核模式/完全放开/自动模式）', () => {
    expect(DESKTOP_RUNTIME_MODES).toEqual(['sandbox', 'review', 'full', 'auto'])
  })

  it('未加载前默认 full（= 后端现状默认，零回归）', () => {
    const { mode } = useDesktopRuntimeMode()
    expect(mode.value).toBe('full')
  })

  it('load 从后端 settings.advanced 读取运行档', async () => {
    getSettings.mockResolvedValue({
      settings: { advanced: { desktop_runtime_mode: 'review' } },
    })
    const { load, mode } = useDesktopRuntimeMode()
    await load()
    expect(mode.value).toBe('review')
  })

  it('load 兼容 ApiResponse 包裹壳（res.data.settings / res.data）', async () => {
    getSettings.mockResolvedValue({
      data: { settings: { advanced: { desktop_runtime_mode: 'auto' } } },
    })
    const { load, mode } = useDesktopRuntimeMode()
    await load()
    expect(mode.value).toBe('auto')
  })

  it('load 收到非法值回退 full', async () => {
    getSettings.mockResolvedValue({
      settings: { advanced: { desktop_runtime_mode: 'nope' } },
    })
    const { load, mode } = useDesktopRuntimeMode()
    await load()
    expect(mode.value).toBe('full')
  })

  it('load 失败静默保持当前档', async () => {
    getSettings.mockRejectedValue(new Error('network'))
    const { load, mode } = useDesktopRuntimeMode()
    await expect(load()).resolves.toBeUndefined()
    expect(mode.value).toBe('full')
  })

  it('setMode 更新并写入后端 advanced 段', async () => {
    updateSettings.mockResolvedValue({ data: { code: 0 } })
    const { setMode, mode } = useDesktopRuntimeMode()
    await setMode('sandbox')
    expect(mode.value).toBe('sandbox')
    expect(updateSettings).toHaveBeenCalledWith('advanced', {
      desktop_runtime_mode: 'sandbox',
    })
  })

  it('setMode 后端失败回滚原档', async () => {
    updateSettings.mockRejectedValue(new Error('500'))
    const { setMode, mode } = useDesktopRuntimeMode()
    await setMode('auto')
    expect(mode.value).toBe('full')
  })

  it('setMode 忽略非法档位', async () => {
    const { setMode, mode } = useDesktopRuntimeMode()
    // @ts-expect-error 故意传非法值
    await setMode('ultra')
    expect(mode.value).toBe('full')
    expect(updateSettings).not.toHaveBeenCalled()
  })

  it('模块级单例：多处调用共享同一档位', async () => {
    updateSettings.mockResolvedValue({ data: { code: 0 } })
    const a = useDesktopRuntimeMode()
    await a.setMode('review')
    const b = useDesktopRuntimeMode()
    expect(b.mode.value).toBe('review')
  })
})

import { createApp, defineComponent } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import Antd from '@/antd'

describe('Ant Design 按需装配', () => {
  it('注册 Modal 且只安装带 install 的组件', () => {
    const app = createApp(defineComponent({ render: () => null }))
    const useSpy = vi.spyOn(app, 'use')
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})

    app.use(Antd)

    expect(app.component('AModal')).toBeDefined()
    for (const [plugin] of useSpy.mock.calls) {
      expect(
        typeof plugin === 'function'
        || (typeof plugin === 'object' && plugin !== null && typeof plugin.install === 'function'),
      ).toBe(true)
    }
    expect(warnSpy).not.toHaveBeenCalled()

    warnSpy.mockRestore()
    useSpy.mockRestore()
  })
})

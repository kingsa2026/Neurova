import { describe, it, expect } from 'vitest'
import {
  useComputerPanel,
  describeComputerAction,
  isComputerTool,
} from '@/composables/useComputerPanel'

describe('isComputerTool', () => {
  it('识别桌面与浏览器工具', () => {
    expect(isComputerTool('computer_click')).toBe(true)
    expect(isComputerTool('computer_screenshot')).toBe(true)
    expect(isComputerTool('browser_navigate')).toBe(true)
  })

  it('不误判普通工具', () => {
    expect(isComputerTool('web_search')).toBe(false)
    expect(isComputerTool('file_read')).toBe(false)
    expect(isComputerTool('')).toBe(false)
    expect(isComputerTool('computers_click')).toBe(false)
  })
})

describe('describeComputerAction', () => {
  it('为各类操作生成可读摘要', () => {
    expect(describeComputerAction('computer_screenshot', {})).toContain('截取')
    expect(describeComputerAction('computer_click', { x: 10, y: 20 })).toContain('10')
    expect(describeComputerAction('computer_shell', { command: 'ls -la' })).toContain('ls -la')
    expect(describeComputerAction('browser_navigate', { url: 'https://example.com' })).toContain(
      'https://example.com',
    )
    expect(describeComputerAction('browser_type', { selector: '#kw' })).toContain('#kw')
  })

  it('超长命令截断', () => {
    const summary = describeComputerAction('computer_shell', { command: 'x'.repeat(100) })
    expect(summary.length).toBeLessThan(80)
    expect(summary.endsWith('…')).toBe(true)
  })

  it('未知工具回退到工具名，空参数不抛异常', () => {
    expect(describeComputerAction('custom_tool', {})).toBe('custom_tool')
    expect(() => describeComputerAction('computer_click')).not.toThrow()
  })
})

describe('useComputerPanel', () => {
  it('handleComputerAction 记录动作并自动打开分屏', () => {
    const panel = useComputerPanel()
    expect(panel.state.open).toBe(false)

    panel.handleComputerAction({
      tool: 'browser_navigate',
      params: { url: 'https://example.com' },
      success: true,
      url: 'https://example.com',
    })

    expect(panel.state.open).toBe(true)
    expect(panel.state.actions).toHaveLength(1)
    const entry = panel.state.actions[0]
    expect(entry.tool).toBe('browser_navigate')
    expect(entry.kind).toBe('browser')
    expect(entry.success).toBe(true)
    expect(panel.state.browserUrl).toBe('https://example.com')
  })

  it('截图动作生成 data URL 并更新最新截图', () => {
    const panel = useComputerPanel()
    panel.handleComputerAction({ tool: 'computer_screenshot', params: {}, success: true, screenshot: 'QUJD' })
    expect(panel.state.latestScreenshot).toBe('data:image/png;base64,QUJD')
    expect(panel.state.actions[0].screenshot).toBe('data:image/png;base64,QUJD')
  })

  it('失败动作保留错误信息', () => {
    const panel = useComputerPanel()
    panel.handleComputerAction({ tool: 'computer_click', params: {}, success: false, error: '需要 pyautogui' })
    expect(panel.state.actions[0].success).toBe(false)
    expect(panel.state.actions[0].error).toBe('需要 pyautogui')
  })

  it('动作日志超过上限时丢弃最旧的', () => {
    const panel = useComputerPanel(3)
    for (let i = 0; i < 5; i++) {
      panel.handleComputerAction({ tool: 'computer_scroll', params: {}, success: true })
    }
    expect(panel.state.actions).toHaveLength(3)
    // 最旧的两条被移除
    expect(panel.state.actions[0].id).not.toBe(panel.state.actions.at(-1)!.id)
  })

  it('handleToolCall 仅对电脑类工具打开分屏并置忙碌', () => {
    const panel = useComputerPanel()
    panel.handleToolCall('web_search')
    expect(panel.state.open).toBe(false)

    panel.handleToolCall('computer_click')
    expect(panel.state.open).toBe(true)
    expect(panel.state.busy).toBe(true)
  })

  it('close/clear/toggleMinimized 状态切换', () => {
    const panel = useComputerPanel()
    panel.handleComputerAction({ tool: 'computer_scroll', params: {}, success: true })
    panel.toggleMinimized()
    expect(panel.state.minimized).toBe(true)

    panel.close()
    expect(panel.state.open).toBe(false)

    panel.clear()
    expect(panel.state.actions).toHaveLength(0)
    expect(panel.state.latestScreenshot).toBeUndefined()
  })

  it('无效 payload 安全忽略', () => {
    const panel = useComputerPanel()
    expect(() => panel.handleComputerAction(undefined as never)).not.toThrow()
    expect(() => panel.handleComputerAction({})).not.toThrow()
    expect(panel.state.actions).toHaveLength(0)
  })
})

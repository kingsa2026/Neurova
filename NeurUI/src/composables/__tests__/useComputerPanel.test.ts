import { describe, it, expect } from 'vitest'
import {
  createComputerPanel,
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

describe('createComputerPanel', () => {
  it('handleComputerAction 记录动作并自动打开分屏', () => {
    const panel = createComputerPanel()
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
    const panel = createComputerPanel()
    panel.handleComputerAction({ tool: 'computer_screenshot', params: {}, success: true, screenshot: 'QUJD' })
    expect(panel.state.latestScreenshot).toBe('data:image/png;base64,QUJD')
    expect(panel.state.actions[0].screenshot).toBe('data:image/png;base64,QUJD')
  })

  it('失败动作保留错误信息', () => {
    const panel = createComputerPanel()
    panel.handleComputerAction({ tool: 'computer_click', params: {}, success: false, error: '需要 pyautogui' })
    expect(panel.state.actions[0].success).toBe(false)
    expect(panel.state.actions[0].error).toBe('需要 pyautogui')
  })

  it('动作日志超过上限时丢弃最旧的', () => {
    const panel = createComputerPanel(3)
    for (let i = 0; i < 5; i++) {
      panel.handleComputerAction({ tool: 'computer_scroll', params: {}, success: true })
    }
    expect(panel.state.actions).toHaveLength(3)
    // 最旧的两条被移除
    expect(panel.state.actions[0].id).not.toBe(panel.state.actions.at(-1)!.id)
  })

  it('handleToolCall 仅对电脑类工具打开分屏并置忙碌', () => {
    const panel = createComputerPanel()
    panel.handleToolCall('web_search')
    expect(panel.state.open).toBe(false)

    panel.handleToolCall('computer_click')
    expect(panel.state.open).toBe(true)
    expect(panel.state.busy).toBe(true)
  })

  it('close/clear/toggleMinimized 状态切换', () => {
    const panel = createComputerPanel()
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
    const panel = createComputerPanel()
    expect(() => panel.handleComputerAction(undefined as never)).not.toThrow()
    expect(() => panel.handleComputerAction({})).not.toThrow()
    expect(panel.state.actions).toHaveLength(0)
  })

  it('R2-5 refreshed 事件更新最近一条动作的画面而非新开日志行', () => {
    const panel = createComputerPanel()
    panel.handleComputerAction({ tool: 'computer_click', params: { x: 10, y: 20 }, success: true })
    expect(panel.state.actions).toHaveLength(1)
    expect(panel.state.actions[0].screenshot).toBeUndefined()

    panel.handleComputerAction({
      tool: 'computer_click',
      params: { x: 10, y: 20 },
      success: true,
      refreshed: true,
      screenshot: 'UkVGUkVTSA==',
    })
    // 不新增日志行
    expect(panel.state.actions).toHaveLength(1)
    // 该动作的画面被补上，且成为最新截图
    expect(panel.state.actions[0].screenshot).toBe('data:image/png;base64,UkVGUkVTSA==')
    expect(panel.state.latestScreenshot).toBe('data:image/png;base64,UkVGUkVTSA==')
  })

  it('R2-5 点击动作设置位置标记（供面板渲染 agent 点击点）', () => {
    const panel = createComputerPanel()
    panel.handleComputerAction({
      tool: 'computer_click',
      params: { x: 300, y: 200 },
      success: true,
    })
    expect(panel.state.clickMarker).toBeDefined()
    expect(panel.state.clickMarker!.x).toBe(300)
    expect(panel.state.clickMarker!.y).toBe(200)

    panel.clear()
    expect(panel.state.clickMarker).toBeUndefined()
  })

  it('R2-5 非 computer_click 动作不设置标记', () => {
    const panel = createComputerPanel()
    panel.handleComputerAction({ tool: 'computer_type', params: { text: 'x' }, success: true })
    expect(panel.state.clickMarker).toBeUndefined()
  })

  it('R2-5 ActionResult 契约字段落到日志条目', () => {
    const panel = createComputerPanel()
    panel.handleComputerAction({
      tool: 'computer_click_element',
      params: { index: 0 },
      success: true,
      action_result: {
        route: 'uia',
        effect: 'confirmed',
        delivery: 'background',
        evidence: ['delivery_ack'],
      },
    })
    const entry = panel.state.actions[0]
    expect(entry.route).toBe('uia')
    expect(entry.effect).toBe('confirmed')

    panel.handleComputerAction({
      tool: 'browser_click_role',
      params: { role: 'button' },
      success: false,
      error: '快照中未找到',
      action_result: { route: 'camofox_ref', effect: 'refused', refusal_code: 'ref_not_found' },
    })
    expect(panel.state.actions[1].route).toBe('camofox_ref')
    expect(panel.state.actions[1].refusalCode).toBe('ref_not_found')
  })

  it('R2-5 新桌面工具生成可读摘要', () => {
    expect(describeComputerAction('computer_dom_snapshot', {})).toContain('桌面')
    expect(describeComputerAction('computer_click_element', { index: 3 })).toContain('3')
    expect(describeComputerAction('computer_set_value', { value: '你好世界' })).toContain('你好世界')
  })

  it('SSH 工具生成含 host 与命令的摘要', () => {
    expect(describeComputerAction('computer_ssh_exec', { host: '10.0.0.5', command: 'uptime' })).toContain('10.0.0.5')
    expect(describeComputerAction('computer_ssh_exec', { host: 'h', command: 'uptime' })).toContain('uptime')
  })
})

describe('SSH/shell 终端视图', () => {
  it('terminal 负载切到终端视口并累积转录', () => {
    const panel = createComputerPanel()
    panel.handleComputerAction({
      tool: 'computer_ssh_exec',
      params: { host: 'h1', command: 'ls' },
      success: true,
      terminal: { command: 'ls', stdout: 'file1\nfile2', stderr: '', host: 'h1', exit: 0 },
    })
    expect(panel.state.view).toBe('terminal')
    expect(panel.state.terminalTranscript).toContain('$ [h1] ls')
    expect(panel.state.terminalTranscript).toContain('file1')
  })

  it('非零退出码追加 exit 标记', () => {
    const panel = createComputerPanel()
    panel.handleComputerAction({
      tool: 'computer_ssh_exec',
      params: { host: 'h1', command: 'false' },
      success: false,
      terminal: { command: 'false', stdout: '', stderr: 'boom', host: 'h1', exit: 1 },
    })
    expect(panel.state.terminalTranscript).toContain('boom')
    expect(panel.state.terminalTranscript).toContain('[exit 1]')
  })

  it('截图动作把视口切回桌面', () => {
    const panel = createComputerPanel()
    panel.handleComputerAction({
      tool: 'computer_ssh_exec',
      params: { host: 'h1', command: 'ls' },
      success: true,
      terminal: { command: 'ls', stdout: 'x', stderr: '', host: 'h1', exit: 0 },
    })
    expect(panel.state.view).toBe('terminal')
    panel.handleComputerAction({
      tool: 'computer_screenshot',
      params: {},
      success: true,
      screenshot: 'AAAA',
    })
    expect(panel.state.view).toBe('desktop')
  })

  it('clear 重置终端转录与视口', () => {
    const panel = createComputerPanel()
    panel.handleComputerAction({
      tool: 'computer_ssh_exec',
      params: { host: 'h1', command: 'ls' },
      success: true,
      terminal: { command: 'ls', stdout: 'x', stderr: '', host: 'h1', exit: 0 },
    })
    panel.clear()
    expect(panel.state.terminalTranscript).toBe('')
    expect(panel.state.view).toBe('desktop')
  })
})

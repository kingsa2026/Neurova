import { reactive } from 'vue'
import i18n from '@/i18n'

/**
 * 电脑操作分屏面板状态机
 *
 * 数据来源（双通道，任一到达都驱动面板）：
 * - WS 会话同步事件 computer_action（后端工具执行时实时广播，主通道）
 * - SSE tool_call/tool_result 中的 computer_* 与 browser_* 工具名（兜底开屏）
 *
 * Agent 操作电脑/浏览器时面板自动打开（分屏），展示实时截图与动作日志。
 */

export interface ComputerActionEntry {
  id: string
  /** 工具名，如 computer_click / browser_navigate */
  tool: string
  kind: 'desktop' | 'browser'
  /** 一句话摘要（操作日志） */
  summary: string
  success: boolean
  error?: string
  timestamp: string
  /** data URL 形式的截图（截图类动作携带） */
  screenshot?: string
  /** 浏览器当前 URL */
  url?: string
}

export interface ComputerPanelState {
  open: boolean
  minimized: boolean
  /** Agent 正在执行电脑类操作 */
  busy: boolean
  actions: ComputerActionEntry[]
  latestScreenshot?: string
  browserUrl?: string
}

const COMPUTER_TOOL_PREFIXES = ['computer_', 'browser_']

/**
 * 模块级共享单例（2026-09-08 dock 收编）：ChatPage 的 WS/SSE 处理器与
 * dock 的 ComputerTab 必须共享同一 state；useComputerPanel() 每次调用
 * 返回同一实例（工厂签名保留兼容既有调用方）。
 */
export interface ComputerPanelApi {
  state: ComputerPanelState
  handleComputerAction: (payload: Record<string, any> | undefined | null) => void
  handleToolCall: (toolName: string) => void
  markIdle: () => void
  open: () => void
  close: () => void
  toggleMinimized: () => void
  clear: () => void
}

let _sharedPanel: ComputerPanelApi | null = null

// 测试环境清理钩子（可选注入；生产无感知）
export function resetComputerPanelForTest(): void {
  _sharedPanel = null
}

export function isComputerTool(name: string): boolean {
  if (!name) return false
  return COMPUTER_TOOL_PREFIXES.some((p) => name.startsWith(p))
}

export function describeComputerAction(tool: string, params: Record<string, unknown> = {}): string {
  const p = params || {}
  const ellipsize = (s: string, max: number) => `${s.slice(0, max)}${s.length > max ? '…' : ''}`
  switch (tool) {
    case 'computer_screenshot':
      return i18n.global.t('ui.actScreenshot')
    case 'computer_click':
      return i18n.global.t('ui.actClick', { x: p.x ?? '?', y: p.y ?? '?' })
    case 'computer_type':
      return i18n.global.t('ui.actType', { text: ellipsize(String(p.text ?? ''), 30) })
    case 'computer_scroll':
      return i18n.global.t('ui.actScroll')
    case 'computer_shell':
      return i18n.global.t('ui.actShell', { cmd: ellipsize(String(p.command ?? ''), 60) })
    case 'browser_navigate':
      return i18n.global.t('ui.actNavigate', { url: String(p.url ?? '') })
    case 'browser_click':
      return i18n.global.t('ui.actBrowserClick', { sel: String(p.selector ?? p.text ?? '') })
    case 'browser_type':
      return i18n.global.t('ui.actBrowserType', { sel: String(p.selector ?? '?') })
    case 'browser_screenshot':
      return i18n.global.t('ui.actBrowserScreenshot')
    case 'browser_extract_text':
      return i18n.global.t('ui.actExtractText')
    default:
      return tool
  }
}

let entrySeq = 0

export function createComputerPanel(maxActions = 50): ComputerPanelApi {
  const state = reactive<ComputerPanelState>({
    open: false,
    minimized: false,
    busy: false,
    actions: [],
  })
  /** 处理 WS computer_action 事件 payload */
  function handleComputerAction(payload: Record<string, any> | undefined | null): void {
    if (!payload || typeof payload !== 'object') return
    const tool = String(payload.tool || '')
    if (!tool) return

    const b64 = typeof payload.screenshot === 'string' && payload.screenshot ? payload.screenshot : undefined
    const params = (payload.params && typeof payload.params === 'object' ? payload.params : {}) as Record<
      string,
      unknown
    >
    entrySeq += 1
    const entry: ComputerActionEntry = {
      id: `${Date.now()}-${entrySeq}`,
      tool,
      kind: tool.startsWith('browser_') ? 'browser' : 'desktop',
      summary: String(payload.summary || describeComputerAction(tool, params)),
      success: payload.success !== false,
      error: payload.error ? String(payload.error) : undefined,
      timestamp: String(payload.timestamp || new Date().toISOString()),
      screenshot: b64 ? `data:image/png;base64,${b64}` : undefined,
      url: payload.url ? String(payload.url) : undefined,
    }

    state.actions.push(entry)
    if (state.actions.length > maxActions) {
      state.actions.splice(0, state.actions.length - maxActions)
    }
    if (entry.screenshot) state.latestScreenshot = entry.screenshot
    if (entry.url) state.browserUrl = entry.url
    state.busy = false
    // 自动分屏：Agent 操作电脑时自动展开（ZCode 式跟随）。
    // 2026-09-08 dock 收编：开屏统一走 rightDock（computer tab），state.open
    // 保留为兼容位（组件挂载已迁入 dock，不再由它驱动 v-if）。
    state.open = true
    openComputerDockTab()
  }

  /** 打开 dock 的 computer tab（延迟导入防循环依赖：rightDock 不依赖本模块） */
  function openComputerDockTab(): void {
    void import('@/stores/rightDock').then(({ useRightDockStore }) => {
      useRightDockStore().openComputer()
    })
  }

  /** SSE 兜底：看到电脑类工具调用即开屏并置忙碌 */
  function handleToolCall(toolName: string): void {
    if (!isComputerTool(toolName)) return
    state.open = true
    state.busy = true
    openComputerDockTab()
  }

  function markIdle(): void {
    state.busy = false
  }

  function open(): void {
    state.open = true
  }

  function close(): void {
    state.open = false
  }

  function toggleMinimized(): void {
    state.minimized = !state.minimized
  }

  function clear(): void {
    state.actions.splice(0)
    state.latestScreenshot = undefined
    state.browserUrl = undefined
  }

  return (_sharedPanel = { state, handleComputerAction, handleToolCall, markIdle, open, close, toggleMinimized, clear })
}

/**
 * 共享实例入口：ChatPage 与 dock ComputerTab 调用同一单例
 * （WS/SSE 处理器写入的状态必须与 dock 面板读到的状态一致）。
 */
export function useComputerPanel(): ComputerPanelApi {
  if (!_sharedPanel) createComputerPanel()
  return _sharedPanel!
}

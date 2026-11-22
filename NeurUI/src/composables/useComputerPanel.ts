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

/** 窗口清单行（computer_list_windows 的事件载荷形状，增强③） */
export interface ComputerWindowRow {
  title: string
  class_name: string
  pid: number
  hwnd: number
  rect: { x: number; y: number; w: number; h: number }
  focused: boolean
}

/** AD 批：dom_snapshot 快照质量元信息（后端按需出现——确有截断/骨架/下钻才带） */
export interface ComputerSnapshotMeta {
  truncated: boolean
  depthTruncated: boolean
  observedMaxDepth?: number
  skeleton: boolean
  omittedCount?: number
  drilledFromIndex?: number
  drilledFromRuntimeId?: string
  subtreeTruncatedCount: number
}

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
  /** R1-2 ActionResult 契约：投递路径（uia/app_post/playwright_role/...） */
  route?: string
  /** R1-2 ActionResult 契约：效果档（confirmed/unverifiable/refused/...） */
  effect?: string
  /** R1-2 ActionResult 契约：精确拒绝码（refused 时） */
  refusalCode?: string
  /** P1-2 ActionResult 契约：重试建议（reobserve/retry/never） */
  retry?: string
  /** T-01 ActionResult 契约：投递平面（background/foreground/isolated_plane/not_applicable） */
  delivery?: string
  /** T-01 ActionResult 契约：验证证据（有则面板给"已验证"档，无则明示未验证） */
  evidence?: string[]
  /** T-01 ActionResult 契约：跳级去向（refused 时点名"为何降级到下一级"） */
  escalation?: Record<string, string>
  /** 增强③：窗口清单（computer_list_windows 结果） */
  windows?: ComputerWindowRow[]
  /** SSH/shell 终端负载（命令 + 输出），面板渲染成终端窗口 */
  terminal?: { command: string; stdout: string; stderr: string; host?: string; exit?: number }
  /** AD 批：dom_snapshot 快照质量（深度剪枝/骨架折叠/下钻来源），按需出现 */
  snapshotMeta?: ComputerSnapshotMeta
}

export interface ComputerPanelState {
  open: boolean
  minimized: boolean
  /** Agent 正在执行电脑类操作 */
  busy: boolean
  actions: ComputerActionEntry[]
  latestScreenshot?: string
  browserUrl?: string
  /** R2-5 agent 点击位置标记（截图像素坐标，面板按图片尺寸换算成百分比） */
  clickMarker?: { x: number; y: number; ts: number }
  /** 主视口模式：桌面截图 / 终端（SSH·shell 命令流） */
  view: 'desktop' | 'terminal'
  /** 累积终端转录（$ 命令 + stdout + stderr），终端视口渲染 */
  terminalTranscript: string
  /** 增强③：最近一次窗口清单（computer_list_windows），面板渲染表格 */
  latestWindows?: ComputerWindowRow[]
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
  /** U8：park 轮询开始 → 终端视图提示（按 poll_after 间隔轮询中） */
  noteParkPolling: (park: { parkId: string; pollAfterSec: number }) => void
  /** U8：park 终态回灌 → 用最终结果刷新终端视图（completed=结果，failed=失败原因） */
  applyParkResult: (data: Record<string, unknown>) => void
  /** U8：轮询自身失败（404/超限/网络）→ 终端视图诚实报错 */
  applyParkFailure: (reason: string) => void
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
    case 'browser_dom_snapshot':
      return i18n.global.t('computerPanel.actBrowserDomSnapshot')
    case 'browser_dom_read':
      return i18n.global.t('computerPanel.actBrowserDomRead')
    case 'browser_click_role':
      return i18n.global.t('computerPanel.actBrowserClickRole', {
        role: String(p.role ?? '?'),
        name: String(p.name ?? ''),
      })
    case 'browser_fill_role':
      return i18n.global.t('computerPanel.actBrowserFillRole', {
        role: String(p.role ?? '?'),
        name: String(p.name ?? ''),
      })
    case 'browser_click_ref':
      return i18n.global.t('computerPanel.actBrowserClickRef', { ref: String(p.ref ?? '?') })
    case 'browser_fill_ref':
      return i18n.global.t('computerPanel.actBrowserFillRef', { ref: String(p.ref ?? '?') })
    case 'browser_tab_open':
      return i18n.global.t('computerPanel.actBrowserTabOpen', { url: String(p.url ?? '') })
    case 'browser_tab_list':
      return i18n.global.t('computerPanel.actBrowserTabList')
    case 'browser_tab_switch':
      return i18n.global.t('computerPanel.actBrowserTabSwitch', { id: String(p.target_id ?? '?') })
    case 'browser_tab_close':
      return i18n.global.t('computerPanel.actBrowserTabClose', { id: String(p.target_id ?? '?') })
    case 'browser_eval':
      return i18n.global.t('computerPanel.actBrowserEval', {
        script: ellipsize(String(p.script ?? ''), 40),
      })
    case 'browser_back':
      return i18n.global.t('computerPanel.actBrowserBack')
    case 'browser_forward':
      return i18n.global.t('computerPanel.actBrowserForward')
    case 'browser_reload':
      return i18n.global.t('computerPanel.actBrowserReload')
    case 'browser_wait': {
      const cond = String(p.selector ?? p.state ?? (p.ms != null ? `${p.ms}ms` : '?'))
      return i18n.global.t('computerPanel.actBrowserWait', { cond })
    }
    case 'browser_scroll':
      return i18n.global.t('computerPanel.actBrowserScroll', { x: p.scroll_x ?? 0, y: p.scroll_y ?? 0 })
    case 'browser_press':
      return i18n.global.t('computerPanel.actBrowserPress', { key: String(p.key ?? '?') })
    case 'browser_hover':
      return i18n.global.t('computerPanel.actBrowserHover', {
        role: String(p.role ?? '?'),
        name: String(p.name ?? ''),
      })
    case 'browser_select':
      return i18n.global.t('computerPanel.actBrowserSelect', {
        role: String(p.role ?? '?'),
        values: String((p.values as string[] | undefined)?.join(',') ?? ''),
      })
    case 'browser_check':
      return i18n.global.t(
        p.checked ? 'computerPanel.actBrowserCheck' : 'computerPanel.actBrowserUncheck',
        { role: String(p.role ?? '?'), name: String(p.name ?? '') },
      )
    case 'browser_cookies':
      return i18n.global.t('computerPanel.actBrowserCookies', { action: String(p.action ?? 'get') })
    case 'browser_storage':
      return i18n.global.t('computerPanel.actBrowserStorage', {
        kind: String(p.kind ?? 'local'),
        action: String(p.action ?? 'get'),
      })
    case 'browser_console':
      return i18n.global.t('computerPanel.actBrowserConsole')
    case 'browser_download':
      return i18n.global.t('computerPanel.actBrowserDownload', { url: String(p.url ?? '') })
    case 'browser_pdf':
      return i18n.global.t('computerPanel.actBrowserPdf')
    case 'browser_drag':
      return i18n.global.t('computerPanel.actBrowserDrag', {
        source: String(p.source_role ?? '?'),
        target: String(p.target_role ?? '?'),
      })
    case 'browser_upload':
      return i18n.global.t('computerPanel.actBrowserUpload', {
        n: (p.paths as unknown[] | undefined)?.length ?? 0,
      })
    case 'computer_dom_snapshot':
      return i18n.global.t('computerPanel.actDesktopSnapshot')
    case 'computer_click_element':
      return i18n.global.t('computerPanel.actClickElement', {
        target: String(p.runtime_id ?? p.index ?? '?'),
      })
    case 'computer_set_value':
      return i18n.global.t('computerPanel.actSetValue', {
        text: ellipsize(String(p.value ?? ''), 30),
      })
    case 'computer_som_snapshot':
      return i18n.global.t('computerPanel.actSomSnapshot')
    case 'computer_click_mark':
      return i18n.global.t('computerPanel.actClickMark', { id: String(p.index ?? '?') })
    case 'computer_ssh_exec':
      return i18n.global.t('computerPanel.actSsh', {
        host: String(p.host ?? ''),
        cmd: ellipsize(String(p.command ?? ''), 60),
      })
    case 'computer_list_windows':
      return i18n.global.t('computerPanel.actListWindows')
    case 'computer_key':
      return i18n.global.t('computerPanel.actKey', { key: String(p.key ?? '?') })
    case 'computer_paste':
      return i18n.global.t('computerPanel.actPaste', { text: ellipsize(String(p.text ?? ''), 30) })
    case 'computer_drag':
      return i18n.global.t('computerPanel.actDrag', {
        sx: p.start_x ?? '?',
        sy: p.start_y ?? '?',
        ex: p.end_x ?? '?',
        ey: p.end_y ?? '?',
      })
    default:
      return tool
  }
}

let entrySeq = 0

/** R1-2/T-01 ActionResult 契约落到条目展示字段的形状 */
interface ActionResultFields {
  route?: string
  effect?: string
  refusalCode?: string
  retry?: string
  delivery?: string
  evidence?: string[]
  escalation?: Record<string, string>
}

/** R2-5/T-01 ActionResult 契约字段抽取（payload.action_result → 条目展示字段）
 *
 * `delivery`/`evidence`/`escalation` 后端一直在产出并整体透传，此前只抽三键
 * 等于把"走哪条通道、有没有碰用户桌面、为何跳到下一级"在 dock 上抹掉了——
 * 无抢占这件事本来就该在这儿被看见。
 */
function extractActionResult(payload: Record<string, any>): ActionResultFields | undefined {
  const ar = payload.action_result
  if (!ar || typeof ar !== 'object') return undefined
  const out: ActionResultFields = {}
  if (typeof ar.route === 'string') out.route = ar.route
  if (typeof ar.effect === 'string') out.effect = ar.effect
  if (typeof ar.refusal_code === 'string') out.refusalCode = ar.refusal_code
  if (typeof ar.retry === 'string') out.retry = ar.retry
  if (typeof ar.delivery === 'string') out.delivery = ar.delivery
  if (Array.isArray(ar.evidence)) {
    out.evidence = ar.evidence.filter((kind: unknown) => typeof kind === 'string')
  }
  if (ar.escalation && typeof ar.escalation === 'object' && !Array.isArray(ar.escalation)) {
    out.escalation = ar.escalation as Record<string, string>
  }
  const hasAny =
    out.route || out.effect || out.refusalCode || out.retry || out.delivery || out.evidence || out.escalation
  return hasAny ? out : undefined
}

/** 增强①：重试建议 → 徽标提示（技术码形态，与 route/effect 同风格） */
const RETRY_HINTS: Record<string, string> = {
  reobserve: '↻reobserve',
  retry: '↻retry',
  never: '⛔never',
}

/** AD 批：payload.snapshot_meta（snake_case）→ 条目展示形状（camelCase），无则 undefined */
function extractSnapshotMeta(payload: Record<string, any>): ComputerSnapshotMeta | undefined {
  const m = payload.snapshot_meta
  if (!m || typeof m !== 'object') return undefined
  const drilled = m.drilled_from
  const meta: ComputerSnapshotMeta = {
    truncated: m.truncated === true,
    depthTruncated: m.depth_truncated === true,
    skeleton: m.skeleton === true,
    subtreeTruncatedCount: typeof m.subtree_truncated_count === 'number' ? m.subtree_truncated_count : 0,
  }
  if (typeof m.observed_max_depth === 'number') meta.observedMaxDepth = m.observed_max_depth
  if (typeof m.omitted_count === 'number') meta.omittedCount = m.omitted_count
  if (drilled && typeof drilled === 'object') {
    if (typeof drilled.index === 'number') meta.drilledFromIndex = drilled.index
    if (typeof drilled.runtime_id === 'string') meta.drilledFromRuntimeId = drilled.runtime_id
  }
  return meta
}

/** AD 批：快照质量 → 一行可读摘要（只拼存在的维度；全无则空串） */
export function snapshotMetaText(meta: ComputerSnapshotMeta): string {
  const parts: string[] = []
  if (meta.depthTruncated) {
    parts.push(i18n.global.t('computerPanel.snapDepthCut', { depth: meta.observedMaxDepth ?? '?' }))
  }
  if (meta.omittedCount != null) {
    parts.push(i18n.global.t('computerPanel.snapSkeletonFold', { n: meta.omittedCount }))
  }
  if (meta.drilledFromIndex != null || meta.drilledFromRuntimeId) {
    parts.push(
      i18n.global.t('computerPanel.snapDrilledFrom', {
        target: meta.drilledFromIndex ?? meta.drilledFromRuntimeId,
      }),
    )
  }
  if (meta.subtreeTruncatedCount > 0) {
    parts.push(i18n.global.t('computerPanel.snapSubtreeCut', { n: meta.subtreeTruncatedCount }))
  }
  return parts.join(' · ')
}

function retryHint(retry?: string): string {
  if (!retry) return ''
  return RETRY_HINTS[retry] ?? `↻${retry}`
}

/** T-01 投递事实徽标文本：一行呈现"走了哪条通道 / 有没有碰真实输入设备 / 是否被验证"。
 *
 * 无抢占不是口号——`delivery=foreground` 就意味着动了用户的光标键盘，
 * `evidence` 为空则代表"投递了但没验证手段"。这一行是该事实在 dock 上唯一可被证伪处。
 * 增强①：`retry` 建议随行（reobserve=先重观察 / never=不可重试 / retry=可重试）。
 */
export function actionBadgeText(
  entry: Pick<
    ComputerActionEntry,
    'route' | 'delivery' | 'effect' | 'refusalCode' | 'retry' | 'evidence' | 'escalation'
  >,
): string {
  const hint = retryHint(entry.retry)
  if (entry.effect === 'refused') {
    const code = entry.refusalCode ?? ''
    const to = entry.escalation?.target
    const base = to ? (code ? `${code}→${to}` : `→${to}`) : code
    return hint ? (base ? `${base} ${hint}` : hint) : base
  }
  const head = [entry.route, entry.delivery, entry.effect]
    .filter((part): part is string => !!part)
    .join('·')
  const parts = [head, hint].filter((part): part is string => !!part)
  if (!parts.length) return ''
  const text = parts.join(' ')
  return entry.evidence && entry.evidence.length > 0 ? `${text} ✓` : text
}

export function createComputerPanel(maxActions = 50): ComputerPanelApi {
  const state = reactive<ComputerPanelState>({
    open: false,
    minimized: false,
    busy: false,
    actions: [],
    view: 'desktop',
    terminalTranscript: '',
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
    const actionResult = extractActionResult(payload)
    const snapshotMeta = extractSnapshotMeta(payload)
    // 增强③：窗口清单（computer_list_windows 载荷）吸收进条目与面板状态
    const windows = Array.isArray(payload.windows)
      ? (payload.windows as ComputerWindowRow[]).filter((w) => w && typeof w === 'object')
      : undefined
    const term =
      payload.terminal && typeof payload.terminal === 'object'
        ? (payload.terminal as { command?: string; stdout?: string; stderr?: string; host?: string; exit?: number })
        : undefined

    // R0-3/R2-5 刷新事件：不新开日志行，把操作后画面补到最近一条同工具动作上
    if (payload.refreshed === true) {
      const last = [...state.actions].reverse().find((e) => e.tool === tool)
      if (b64) {
        const dataUrl = `data:image/png;base64,${b64}`
        if (last) last.screenshot = dataUrl
        state.latestScreenshot = dataUrl
      }
      state.busy = false
      return
    }

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
      terminal: term
        ? { command: String(term.command ?? ''), stdout: String(term.stdout ?? ''), stderr: String(term.stderr ?? ''), host: term.host ? String(term.host) : undefined, exit: typeof term.exit === 'number' ? term.exit : undefined }
        : undefined,
      ...(windows && windows.length ? { windows } : {}),
      ...(snapshotMeta ? { snapshotMeta } : {}),
      ...(actionResult ?? {}),
    }

    state.actions.push(entry)
    if (state.actions.length > maxActions) {
      state.actions.splice(0, state.actions.length - maxActions)
    }
    if (entry.screenshot) state.latestScreenshot = entry.screenshot
    if (entry.url) state.browserUrl = entry.url
    // 增强③：窗口清单刷新面板状态（表格视图数据源）
    if (entry.windows && entry.windows.length) state.latestWindows = entry.windows
    // 终端视图：SSH/shell 命令到达 → 累积转录并切到终端视口；截图动作切回桌面
    if (entry.terminal) {
      appendTerminal(entry.terminal)
    } else if (entry.screenshot) {
      state.view = 'desktop'
    }
    // R2-5 agent 点击位置标记（截图像素坐标）
    if (tool === 'computer_click' && entry.success && typeof params.x === 'number' && typeof params.y === 'number') {
      state.clickMarker = { x: params.x, y: params.y, ts: Date.now() }
      scheduleMarkerClear()
    }
    state.busy = false
    // 自动分屏：Agent 操作电脑时自动展开。
    // 2026-09-08 dock 收编：开屏统一走 rightDock（computer tab），state.open
    // 保留为兼容位（组件挂载已迁入 dock，不再由它驱动 v-if）。
    state.open = true
    openComputerDockTab()
  }

  /** R2-5 标记 2s 后自动淡出（测试环境无计时器依赖问题） */
  function scheduleMarkerClear(): void {
    const ts = state.clickMarker?.ts
    if (typeof setTimeout !== 'function') return
    setTimeout(() => {
      if (state.clickMarker?.ts === ts) state.clickMarker = undefined
    }, 2000)
  }

  /** 终端转录追加（$ 命令头 + stdout/stderr + 非 0 exit），并切到终端视口 */
  function appendTerminal(t: { command: string; stdout: string; stderr: string; host?: string; exit?: number }): void {
    const head = t.host ? `$ [${t.host}] ${t.command}` : `$ ${t.command}`
    state.terminalTranscript += (state.terminalTranscript ? '\n' : '') + head
    if (t.stdout) state.terminalTranscript += '\n' + t.stdout.replace(/\n+$/, '')
    if (t.stderr) state.terminalTranscript += '\n' + t.stderr.replace(/\n+$/, '')
    if (typeof t.exit === 'number' && t.exit !== 0) state.terminalTranscript += `\n[exit ${t.exit}]`
    state.view = 'terminal'
  }

  /** U8：park 轮询开始 → 终端视图提示一行（不打断既有转录） */
  function noteParkPolling(park: { parkId: string; pollAfterSec: number }): void {
    state.terminalTranscript +=
      (state.terminalTranscript ? '\n' : '') +
      i18n.global.t('computerPanel.parkPolling', { seconds: park.pollAfterSec }) +
      ` [${park.parkId}]`
    state.view = 'terminal'
    state.busy = true
  }

  /** U8：park 终态回灌 → 用最终结果刷新终端视图 */
  function applyParkResult(data: Record<string, unknown>): void {
    if (data.status === 'failed') {
      const reason = String(data.error || '')
      state.terminalTranscript +=
        (state.terminalTranscript ? '\n' : '') +
        `[park] ${i18n.global.t('computerPanel.parkFailed', { error: reason })}`
      state.view = 'terminal'
      state.busy = false
      return
    }
    const result = (data.result && typeof data.result === 'object' ? data.result : {}) as Record<string, unknown>
    appendTerminal({
      command: String(result.command ?? ''),
      stdout: String(result.stdout ?? ''),
      stderr: String(result.stderr ?? ''),
      host: result.host ? String(result.host) : undefined,
      exit: typeof result.returncode === 'number' ? result.returncode : undefined,
    })
    state.terminalTranscript += `\n[park] ${i18n.global.t('computerPanel.parkDone')}`
    state.busy = false
  }

  /** U8：轮询自身失败（404/超限/网络）→ 终端视图诚实报错 */
  function applyParkFailure(reason: string): void {
    state.terminalTranscript +=
      (state.terminalTranscript ? '\n' : '') +
      `[park] ${i18n.global.t('computerPanel.parkTimeout')}` +
      (reason ? ` (${reason})` : '')
    state.view = 'terminal'
    state.busy = false
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
    state.clickMarker = undefined
    state.terminalTranscript = ''
    state.view = 'desktop'
    state.latestWindows = undefined
  }

  return (_sharedPanel = {
    state,
    handleComputerAction,
    handleToolCall,
    markIdle,
    noteParkPolling,
    applyParkResult,
    applyParkFailure,
    open,
    close,
    toggleMinimized,
    clear,
  })
}

/**
 * 共享实例入口：ChatPage 与 dock ComputerTab 调用同一单例
 * （WS/SSE 处理器写入的状态必须与 dock 面板读到的状态一致）。
 */
export function useComputerPanel(): ComputerPanelApi {
  if (!_sharedPanel) createComputerPanel()
  return _sharedPanel!
}

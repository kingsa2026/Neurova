/**
 * 错误日志自动上报（客户端采集 + 官网 PHP 收报端点）
 *
 * 链路：window error / unhandledrejection / Vue errorHandler / 手动捕获
 *   → 脱敏 → 去重 + 本地日限额 → localStorage 持久化队列
 *   → fetch(keepalive) / sendBeacon 上报 https://www.neurova.top/error-report.php
 *
 * 用户标识唯一性：首次生成随机固定代号（nv_client_id，UUID），此后永久复用，
 *   不上传用户名/邮箱/token——管理员按此代号检索。
 * 平台区分：tauri 桌面壳 → desktop-windows / desktop-linux；
 *   浏览器 → web（UA 含 Linux 记 linux、Mac 记 mac）。
 * 上报时间精确到秒（error_at 客户端生成，重复上报由收报端 UNIQUE 去重）。
 */

const STORAGE_CLIENT_ID = 'nv_client_id'
const STORAGE_QUEUE = 'nv_err_queue'
const REPORT_URL = import.meta.env.VITE_ERROR_REPORT_URL ?? 'https://www.neurova.top/error-report.php'
const MAX_QUEUE = 15
const DEDUPE_WINDOW_MS = 30_000
const DAILY_CAP = 100

export type ErrorSource = 'window' | 'promise' | 'vue' | 'manual' | 'app'

export interface ErrorReport {
  error_at: string
  client_id: string
  platform: string
  source: string
  error_code: string
  location: string
  message: string
  stack: string
  app_version: string
  ua: string
  extra?: Record<string, unknown>
}

export interface ReporterOptions {
  /** 版本号（前端包/桌面壳版本） */
  version?: string
  /** 强制启用（测试/调试用） */
  force?: boolean
}

export interface ReporterInstance {
  /** 手工捕获一条错误（Vue errorHandler / 业务代码调用） */
  capture: (source: ErrorSource, errorCode: string, message: string, stack?: string, extra?: Record<string, unknown>) => void
  /** 用户主动手动上报（不受自动开关/去重/日限额限制，仍脱敏） */
  captureManual: (message: string, extra?: Record<string, unknown>) => void
  /** 卸载全局监听 */
  dispose: () => void
  /** 调试：当前队列长度 */
  queueLength: () => number
}

// ---------------------------------------------------------------------------
// 用户标识唯一性：客户端随机固定代号
// ---------------------------------------------------------------------------

export function getClientId(): string {
  try {
    const existing = localStorage.getItem(STORAGE_CLIENT_ID)
    if (existing && /^[0-9a-fA-F-]{8,64}$/.test(existing)) return existing
    const id = crypto.randomUUID ? crypto.randomUUID() : 'nv-' + Math.random().toString(36).slice(2) + '-' + Date.now().toString(36)
    localStorage.setItem(STORAGE_CLIENT_ID, id)
    return id
  } catch {
    return 'nv-' + Math.random().toString(36).slice(2)
  }
}

// ---------------------------------------------------------------------------
// 平台检测（桌面端 / Linux 端 / Web 端区分）
// ---------------------------------------------------------------------------

export function detectPlatform(): string {
  try {
    const tauri = (window as unknown as Record<string, unknown>).__TAURI__
    const hasTauri = typeof tauri !== 'undefined' && tauri !== null
    const ua = navigator.userAgent ?? ''
    if (hasTauri) {
      return /Linux/i.test(ua) ? 'desktop-linux' : 'desktop-windows'
    }
    if (/Linux/i.test(ua) || /Android/i.test(ua)) return 'linux'
    if (/Macintosh|Mac OS X/i.test(ua)) return 'mac'
    return 'web'
  } catch {
    return 'unknown'
  }
}

// ---------------------------------------------------------------------------
// 脱敏（客户端侧再拦一道：密钥/凭据/本地路径模式打码）
// ---------------------------------------------------------------------------

const SENSITIVE_PATTERNS: Array<[RegExp, string]> = [
  [/(sk-[A-Za-z0-9_-]{8,})/g, 'sk-***'],
  [/(Bearer\s+[A-Za-z0-9._-]{8,})/gi, 'Bearer ***'],
  [/((?:access_?token|api_?key|password|secret)\s*[=:])[\w.-]{6,}/gi, '$1***'],
  [/\\?[A-Za-z]:\\Users\\[^\\\s"]+/g, 'C:\\Users\\***'],
  [/\/home\/[^\/\s"]+/g, '/home/***'],
]

export function sanitizeText(value: string, maxLen = 500): string {
  let out = String(value ?? '')
  // 控制字符剥除（保留换行便于阅读堆栈）
  out = out.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, '')
  // 敏感信息打码
  for (const [re, repl] of SENSITIVE_PATTERNS) out = out.replace(re, repl)
  // 长度封顶
  if (out.length > maxLen) out = out.slice(0, maxLen)
  return out
}

// ---------------------------------------------------------------------------
// 队列（localStorage 持久化，网络失败可重试）
// ---------------------------------------------------------------------------

interface QueueItem extends ErrorReport {}

function loadQueue(): QueueItem[] {
  try {
    const raw = localStorage.getItem(STORAGE_QUEUE)
    const arr = raw ? JSON.parse(raw) : []
    return Array.isArray(arr) ? arr.slice(0, MAX_QUEUE) : []
  } catch {
    return []
  }
}

function saveQueue(items: QueueItem[]) {
  try {
    localStorage.setItem(STORAGE_QUEUE, JSON.stringify(items.slice(0, MAX_QUEUE)))
  } catch {
    /* storage 满则丢弃队列（缓存失败不阻断主流程） */
  }
}

// ---------------------------------------------------------------------------
// 采集器
// ---------------------------------------------------------------------------

const STORAGE_REPORT_PREF = 'nv_err_report_enabled' // 'on' | 'off' | 缺省=默认策略

/** 用户偏好：true=显式开启，false=显式关闭，null=未设置（跟随默认策略） */
export function getReportEnabledPref(): boolean | null {
  try {
    const v = localStorage.getItem(STORAGE_REPORT_PREF)
    if (v === 'on') return true
    if (v === 'off') return false
    return null
  } catch {
    return null
  }
}

export function setReportEnabledPref(on: boolean): void {
  try {
    localStorage.setItem(STORAGE_REPORT_PREF, on ? 'on' : 'off')
  } catch {
    /* localStorage 不可用时仅本次会话生效 */
  }
}

/** 默认策略：生产构建默认自动启用；开发需显式 VITE_ENABLE_ERROR_REPORT=true */
function defaultReportEnabled(): boolean {
  return import.meta.env.PROD || import.meta.env.VITE_ENABLE_ERROR_REPORT === 'true'
}

/** 运行时开关（用户设置 > 默认策略）：随偏好即时生效 */
export function isErrorReporterEnabled(): boolean {
  const pref = getReportEnabledPref()
  if (pref === true) return true
  if (pref === false) return false
  return defaultReportEnabled()
}

export function initErrorReporter(opts: ReporterOptions = {}): ReporterInstance {
  const version = opts.version ?? (import.meta.env.VITE_APP_VERSION || '')
  const force = opts.force === true
  const enabled = force || isErrorReporterEnabled()

  const clientId = getClientId()
  const platform = detectPlatform()
  const lastSent = new Map<string, number>()
  let queue: QueueItem[] = loadQueue()
  let timer: ReturnType<typeof setInterval> | null = null

  const now = () => new Date()

  function todayKey(): string {
    const d = now()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  }

  function sentToday(): number {
    try {
      const raw = localStorage.getItem('nv_err_day_count')
      const data = raw ? (JSON.parse(raw) as { date: string; count: number }) : null
      return data && data.date === todayKey() ? data.count : 0
    } catch {
      return 0
    }
  }

  function markSent() {
    try {
      localStorage.setItem('nv_err_day_count', JSON.stringify({ date: todayKey(), count: sentToday() + 1 }))
    } catch {
      /* noop */
    }
  }

  let retryDelay = 30_000 // 失败后的指数退避：30s → 60s → … → 10min 封顶
  let retryTimer: ReturnType<typeof setTimeout> | null = null

  async function flush() {
    // 顺序排空：成功/客户端拒绝(4xx) 继续下一条；网络失败/5xx 保留剩余等待重试
    while (queue.length > 0) {
      const item = queue[0]
      try {
        // 注意：不能加 keepalive —— keepalive + application/json 需要 CORS
        // preflight，浏览器会直接拒绝（TypeError: Failed to fetch）。
        // 页面卸载场景交给 sendBeacon（text/plain，无 preflight）。
        const res = await fetch(REPORT_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(item),
        })
        if (res.ok) {
          queue = queue.slice(1)
          saveQueue(queue)
          markSent()
          retryDelay = 30_000 // 成功：退避归零
          continue
        }
        if (res.status === 429 || res.status >= 500) {
          scheduleRetry() // 429 限流/5xx：临时失败，保留队列退避重试
          return
        }
        if (res.status >= 400 && res.status < 500) {
          queue = queue.slice(1) // 400/404 等 schema 拒绝：永久丢弃避免死循环
          saveQueue(queue)
          continue
        }
      } catch {
        scheduleRetry() // 网络不可用：保留队列 + 退避（避免高频重试被网络层限流饿死）
        return
      }
    }
  }

  /** 失败退避：指数增长 30s→60s→120s→…→10min 封顶，成功时归零 */
  function scheduleRetry() {
    if (retryTimer) return
    retryTimer = setTimeout(() => {
      retryTimer = null
      void flush()
    }, retryDelay)
    retryDelay = Math.min(retryDelay * 2, 10 * 60_000)
  }

  /** 页面卸载兜底：sendBeacon 不需要 CORS preflight，天然 keepalive */
  function onPageHide() {
    while (queue.length > 0) {
      const item = queue[0]
      try {
        const ok = navigator.sendBeacon(REPORT_URL, JSON.stringify(item))
        if (!ok) return
        queue = queue.slice(1)
      } catch {
        return
      }
    }
    saveQueue(queue)
  }

  function enqueue(item: QueueItem) {
    queue = [...queue, item].slice(0, MAX_QUEUE)
    saveQueue(queue)
    void flush()
  }

  function buildReport(
    source: ErrorSource,
    errorCode: string,
    message: string,
    stack?: string,
    extra?: Record<string, unknown>,
  ): QueueItem {
    const safeMessage = sanitizeText(message, 500)
    const safeCode = sanitizeText(errorCode, 64).replace(/[^a-zA-Z0-9_:.-]/g, '_') || 'unknown'
    return {
      error_at: now().toISOString().slice(0, 19) + 'Z', // 精确到秒
      client_id: clientId,
      platform,
      source,
      error_code: safeCode,
      location: sanitizeText((extra?.location as string) ?? '', 200),
      message: safeMessage,
      stack: sanitizeText(stack ?? '', 4000),
      app_version: sanitizeText(version, 40),
      ua: sanitizeText(navigator.userAgent ?? '', 256),
      extra: extra && typeof extra === 'object' ? extra : undefined,
    }
  }

  function capture(source: ErrorSource, errorCode: string, message: string, stack?: string, extra?: Record<string, unknown>) {
    if (!force && !isErrorReporterEnabled()) return // 运行时门控：用户开关即时生效

    const safeMessage = sanitizeText(message, 500)
    const safeCode = sanitizeText(errorCode, 64).replace(/[^a-zA-Z0-9_:.-]/g, '_') || 'unknown'
    const dedupeKey = `${safeCode}:${safeMessage.slice(0, 64)}`
    const last = lastSent.get(dedupeKey) ?? 0
    if (now().getTime() - last < DEDUPE_WINDOW_MS) return // 同一错误 30s 窗口内只报一次
    if (sentToday() >= DAILY_CAP) return

    const report = buildReport(source, errorCode, message, stack, extra)
    lastSent.set(dedupeKey, now().getTime())
    enqueue(report)
  }

  /** 手动上报：用户主动提交，不受自动开关/去重/日限额限制（仍会脱敏） */
  function captureManual(message: string, extra?: Record<string, unknown>) {
    const text = (message ?? '').trim()
    if (!text) return
    const safeMessage = sanitizeText(text, 500)
    if (!safeMessage) return
    enqueue(
      buildReport('manual', 'user-feedback', safeMessage, '', {
        ...(extra ?? {}),
        manual: true,
      }),
    )
  }

  function onWindowError(event: ErrorEvent) {
    if (!event?.message) return
    capture('window', 'window-error', event.message, (event.error as Error | undefined)?.stack?.slice(0, 4000))
  }

  function onUnhandledRejection(event: PromiseRejectionEvent) {
    const reason = event?.reason ?? {}
    capture(
      'promise',
      'unhandled-promise',
      reason instanceof Error ? reason.message : String(reason).slice(0, 500),
      reason instanceof Error ? reason.stack : undefined,
    )
  }

  function bind() {
    window.addEventListener('error', onWindowError)
    window.addEventListener('unhandledrejection', onUnhandledRejection)
    window.addEventListener('pagehide', onPageHide)
    timer = setInterval(() => void flush(), 5 * 60_000) // 兜底周期检查（失败重试走指数退避）
  }

  // 监听器始终绑定（采集入口 capture 内部做运行时门控实现开关即时生效）
  bind()

  return {
    capture,
    captureManual,
    dispose: () => {
      window.removeEventListener('error', onWindowError)
      window.removeEventListener('unhandledrejection', onUnhandledRejection)
      window.removeEventListener('pagehide', onPageHide)
      if (timer) clearInterval(timer)
      timer = null
      if (retryTimer) clearTimeout(retryTimer)
      retryTimer = null
    },
    queueLength: () => queue.length,
  }
}

// ---------------------------------------------------------------------------
// 模块级采集器单例：App.vue 挂载后 initErrorReporter 注入实例；
// 任何业务代码可随时 captureAppError（未初始化时静默丢弃）。
// ---------------------------------------------------------------------------

const errorReporterRef: { instance: ReporterInstance | null } = { instance: null }

/** 供 App.vue 把初始化后的采集器实例交给模块单例 */
export function setErrorReporterInstance(instance: ReporterInstance | null): void {
  errorReporterRef.instance = instance
}

/** 全局错误上报入口（Vue errorHandler / 业务 catch 均可调用） */
export function captureAppError(
  source: ErrorSource,
  errorCode: string,
  message: string,
  stack?: string,
  extra?: Record<string, unknown>,
): void {
  errorReporterRef.instance?.capture(source, errorCode, message, stack, extra)
}

/** 用户主动手动上报（不受自动上报开关/去重/日限额限制） */
export function reportManualFeedback(message: string, extra?: Record<string, unknown>): void {
  errorReporterRef.instance?.captureManual(message, extra)
}

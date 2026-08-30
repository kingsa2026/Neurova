/**
 * 统一事件总线 - 基于 mitt 接口的轻量实现
 *
 * 所有跨组件通信通过此总线，禁止 props 逐层传递超过 2 层。
 *
 * 事件命名规范: `domain:action`（如 `memory:created`、`user:login`）
 */

export type EventHandler<T = unknown> = (payload: T) => void

export type EventMap = Record<string, unknown>

export interface Emitter<Events extends EventMap> {
  on<Key extends keyof Events>(type: Key, handler: EventHandler<Events[Key]>): void
  on(type: '*', handler: EventHandler<unknown>): void
  off<Key extends keyof Events>(type: Key, handler?: EventHandler<Events[Key]>): void
  off(type: '*', handler?: EventHandler<unknown>): void
  emit<Key extends keyof Events>(type: Key, event: Events[Key]): void
  emit(type: '*', event: unknown): void
  clear(): void
}

/**
 * 创建事件发射器（mitt 兼容接口）
 *
 * @param events 初始事件映射（可选）
 */
export function mitt<Events extends EventMap>(events?: Map<keyof Events | '*', EventHandler[]>): Emitter<Events> {
  const handlers = events ?? new Map<keyof Events | '*', EventHandler[]>()

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const emitter: any = {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    on(type: any, handler: any): void {
      const list = handlers.get(type) ?? []
      list.push(handler)
      handlers.set(type, list)
    },

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    off(type: any, handler?: any): void {
      if (handler === undefined) {
        handlers.delete(type)
        return
      }
      const list = handlers.get(type)
      if (list) {
        const idx = list.indexOf(handler)
        if (idx >= 0) list.splice(idx, 1)
        if (list.length === 0) handlers.delete(type)
      }
    },

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    emit(type: any, event: any): void {
      // 触发特定事件
      const list = handlers.get(type)
      if (list) {
        for (const handler of [...list]) {
          handler(event)
        }
      }
      // 触发通配符事件
      const starList = handlers.get('*')
      if (starList) {
        for (const handler of [...starList]) {
          handler(event)
        }
      }
    },

    clear(): void {
      handlers.clear()
    },
  }

  return emitter as Emitter<Events>
}

// ────── 应用事件类型定义 ──────

export type AppEvents = {
  // 记忆事件
  'memory:created': { memoryId: string; content: string }
  'memory:archived': { memoryId: string }
  // 用户事件
  'user:login': { userId: string }
  'user:logout': void
  // 通知事件
  'notification:show': { type: 'success' | 'error' | 'warning' | 'info'; message: string }
  // API 事件
  'api:rate-limited': { requestId: string; retryAfter?: number; message?: string }
  // 聊天会话事件(#2 / ADR 0008:useChat composable 发射)
  'chat:session-created': { sessionId: string; agentId: string }
  'chat:session-switched': { sessionId: string }
  'chat:session-deleted': { sessionId: string }
  'chat:session-renamed': { sessionId: string; title: string }
  // 会话存档（删除 → 存档：历史列表隐藏，存档卡片页可随时恢复）
  'chat:session-archived': { sessionId: string }
  'chat:session-restored': { sessionId: string }
}

// ────── 全局事件总线单例 ──────

export const bus: Emitter<AppEvents> = mitt<AppEvents>()

export default bus

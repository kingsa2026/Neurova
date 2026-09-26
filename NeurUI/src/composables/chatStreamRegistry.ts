/**
 * 聊天流所有权登记表：一轮 SSE 流的可中止权唯一收口在此。
 *
 * 现场故障（2026-09-26）：ChatPage 的 onBeforeUnmount 直接 abortController.abort()，
 * 把一轮仍在后台跑、后端已备好 replay 缓冲与落库的推理从显示侧掐死，回页面后
 * 既不重连也不重载，气泡永远停在半截。根因是流的生命周期被绑在组件生命周期上。
 * 这里把"可以中止"限定为三种显式用户意图；脱离视图（切页/关组件）不在其列。
 */
export type ChatStreamAbortReason = 'userStopped' | 'switchedSession' | 'switchedAgent'

export interface ClaimedChatStream {
  sessionId: string
  roundKey: string
  controller: AbortController
  viewBound: boolean
}

export interface ClaimDescriptor {
  sessionId: string
  roundKey: string
  controller: AbortController
}

export type ChatStreamSettledListener = (sessionId: string, outcome: { aborted: boolean }) => void

/** 可中止理由的白名单——新增理由必须同时带来"用户真的要求停止"的语义。 */
const ABORT_REASONS: ReadonlySet<string> = new Set(['userStopped', 'switchedSession', 'switchedAgent'])

const activeStreams = new Map<string, ClaimedChatStream>()
const settledListeners: ChatStreamSettledListener[] = []

function notifySettled(sessionId: string, aborted: boolean): void {
  for (const listener of [...settledListeners]) listener(sessionId, { aborted })
}

export function claimChatStream(descriptor: ClaimDescriptor): ClaimedChatStream | null {
  const { sessionId, roundKey, controller } = descriptor
  if (!sessionId || !controller || activeStreams.has(sessionId)) return null
  const stream: ClaimedChatStream = { sessionId, roundKey, controller, viewBound: true }
  activeStreams.set(sessionId, stream)
  return stream
}

export function currentChatStream(sessionId?: string): ClaimedChatStream | null {
  if (sessionId) return activeStreams.get(sessionId) ?? null
  const first = activeStreams.values().next()
  return first.done ? null : first.value
}

export function attachChatStreamView(sessionId: string): ClaimedChatStream | null {
  const stream = activeStreams.get(sessionId)
  if (!stream) return null
  stream.viewBound = true
  return stream
}

export function detachChatStreamView(sessionId: string): void {
  const stream = activeStreams.get(sessionId)
  if (stream) stream.viewBound = false
}

export function abortChatStream(sessionId: string, reason: ChatStreamAbortReason): boolean {
  if (!ABORT_REASONS.has(reason)) return false
  const stream = activeStreams.get(sessionId)
  if (!stream) return false
  activeStreams.delete(sessionId)
  stream.controller.abort()
  notifySettled(sessionId, true)
  return true
}

export function releaseChatStream(sessionId: string): void {
  if (!activeStreams.delete(sessionId)) return
  notifySettled(sessionId, false)
}

export function onChatStreamSettled(listener: ChatStreamSettledListener): () => void {
  settledListeners.push(listener)
  return () => {
    const at = settledListeners.indexOf(listener)
    if (at >= 0) settledListeners.splice(at, 1)
  }
}

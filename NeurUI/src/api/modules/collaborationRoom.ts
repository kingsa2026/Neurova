/**
 * collaborationRoom.ts — 协作群聊房间的前端数据层。
 *
 * - REST：房间元信息 / 历史消息 / 发言（对应后端 collaboration_room_api）。
 * - applyRoomEvent：把 session-sync 实时事件（user_message/agent_stream_chunk/
 *   agent_reply/agent_error）纯函数式投影为房间消息列表（流式合并/定稿/去重）。
 */
import api from '@/api'
import { buildStepsFromHistory, type ChatStep } from '@/utils/chatSteps'

const BASE = '/collaboration'

export interface RoomMember {
  id: string
  name: string
}

export interface RoomInfo {
  id: string
  name: string
  description: string
  owner: string
  members: RoomMember[]
  responder_agent_id: string
}

export interface RoomMessage {
  id: string
  sender_type: 'user' | 'agent' | 'system'
  sender_id: string
  content: string
  streaming?: boolean
  kind?: 'message' | 'error'
  /** 助手回应附带的工具/推理步骤（与 ChatPage 同源契约，供 MessageSteps 渲染）。 */
  steps?: ChatStep[]
}

/** 后端历史行（RoomStore.history 形状）。 */
interface RawRoomMessage {
  sender_type: string
  sender_id: string
  role: string
  content: string
  ts?: number | string
  meta?: Record<string, unknown>
}

/** session-sync WS 事件帧（与 useSessionSync.SessionSyncEvent 对齐）。 */
export interface RoomEvent {
  event_id: string
  event_type: string
  session_id: string
  source_channel: string
  timestamp: string
  payload: Record<string, unknown>
  seq?: number
}

function unwrap<T>(res: unknown): T {
  return ((res as any)?.data ?? res) as T
}

export async function getRoom(roomId: string): Promise<RoomInfo> {
  const res = await api.get(`${BASE}/rooms/${encodeURIComponent(roomId)}`)
  return unwrap<RoomInfo>(res)
}

/** 归一后的工具段（buildStepsFromHistory 消费形状）。 */
interface NormalizedToolCall {
  name: string
  arguments: string
  result?: string
}

function safeStringify(v: unknown): string {
  if (v == null) return ''
  return typeof v === 'string' ? v : JSON.stringify(v)
}

/**
 * 把管线落盘/广播的原始 tool_messages（内部形态 tool_name/params/result 与
 * 原生 OpenAI 形态 data.function.*）归一为 {name, arguments, result} 列表，
 * 按 tool_name 合并 tool_call 与 tool_result。契约与 useChat 历史回放一致。
 */
export function normalizeToolMessages(msgs: unknown): NormalizedToolCall[] {
  if (!Array.isArray(msgs)) return []
  const byName = new Map<string, NormalizedToolCall>()
  for (const tm of msgs) {
    if (!tm || typeof tm !== 'object') continue
    const m = tm as Record<string, any>
    const name = String(m.tool_name ?? m.name ?? m.data?.function?.name ?? '')
    if (!name) continue
    let entry = byName.get(name)
    if (!entry) {
      entry = { name, arguments: '' }
      byName.set(name, entry)
    }
    if (m.type === 'tool_call' || m.params !== undefined || m.data?.function?.arguments !== undefined) {
      entry.arguments = safeStringify(m.params ?? m.arguments ?? m.data?.function?.arguments) || entry.arguments
    }
    if (m.type === 'tool_result' || m.result !== undefined) {
      entry.result = typeof m.result === 'string' ? m.result : safeStringify(m.result ?? m.data?.content)
    }
  }
  return [...byName.values()]
}

/** 从一行历史 meta 重建步骤（无工具/推理时返回空数组）。 */
function stepsFromMeta(meta: Record<string, unknown> | undefined): ChatStep[] {
  const md = meta || {}
  const reasoning = md.reasoning_content ? String(md.reasoning_content) : undefined
  return buildStepsFromHistory(reasoning, normalizeToolMessages(md.tool_calls))
}

export async function getRoomMessages(roomId: string, limit = 200): Promise<RoomMessage[]> {
  const res = await api.get(`${BASE}/rooms/${encodeURIComponent(roomId)}/messages`, { params: { limit } })
  const rows = unwrap<RawRoomMessage[]>(res) || []
  return rows.map((r, i) => {
    const steps = stepsFromMeta(r.meta)
    return {
      id: `h${i}-${r.ts ?? ''}`,
      sender_type: (r.sender_type as RoomMessage['sender_type']) || (r.role === 'user' ? 'user' : 'agent'),
      sender_id: r.sender_id || '',
      content: r.content || '',
      steps: steps.length ? steps : undefined,
    }
  })
}

export async function postRoomMessage(roomId: string, text: string): Promise<void> {
  await api.post(`${BASE}/rooms/${encodeURIComponent(roomId)}/messages`, { text })
}

export interface UpdateRoomPayload {
  name?: string
  description?: string
  members?: string[]
  responder_agent_id?: string
}

export async function updateRoom(roomId: string, payload: UpdateRoomPayload): Promise<void> {
  await api.put(`${BASE}/rooms/${encodeURIComponent(roomId)}`, payload)
}

/**
 * 纯函数：把一个实时事件投影进消息列表，返回新数组（不可变，便于 Vue 响应式）。
 * 规则见 collaborationRoom.test.ts。
 */
export function applyRoomEvent(messages: RoomMessage[], event: RoomEvent): RoomMessage[] {
  const p = event.payload || {}
  const senderId = String(p.sender_id ?? '')
  const type = event.event_type

  if (type === 'user_message') {
    const content = String(p.content ?? '')
    const dup = messages.some(
      (m) => m.sender_type === 'user' && m.sender_id === senderId && m.content === content,
    )
    if (dup) return messages
    return [...messages, { id: event.event_id, sender_type: 'user', sender_id: senderId, content }]
  }

  if (type === 'agent_stream_chunk') {
    const data = String(p.data ?? '')
    const idx = findLastStreamingIndex(messages, senderId)
    if (idx >= 0) {
      const next = messages.slice()
      next[idx] = { ...next[idx], content: next[idx].content + data }
      return next
    }
    return [
      ...messages,
      { id: event.event_id, sender_type: 'agent', sender_id: senderId, content: data, streaming: true },
    ]
  }

  if (type === 'agent_reply') {
    const content = String(p.content ?? '')
    const reasoning = p.reasoning ? String(p.reasoning) : undefined
    const steps = buildStepsFromHistory(reasoning, normalizeToolMessages(p.tool_messages))
    const idx = findLastStreamingIndex(messages, senderId)
    // 幂等合并：GET 历史 / pipeline 与 router 两条 AGENT_REPLY（同内容、sender 可能不一）
    // 归并为一条——按内容定位定稿气泡，补全缺失的 sender_id 与 steps。
    const finalIdx = messages.findIndex(
      (m) => m.sender_type === 'agent' && m.content === content && !m.streaming,
    )
    if (finalIdx >= 0) {
      const existing = messages[finalIdx]
      const mergedSender = existing.sender_id || senderId
      const mergedSteps = existing.steps && existing.steps.length ? existing.steps : steps
      const dirty = mergedSender !== existing.sender_id || (!!mergedSteps.length && !existing.steps?.length)
      const next = dirty
        ? messages.map((m, i) => (i === finalIdx ? { ...m, sender_id: mergedSender, steps: mergedSteps } : m))
        : messages.slice()
      // 若同时残留一条流式缓冲（重放产物）且非本条 → 丢弃之
      if (idx >= 0 && idx !== finalIdx) return next.filter((_, i) => i !== idx)
      return next
    }
    if (idx >= 0) {
      const next = messages.slice()
      next[idx] = { ...next[idx], content, streaming: false, steps: steps.length ? steps : next[idx].steps }
      return next
    }
    return [
      ...messages,
      { id: event.event_id, sender_type: 'agent', sender_id: senderId, content, steps: steps.length ? steps : undefined },
    ]
  }

  if (type === 'agent_error') {
    return [
      ...messages,
      { id: event.event_id, sender_type: 'system', sender_id: senderId, content: String(p.content ?? ''), kind: 'error' },
    ]
  }

  return messages
}

function findLastStreamingIndex(messages: RoomMessage[], senderId: string): number {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i]
    if (m.sender_type === 'agent' && m.sender_id === senderId && m.streaming) return i
  }
  return -1
}

// ── @ 提及辅助（纯函数，供房间输入框使用）─────────────────────
export interface MentionContext {
  query: string
  start: number
}

/** 根据光标前文本判断是否处于 @提及中；返回 partial 与 @ 的位置，否则 null。 */
export function computeMentionQuery(text: string, caret: number): MentionContext | null {
  const upto = text.slice(0, caret)
  const at = upto.lastIndexOf('@')
  if (at < 0) return null
  // @ 需在行首或前接空白（避免 email 式 a@b 误触发）
  if (at > 0 && !/\s/.test(upto[at - 1])) return null
  const partial = upto.slice(at + 1)
  if (/\s/.test(partial)) return null // 提及已随空格结束
  return { query: partial, start: at }
}

/** 把 [start, caret) 的 @partial 替换为 @name （尾随空格）。 */
export function applyMention(text: string, start: number, caret: number, name: string): string {
  return `${text.slice(0, start)}@${name} ${text.slice(caret)}`
}

/** 按名称/ id 前缀不区分大小写过滤成员；空 query 返回全部。 */
export function filterMembers(members: RoomMember[], query: string): RoomMember[] {
  const q = query.toLowerCase()
  if (!q) return members
  return members.filter(
    (m) => (m.name || '').toLowerCase().startsWith(q) || (m.id || '').toLowerCase().startsWith(q),
  )
}

/**
 * 会话时间线重放（Issue #262）。
 *
 * 后端 `GET /console/chat/sessions/{sid}/timeline` 把 SSE 事件以 append-only
 * JSONL 落盘（`session_manager.append_timeline_event` / `read_timeline`），
 * 端点是只读重放面：断线重连补课与审计回放都从这一份事实源取数。
 *
 * 本模块是该事实源在浏览器侧的唯一消费点，把「事件序列」归一为
 * 「聊天消息视图」——与 ChatPage.processSSEEvent 的实时形态同构：
 * 推理/工具按到达顺序成段、正文累积为 content、终止事件切轮。
 *
 * ## 双写形态与「事件族」口径（实跑取证）
 *
 * 后端落盘写的是 **两条并行流**：
 *   1. 旧事件流（`chunk` / `reasoning` / `tool_call` / `tool_result` / `done`…）
 *      —— 兼容别名，前端实时渲染的主通道；
 *   2. item 事件流（`item_started` / `item_delta` / `item_completed`）
 *      —— `ItemEventMapper` 由同一批旧事件状态机派生（`sse_items.py`）。
 *
 * 两条流承载**同一轮**的同一份内容（实测：一次 5 事件的对话落盘 11 行）。
 * 若把两者当独立事件吞进同一个轮，正文会成倍重影。故本模块按「事件族」
 * 择一消费：
 *   - 同一轮内先出现 item_* 就锁定 item 族，其后旧事件不再并入（反之亦然）；
 *   - 终止事件（done…）复位，下一轮重新判定。
 * 这与旧实现的 `hasInternalForm` 归一（useChat.switchSession 里
 * 「同一轮两种形态并存 → 内部形态优先」）同向，只是那一处按消息形态、
 * 此处按事件族——两条历史的归一原则必须一致，否则回放与实时显示不一致。
 *
 * 纯函数，无 IO：可单测、可重放、可复用（历史回放 vs 断线补课）。
 */
import type { ChatMessage } from '@/types/chat'
import {
  appendReasoningStep,
  appendToolStep,
  attachToolResult,
  finishAllSteps,
  type ChatStep,
} from '@/utils/chatSteps'

/** 时间线单条事件（后端逐行 JSON 的原样形态）。 */
export type TimelineEventPayload = Record<string, unknown>

/** 旧事件流的收口事件（与后端 sse_items._TERMINAL_TYPES 同集）。 */
const LEGACY_TERMINAL_EVENT_TYPES = new Set(['done', 'complete', 'stopped', 'error'])

/**
 * item 事件流的收口事件。
 *
 * 两族各认自己的收口事件——理由是后端写路径的两人份语义不同：
 *   - 旧流以 `done` 收口整轮（flush 阶段 `flush_events + flush_item_events
 *     + [done]`，故 `done` 恒在整轮**末尾**）；
 *   - item 族以**末条** `item_completed` 收口（该族的 done 对应物只闭 item，
 *     不闭轮——中途的 tool_result 也是 item_completed）。
 * 若让 `done` 为两族共用边界，旧流事件分两批到达时（流式批 + flush 批）
 * 会被误切成两轮；故 item 族的轮边界只认「末尾」这条，
 * 由 `agentMessagesFromTimeline` 在流结束时统一收口。
 */
const ITEM_TERMINAL_EVENT_TYPES = new Set(['item_completed'])

/** 归一为「正文文本」的事件类型（含 item 别名）。 */
const CONTENT_EVENT_TYPES = new Set(['chunk', 'message', 'delta'])

/** 归一为「推理文本」的事件类型。 */
const REASONING_EVENT_TYPES = new Set(['reasoning', 'thinking'])

/**
 * 判定一行反序列化结果是否为可用事件。
 *
 * 后端 read_timeline 已跳过坏行与空行，但网络/拼装层仍可能送来
 * 非对象或空 type——本判定是消费侧的诚实闸口：不合法即跳过，
 * 不猜、不补默认值。
 */
export function isTimelineEventPayload(value: unknown): value is TimelineEventPayload {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false
  const type = (value as { type?: unknown }).type
  return typeof type === 'string' && type.length > 0
}

function textOf(event: TimelineEventPayload): string {
  const candidate = event.content ?? event.text ?? event.delta
  return typeof candidate === 'string' ? candidate : ''
}

/** item_* 事件取 data.text（SSE item 化的等价别名形态）。 */
function itemTextOf(event: TimelineEventPayload): string {
  const data = event.data
  if (data === null || typeof data !== 'object' || Array.isArray(data)) return ''
  const text = (data as { text?: unknown }).text
  return typeof text === 'string' ? text : ''
}

function itemEventType(event: TimelineEventPayload, expected: string): boolean {
  return String(event.item_type || '') === expected && String(event.type || '').startsWith('item_')
}

function toolText(value: unknown): string {
  if (typeof value === 'string') return value
  if (value === undefined || value === null) return ''
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

/** 一轮重放中间态：一条 assistant 消息的形状逐步补全。 */
interface ReplayRound {
  content: string
  reasoning: string
  toolCalls: NonNullable<ChatMessage['toolCalls']>
  steps: ChatStep[]
}

function emptyRound(): ReplayRound {
  return { content: '', reasoning: '', toolCalls: [], steps: [] }
}

function roundHasContent(round: ReplayRound): boolean {
  return Boolean(round.content || round.reasoning || round.toolCalls.length || round.steps.length)
}

function roundToMessage(round: ReplayRound): ChatMessage {
  return {
    role: 'assistant',
    content: round.content,
    reasoning: round.reasoning || undefined,
    // 重放出来的历史默认收起（与 useChat.switchSession 历史回放同口径）
    reasoningOpen: false,
    steps: round.steps.length > 0 ? round.steps : undefined,
    toolCalls: round.toolCalls.length > 0 ? round.toolCalls : undefined,
  }
}

/**
 * 事件族判定：`item` 为 ItemEventMapper 派生的 item 事件流，`legacy` 为旧事件流。
 *
 * 瞬态/记账类事件（usage / memory_progress / retry / artifact …）不属于任一族
 * ——它们没有 item 对应物，也不参与正文归一，返回 null 即「与族无关」。
 */
function eventFamily(event: TimelineEventPayload): 'item' | 'legacy' | null {
  const type = String(event.type)
  if (type.startsWith('item_')) return 'item'
  if (
    CONTENT_EVENT_TYPES.has(type) ||
    REASONING_EVENT_TYPES.has(type) ||
    type === 'tool_call' ||
    type === 'tool_result'
  ) {
    return 'legacy'
  }
  return null
}

/** 把单条事件并入当前轮；返回是否「消耗了该事件」（用于轮边界判定）。 */
function absorbEvent(round: ReplayRound, event: TimelineEventPayload): void {
  const type = String(event.type)

  if (CONTENT_EVENT_TYPES.has(type)) {
    const text = textOf(event)
    if (text) {
      if (round.steps.some((s) => s.active)) finishAllSteps(round.steps)
      round.content += text
    }
    return
  }

  if (itemEventType(event, 'agent_message')) {
    const text = itemTextOf(event)
    if (text) {
      if (round.steps.some((s) => s.active)) finishAllSteps(round.steps)
      round.content += text
    }
    return
  }

  if (REASONING_EVENT_TYPES.has(type) || itemEventType(event, 'reasoning')) {
    const text = itemEventType(event, 'reasoning') ? itemTextOf(event) : textOf(event)
    if (text) {
      round.reasoning += text
      appendReasoningStep(round.steps, text)
    }
    return
  }

  if (type === 'tool_call') {
    const name = String(event.name || event.tool_name || 'unknown')
    const args = typeof event.arguments === 'string' ? event.arguments : toolText(event.arguments ?? {})
    round.toolCalls.push({ name, arguments: args })
    appendToolStep(round.steps, name, args, event.task_name ? String(event.task_name) : undefined)
    return
  }

  if (type === 'tool_result') {
    const name = String(event.name || event.tool_name || '')
    const result = toolText(event.result)
    const last = round.toolCalls[round.toolCalls.length - 1]
    if (last) last.result = result
    attachToolResult(round.steps, result, event.task_name ? String(event.task_name) : undefined, name || undefined)
  }
}

/**
 * 事件序列 → 逐轮 assistant 消息。
 *
 * 轮边界 = 终止事件（done/complete/stopped/error）。没有终止事件时不抛错：
 * 未收口的尾轮也返回（断线场景下它就是「已落盘的部分」），
 * 由调用方决定是续写还是另起。
 */
export function agentMessagesFromTimeline(events: unknown): ChatMessage[] {
  if (!Array.isArray(events)) return []
  const rounds: ChatMessage[] = []
  let current = emptyRound()
  // 本轮已锁定的事件族；null = 尚未出现任一族的首个事件
  let family: 'item' | 'legacy' | null = null

  const closeRound = (): void => {
    if (roundHasContent(current)) {
      finishAllSteps(current.steps)
      rounds.push(roundToMessage(current))
    }
    current = emptyRound()
    family = null
  }

  /** 该类型是否收口「已锁定的族」（未锁定族时不构成轮边界）。 */
  const closesLockedFamily = (type: string): boolean => {
    if (family === 'legacy') return LEGACY_TERMINAL_EVENT_TYPES.has(type)
    if (family === 'item') return ITEM_TERMINAL_EVENT_TYPES.has(type)
    return false
  }

  for (const raw of events) {
    if (!isTimelineEventPayload(raw)) continue
    const type = String(raw.type)
    const rawFamily = eventFamily(raw)
    // 非终止、且不属于任何一族的瞬态事件：与正文归一无关，直接跳过
    if (rawFamily === null && !LEGACY_TERMINAL_EVENT_TYPES.has(type)) continue

    // 轮边界只认「已锁定族的收口事件」：另一族的 done 落在本族事件之间时
    // 不得误切（实测落盘顺序正是 legacy 的 done 在 item 族之前）。
    if (closesLockedFamily(type)) {
      closeRound()
      continue
    }
    if (rawFamily === null) continue
    if (family === null) {
      family = rawFamily
    } else if (family !== rawFamily) {
      // 两条流承载同一轮同一份内容：先到者为准，后来的整族丢弃（不重影）
      continue
    }
    absorbEvent(current, raw)
  }

  closeRound()
  return rounds
}

export interface ReplayTimelineOptions {
  /**
   * 已渲染的轮数，直接从该轮之后开始补——断线重连的「快进」语义：
   * 已确认消费的增量不再回放（与 ChatPage 的 replay_from 语义同向）。
   */
  skipRounds?: number
  /**
   * 是否把尾部未收口的一轮续写到既有消息上（同一轮中途断线）。
   *
   * 前提：既有末条 assistant 消息的正文必须正是时间线的**前缀**——
   * 本函数据此只补差量（`content.slice(tail.content.length)`）。
   * 前缀不匹配（本地被编辑过 / 位点记错）时返回空、不改动既有消息：
   * 断线补课宁可少补，也不制造正文重影。
   */
  continueTail?: boolean
}

/**
 * 断线补课：把时间线里「尚未渲染」的部分并入既有消息列表，返回新增的消息。
 *
 * 不修改传入数组本身（只 push 到局部副本），副作用只有 continueTail 下
 * 对既有末条消息的原地续写——调用方不必关心数组引用。
 */
export function replayTimelineInto(
  messages: ChatMessage[],
  events: unknown,
  options: ReplayTimelineOptions = {},
): ChatMessage[] {
  const skipRounds = Math.max(0, Math.trunc(options.skipRounds ?? 0))
  const rounds = agentMessagesFromTimeline(events)
  if (rounds.length <= skipRounds) return []

  const pending = rounds.slice(skipRounds)
  const tail = messages.length > 0 ? messages[messages.length - 1] : undefined

  if (options.continueTail && tail && tail.role === 'assistant') {
    const [head, ...rest] = pending
    if (head && head.content.startsWith(tail.content || '')) {
      const delta = head.content.slice((tail.content || '').length)
      if (delta) tail.content = (tail.content || '') + delta
    }
    return rest
  }

  return pending
}

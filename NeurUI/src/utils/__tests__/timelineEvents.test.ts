/**
 * 会话时间线重放（GET /console/chat/sessions/{sid}/timeline）契约测试 —— 红灯切片。
 *
 * 背景（Issue #262）：后端 `neurova/api/endpoints/console.py` 的 timeline 端点
 * 已建，NeurUI 侧零消费者——SSE 落盘的 append-only JSONL 无人读取，
 * 断线重连/审计回放这条链路在浏览器端是断的。
 *
 * 本文件钉「读回来的事件 → 聊天消息视图」的归一契约：纯函数，无 IO。
 * 红灯阶段先断言语义，实现文件尚不存在（import 直接失败）。
 */
import { describe, it, expect } from 'vitest'
import {
  agentMessagesFromTimeline,
  isTimelineEventPayload,
  replayTimelineInto,
} from '@/utils/timelineEvents'
import type { ChatMessage } from '@/types/chat'

const ts = (i: number) => `2026-09-26T06:1${i}:00Z`

function chunk(content: string, i = 0) {
  return { type: 'chunk', content }
}

function reasoning(content: string) {
  return { type: 'reasoning', content }
}

function toolCall(name: string, args = '{}') {
  return { type: 'tool_call', name, arguments: args }
}

function toolResult(name: string, result: string) {
  return { type: 'tool_result', name, result }
}

describe('isTimelineEventPayload', () => {
  it('接受带 type 的字符串键对象', () => {
    expect(isTimelineEventPayload({ type: 'chunk', content: 'a' })).toBe(true)
  })

  it('拒绝 null / 非对象 / 缺 type / type 非字符串', () => {
    expect(isTimelineEventPayload(null)).toBe(false)
    expect(isTimelineEventPayload('chunk')).toBe(false)
    expect(isTimelineEventPayload([])).toBe(false)
    expect(isTimelineEventPayload({ content: 'a' })).toBe(false)
    expect(isTimelineEventPayload({ type: 3 })).toBe(false)
    expect(isTimelineEventPayload({ type: '' })).toBe(false)
  })
})

describe('agentMessagesFromTimeline — 轮切分', () => {
  it('user + 一段 chunk 序列 = 一轮（1 条 assistant 消息）', () => {
    const events = [chunk('你'), chunk('好')]
    const rounds = agentMessagesFromTimeline(events)
    expect(rounds).toHaveLength(1)
    expect(rounds[0].content).toBe('你好')
  })

  it('done 事件切轮：两段 chunk 各自成轮', () => {
    const events = [
      chunk('第一轮'),
      { type: 'done', session_id: 's1' },
      chunk('第二轮'),
      { type: 'done', session_id: 's1' },
    ]
    const rounds = agentMessagesFromTimeline(events)
    expect(rounds.map((r) => r.content)).toEqual(['第一轮', '第二轮'])
  })

  it('stopped / error 同样收口当前轮', () => {
    const stopped = agentMessagesFromTimeline([chunk('半截'), { type: 'stopped' }, chunk('新的')])
    expect(stopped.map((r) => r.content)).toEqual(['半截', '新的'])
    const errored = agentMessagesFromTimeline([chunk('半截'), { type: 'error', message: 'x' }])
    expect(errored).toHaveLength(1)
  })

  it('空事件 / 全空 chunk 返回空数组（不造幽灵轮）', () => {
    expect(agentMessagesFromTimeline([])).toEqual([])
    expect(agentMessagesFromTimeline([chunk(''), { type: 'done' }])).toEqual([])
    expect(agentMessagesFromTimeline([{ type: 'usage', total_tokens: 3 }])).toEqual([])
  })
})

describe('agentMessagesFromTimeline — 内容还原', () => {
  it('chunk 累积为 content，reasoning 累积为 reasoning', () => {
    const rounds = agentMessagesFromTimeline([reasoning('想一下'), chunk('答案')])
    expect(rounds[0].reasoning).toBe('想一下')
    expect(rounds[0].content).toBe('答案')
  })

  it('item_started/item_delta 是 chunk 的等价别名（不重复计数）', () => {
    const rounds = agentMessagesFromTimeline([
      { type: 'item_started', item_type: 'agent_message', item_id: 'i1', data: { text: '甲' } },
      { type: 'item_delta', item_type: 'agent_message', item_id: 'i1', data: { text: '乙' } },
    ])
    expect(rounds[0].content).toBe('甲乙')
  })

  it('tool_call/tool_result 还原为 toolCalls + 时间轴工具段', () => {
    const rounds = agentMessagesFromTimeline([
      chunk('看下'),
      toolCall('read_file', '{"path":"a.py"}'),
      toolResult('read_file', 'print(1)'),
    ])
    const [round] = rounds
    expect(round.toolCalls).toHaveLength(1)
    expect(round.toolCalls![0].name).toBe('read_file')
    expect(round.toolCalls![0].result).toBe('print(1)')
    expect(round.steps!.some((s) => s.kind === 'tool')).toBe(true)
  })

  it('usage 等瞬态事件不进正文', () => {
    const rounds = agentMessagesFromTimeline([
      chunk('hi'),
      { type: 'usage', total_tokens: 10 },
      { type: 'memory_progress', stage: 'retriever_start' },
    ])
    expect(rounds[0].content).toBe('hi')
  })

  it('坏事件（非对象 / 未知 type）被跳过而不是抛错', () => {
    const rounds = agentMessagesFromTimeline([
      chunk('a'),
      null as unknown as Record<string, unknown>,
      { type: 'future_unknown_kind' },
      chunk('b'),
    ])
    expect(rounds[0].content).toBe('ab')
  })
})

describe('双写形态归族：同一轮不得重影', () => {
  // 实测落盘形状（真后端 TestClient 跑出，顺序逐字段照抄）：
  // console.py 每批写的是 `_record_timeline(旧流 + 其派生 item 流)`，
  // 故各条旧事件**紧邻**其 item 对应物；done 在整轮末尾统一收口
  // （flush 阶段：`flush_events + flush_item_events + [_flush_done]`）。
  const doubleWrittenRound = [
    { type: 'reasoning', content: '先看文件' },
    { type: 'item_started', item_type: 'reasoning', item_id: 'i1', data: { text: '先看文件' } },
    { type: 'chunk', content: '答案' },
    { type: 'item_started', item_type: 'agent_message', item_id: 'i2', data: { text: '答案' } },
    { type: 'tool_call', name: 'read_file', arguments: '{"path":"a.py"}' },
    { type: 'item_started', item_type: 'tool_call', item_id: 'i3', data: { name: 'read_file', arguments: '{"path":"a.py"}' } },
    { type: 'tool_result', name: 'read_file', result: 'print(1)' },
    { type: 'item_completed', item_type: 'tool_result', item_id: 'i4', data: { name: 'read_file', result: 'print(1)' } },
    { type: 'item_completed', item_type: 'agent_message', item_id: 'i2', data: {} },
    { type: 'item_completed', item_type: 'reasoning', item_id: 'i1', data: {} },
    { type: 'done', session_id: 's1' },
  ]

  it('同一轮双写只产出一轮（先到族为准）', () => {
    const rounds = agentMessagesFromTimeline(doubleWrittenRound)
    expect(rounds).toHaveLength(1)
  })

  it('正文不因双写而重影', () => {
    const rounds = agentMessagesFromTimeline(doubleWrittenRound)
    expect(rounds[0].content).toBe('答案')
    expect(rounds[0].reasoning).toBe('先看文件')
    expect(rounds[0].toolCalls).toHaveLength(1)
  })

  it('只有 item 族（旧流被裁掉）时同样只产出一轮', () => {
    const onlyItems = doubleWrittenRound.filter((e) => String(e.type).startsWith('item_'))
    const rounds = agentMessagesFromTimeline(onlyItems)
    expect(rounds).toHaveLength(1)
    expect(rounds[0].content).toBe('答案')
  })

  it('两轮双写 → 两轮（不得把第二轮并进第一轮）', () => {
    const rounds = agentMessagesFromTimeline([
      ...doubleWrittenRound,
      { type: 'reasoning', content: '第二轮想' },
      { type: 'item_started', item_type: 'reasoning', item_id: 'j1', data: { text: '第二轮想' } },
      { type: 'chunk', content: '第二轮答' },
      { type: 'item_started', item_type: 'agent_message', item_id: 'j2', data: { text: '第二轮答' } },
      { type: 'item_completed', item_type: 'agent_message', item_id: 'j2', data: {} },
      { type: 'done' },
    ])
    expect(rounds).toHaveLength(2)
    expect(rounds[1].content).toBe('第二轮答')
    expect(rounds[1].reasoning).toBe('第二轮想')
  })
})

describe('replayTimelineInto — 断线重连快进', () => {
  it('已渲染部分不重复追加（skipRounds 快进）', () => {
    const msg: ChatMessage = { role: 'assistant', content: '第一轮', steps: [] }
    const events = [chunk('第一轮'), { type: 'done' }, chunk('第二轮'), { type: 'done' }]
    const added = replayTimelineInto([msg], events, { skipRounds: 1 })
    expect(added).toHaveLength(1)
    expect(added[0].content).toBe('第二轮')
  })

  it('continueTail 只补差量（既有正文是时间线前缀）', () => {
    // 断线场景：本地已渲染「甲乙」，时间线里完整形状是「甲乙丙」。
    const msg: ChatMessage = { role: 'assistant', content: '甲乙', steps: [] }
    const events = [chunk('甲'), chunk('乙'), chunk('丙')]
    const added = replayTimelineInto([msg], events, { skipRounds: 0, continueTail: true })
    expect(msg.content).toBe('甲乙丙')
    expect(added).toHaveLength(0)
  })

  it('continueTail 且已补齐时不改动既有消息、不重复追加', () => {
    const msg: ChatMessage = { role: 'assistant', content: '甲乙', steps: [] }
    const added = replayTimelineInto([msg], [chunk('甲'), chunk('乙')], {
      skipRounds: 0,
      continueTail: true,
    })
    expect(msg.content).toBe('甲乙')
    expect(added).toHaveLength(0)
  })

  it('continueTail 前缀不匹配时不改动既有消息（不制造重影）', () => {
    const msg: ChatMessage = { role: 'assistant', content: '已被用户编辑', steps: [] }
    const added = replayTimelineInto([msg], [chunk('甲乙丙')], {
      skipRounds: 0,
      continueTail: true,
    })
    expect(msg.content).toBe('已被用户编辑')
    expect(added).toHaveLength(0)
  })

  it('skipRounds 超过实际轮数时不越界、不抛错', () => {
    const events = [chunk('a'), { type: 'done' }]
    expect(replayTimelineInto([], events, { skipRounds: 9 })).toEqual([])
  })
})

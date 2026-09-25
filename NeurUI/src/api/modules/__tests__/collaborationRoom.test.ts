/**
 * collaborationRoom 纯逻辑测试：applyRoomEvent 把 session-sync 事件投影为房间消息列表。
 * 覆盖 用户消息追加/去重、Agent 流式 chunk 合并、reply 定稿、error 落气泡。
 */
import { describe, it, expect } from 'vitest'
import {
  applyRoomEvent, computeMentionQuery, applyMention, filterMembers, normalizeToolMessages,
  type RoomMessage, type RoomMember,
} from '../collaborationRoom'

const ev = (event_type: string, payload: Record<string, unknown>, event_id = 'e1') => ({
  event_id,
  event_type,
  session_id: 'project_x',
  source_channel: 'room',
  timestamp: '2026-09-19T00:00:00Z',
  payload,
})

describe('applyRoomEvent', () => {
  it('user_message 追加用户气泡', () => {
    const out = applyRoomEvent([], ev('user_message', { sender_id: 'u1', content: 'hi' }, 'm1'))
    expect(out).toHaveLength(1)
    expect(out[0]).toMatchObject({ sender_type: 'user', sender_id: 'u1', content: 'hi', id: 'm1' })
  })

  it('user_message 按 sender+content 去重（乐观回显不重复）', () => {
    const optimistic: RoomMessage[] = [{ id: 'local', sender_type: 'user', sender_id: 'u1', content: 'hi' }]
    const out = applyRoomEvent(optimistic, ev('user_message', { sender_id: 'u1', content: 'hi' }, 'm2'))
    expect(out).toHaveLength(1)
  })

  it('agent_stream_chunk 累积到同一 sender 的流式气泡', () => {
    let msgs = applyRoomEvent([], ev('agent_stream_chunk', { sender_id: 'a1', data: 'Hel' }, 'c1'))
    msgs = applyRoomEvent(msgs, ev('agent_stream_chunk', { sender_id: 'a1', data: 'lo' }, 'c2'))
    expect(msgs).toHaveLength(1)
    expect(msgs[0]).toMatchObject({ sender_type: 'agent', sender_id: 'a1', content: 'Hello', streaming: true })
  })

  it('agent_reply 定稿流式气泡（无流式则新建）', () => {
    let msgs = applyRoomEvent([], ev('agent_stream_chunk', { sender_id: 'a1', data: 'part' }, 'c1'))
    msgs = applyRoomEvent(msgs, ev('agent_reply', { sender_id: 'a1', content: 'final answer' }, 'r1'))
    expect(msgs).toHaveLength(1)
    expect(msgs[0]).toMatchObject({ sender_type: 'agent', sender_id: 'a1', content: 'final answer', streaming: false })
  })

  it('agent_reply 去重：已存在同内容定稿不重复（GET+WS 重放双源）', () => {
    const fromGet: RoomMessage[] = [{ id: 'h0', sender_type: 'agent', sender_id: 'a1', content: 'answer' }]
    const out = applyRoomEvent(fromGet, ev('agent_reply', { sender_id: 'a1', content: 'answer' }, 'r1'))
    expect(out).toHaveLength(1)
  })

  it('跨源去重：GET(sender=default) + WS(sender="" 同内容) → 1 条', () => {
    // 实机发现：REST 历史与 WS 重放的 sender_id 可能不一致（default vs 空），应按内容去重。
    const msgs: RoomMessage[] = [{ id: 'h0', sender_type: 'agent', sender_id: 'default', content: 'answer' }]
    const out = applyRoomEvent(msgs, ev('agent_reply', { sender_id: '', content: 'answer' }, 'r1'))
    expect(out).toHaveLength(1)
  })

  it('重载：GET 定稿 + WS 重放 chunk→reply 归一为 1 条', () => {
    let msgs: RoomMessage[] = [{ id: 'h0', sender_type: 'agent', sender_id: 'a1', content: 'answer' }]
    msgs = applyRoomEvent(msgs, ev('agent_stream_chunk', { sender_id: 'a1', data: 'ans' }, 'c1'))
    msgs = applyRoomEvent(msgs, ev('agent_stream_chunk', { sender_id: 'a1', data: 'wer' }, 'c2'))
    msgs = applyRoomEvent(msgs, ev('agent_reply', { sender_id: 'a1', content: 'answer' }, 'r1'))
    expect(msgs).toHaveLength(1)
    expect(msgs[0].content).toBe('answer')
    expect(msgs[0].streaming).toBeFalsy()
  })

  it('agent_error 落系统错误气泡', () => {
    const out = applyRoomEvent([], ev('agent_error', { sender_id: 'a1', content: 'boom' }, 'x1'))
    expect(out[0]).toMatchObject({ sender_type: 'system', sender_id: 'a1', content: 'boom', kind: 'error' })
  })

  it('不同 sender 的流式互不串台', () => {
    let msgs = applyRoomEvent([], ev('agent_stream_chunk', { sender_id: 'a1', data: 'A' }, 'c1'))
    msgs = applyRoomEvent(msgs, ev('agent_stream_chunk', { sender_id: 'a2', data: 'B' }, 'c2'))
    expect(msgs).toHaveLength(2)
    expect(msgs.map((m) => m.sender_id)).toEqual(['a1', 'a2'])
  })

  it('agent_reply 携 tool_messages/reasoning → 构建步骤时间轴', () => {
    const out = applyRoomEvent(
      [],
      ev('agent_reply', {
        sender_id: 'a1',
        content: 'done',
        reasoning: 'thinking...',
        tool_messages: [
          { type: 'tool_call', tool_name: 'search', params: { q: 'x' } },
          { type: 'tool_result', tool_name: 'search', result: 'ok' },
        ],
      }, 'r1'),
    )
    expect(out).toHaveLength(1)
    const steps = out[0].steps
    expect(steps && steps.length).toBe(2)
    expect(steps![0]).toMatchObject({ kind: 'reasoning', text: 'thinking...' })
    expect(steps![1]).toMatchObject({ kind: 'tool', name: 'search', result: 'ok' })
  })

  it('合并增强：GET 行（无步骤）+ WS reply（带步骤）→ 仍 1 条且补上步骤', () => {
    const fromGet: RoomMessage[] = [{ id: 'h0', sender_type: 'agent', sender_id: 'default', content: 'answer' }]
    const out = applyRoomEvent(fromGet, ev('agent_reply', {
      sender_id: 'default', content: 'answer',
      tool_messages: [{ type: 'tool_call', tool_name: 't', params: {} }],
    }, 'r1'))
    expect(out).toHaveLength(1)
    expect(out[0].steps && out[0].steps.length).toBe(1)
  })
})

describe('normalizeToolMessages', () => {
  it('内部形态：tool_call 与 tool_result 按名合并', () => {
    const out = normalizeToolMessages([
      { type: 'tool_call', tool_name: 'search', params: { q: 'x' } },
      { type: 'tool_result', tool_name: 'search', result: 'res' },
    ])
    expect(out).toEqual([{ name: 'search', arguments: '{"q":"x"}', result: 'res' }])
  })

  it('OpenAI 形态：data.function.* 与 result 归一', () => {
    const out = normalizeToolMessages([
      { data: { function: { name: 'f', arguments: '{"a":1}' } } },
      { type: 'tool_result', name: 'f', data: { content: 'r' } },
    ])
    expect(out).toEqual([{ name: 'f', arguments: '{"a":1}', result: 'r' }])
  })

  it('非数组/无名称 → 空', () => {
    expect(normalizeToolMessages(undefined)).toEqual([])
    expect(normalizeToolMessages([{ type: 'tool_call' }])).toEqual([])
  })
})

describe('computeMentionQuery / applyMention / filterMembers', () => {
  it('@ 在行首触发，返回空 query', () => {
    expect(computeMentionQuery('@', 1)).toEqual({ query: '', start: 0 })
  })
  it('@ 前有空格触发，带部分 query', () => {
    expect(computeMentionQuery('hi @Neu', 7)).toEqual({ query: 'Neu', start: 3 })
  })
  it('email 式 a@b 不触发（@ 前非空白）', () => {
    expect(computeMentionQuery('a@b', 3)).toBeNull()
  })
  it('无 @ 返回 null', () => {
    expect(computeMentionQuery('hello', 5)).toBeNull()
  })
  it('applyMention 替换 @partial 为 @name ', () => {
    expect(applyMention('hi @Neu', 3, 7, 'Neurova')).toBe('hi @Neurova ')
  })
  it('filterMembers 按名不区分大小写 startsWith', () => {
    const members: RoomMember[] = [{ id: 'default', name: 'Neurova' }, { id: 'kai', name: '凯' }]
    expect(filterMembers(members, 'ne').map((m) => m.id)).toEqual(['default'])
    expect(filterMembers(members, '').length).toBe(2)
    expect(filterMembers(members, 'zzz')).toEqual([])
  })
})

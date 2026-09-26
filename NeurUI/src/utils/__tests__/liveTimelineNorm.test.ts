/**
 * live-verify：真后端落盘的会话时间线 → 前端归一函数。
 *
 * 事件来源：`/tmp/timeline_live_events.json` —— 由真 FastAPI app（TestClient）
 * 真端点 `GET /api/v1/console/chat/sessions/{sid}/timeline` 取回，
 * 落盘顺序按 `console.py` 的 `_record_timeline` 分批形态逐条复刻
 * （旧事件流紧邻其派生 item 事件、done 在整轮末尾收口）。
 *
 * 本文件不是常规单测：它是「改完跑真实链路自证」的落点，故读取的是
 * 外部实跑产物而非内联夹具。文件缺失时跳过（CI 无该产物）。
 */
import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync } from 'node:fs'
import { agentMessagesFromTimeline } from '@/utils/timelineEvents'

const FIXTURE = '/tmp/timeline_live_events.json'
const hasFixture = existsSync(FIXTURE)

describe.skipIf(!hasFixture)('live: real backend timeline → frontend normalization', () => {
  it('同一轮双写（旧流 + item 流）归一为一段，正文不重影', () => {
    const events = JSON.parse(readFileSync(FIXTURE, 'utf-8')) as unknown[]
    expect(events.length).toBeGreaterThan(0)

    const rounds = agentMessagesFromTimeline(events)

    expect(rounds).toHaveLength(1)
    expect(rounds[0].content).toBe('答案')
    expect(rounds[0].reasoning).toBe('先看文件')
    expect(rounds[0].toolCalls?.[0].name).toBe('read_file')
    expect(rounds[0].toolCalls?.[0].result).toBe('print(1)')
    expect(rounds[0].steps?.map((s) => s.kind)).toEqual(['reasoning', 'tool'])
  })
})

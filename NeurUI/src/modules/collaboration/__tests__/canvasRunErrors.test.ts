/**
 * canvasRunErrors 纯函数测试 — 节点异常弹窗数据格式化（防回归）。
 *
 * 契约：
 * - extractRunBlockDetail(err)：axios err → {message, issues[]} | null
 *   （后端 400 detail={code:1, errors:[{node_id,label,type,missing,message}]}）
 * - collectFailedNodes(nodeResults)：轮询结果 → [{nodeId, error}]（failed 节点）
 */
import { describe, expect, it } from 'vitest'
import { collectFailedNodes, extractRunBlockDetail } from '../canvasRunErrors'

describe('extractRunBlockDetail', () => {
  it('后端 400 校验清单 → message + issues', () => {
    const raw = {
      response: {
        data: {
          detail: {
            code: 1,
            message: '节点配置异常，已停止执行',
            errors: [
              { node_id: 'llm1', label: 'LLM1', type: 'builtin:llm',
                missing: ['提示词（prompt）'], message: '节点「LLM1」配置缺失: 提示词（prompt）' },
            ],
          },
        },
      },
    }
    const out = extractRunBlockDetail(raw as never)
    expect(out).not.toBeNull()
    expect(out!.message).toContain('停止执行')
    expect(out!.issues).toHaveLength(1)
    expect(out!.issues[0].label).toBe('LLM1')
    expect(out!.issues[0].missing).toContain('提示词（prompt）')
  })

  it('非校验错误（无 detail.code=1）→ null', () => {
    expect(extractRunBlockDetail({ response: { data: { detail: '其他错误' } } } as never)).toBeNull()
    expect(extractRunBlockDetail({} as never)).toBeNull()
    expect(extractRunBlockDetail(null as never)).toBeNull()
  })
})

describe('collectFailedNodes', () => {
  it('只收集 failed 状态节点（含 error）', () => {
    const list = collectFailedNodes({
      ok: { status: 'success', output: 'x' },
      bad: { status: 'failed', error: '缺少变量名' },
    } as never)
    expect(list).toEqual([{ nodeId: 'bad', error: '缺少变量名' }])
  })

  it('空结果/无 failed 返回 []', () => {
    expect(collectFailedNodes({})).toEqual([])
    expect(collectFailedNodes({ a: { status: 'success' } } as never)).toEqual([])
  })
})

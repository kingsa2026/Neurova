/**
 * canvasClipboard 纯函数测试 — TDD 红灯先行（遗留 D）。
 *
 * duplicateNodesForPaste(nodes, edges, sourceIds, offsetX/Y)：
 * 1. 选中节点深拷贝，新 id 生成且唯一；
 * 2. 位置平移 offset；
 * 3. 内部边（两端都在选中集内）复制并重映射端点；外部边不复制；
 * 4. 返回 idMap 供调用方同步选中态。
 */
import { describe, expect, it } from 'vitest'
import { duplicateNodesForPaste } from '../canvasClipboard'
import type { CanvasNodeSnapshot, CanvasEdgeSnapshot } from '@/api/modules/collaboration'

const node = (id: string, x = 0, y = 0): CanvasNodeSnapshot => ({
  id,
  label: id,
  type: 'builtin:llm',
  icon: '🤖',
  position: { x, y },
  inputs: [],
  outputs: [],
  config: { prompt: `p-${id}` },
})

const edge = (id: string, source: string, target: string): CanvasEdgeSnapshot => ({
  id,
  source: { nodeId: source, portId: 'out' },
  target: { nodeId: target, portId: 'in' },
  x1: 0,
  y1: 0,
  x2: 10,
  y2: 10,
})

describe('duplicateNodesForPaste', () => {
  it('复制选中节点：新 id、平移位置、保留 config', () => {
    const { nodes, idMap } = duplicateNodesForPaste(
      [node('a', 10, 20), node('b', 100, 200)],
      [],
      ['a'],
      30,
      40,
    )
    expect(nodes).toHaveLength(1)
    const n = nodes[0]
    expect(n.id).not.toBe('a')
    expect(idMap['a']).toBe(n.id)
    expect(n.position).toEqual({ x: 40, y: 60 })
    expect(n.config).toEqual({ prompt: 'p-a' })
  })

  it('内部边复制且端点重映射；外部边不复制', () => {
    const nodes = [node('a'), node('b'), node('c')]
    const edges = [edge('e1', 'a', 'b'), edge('e2', 'a', 'c'), edge('e3', 'b', 'c')]
    const { nodes: newNodes, edges: newEdges } = duplicateNodesForPaste(
      nodes,
      edges,
      ['a', 'b'],
      50,
      0,
    )
    expect(newNodes).toHaveLength(2)
    // e1 两端都在选中集 → 复制；e2/e3 涉及 c → 不复制
    expect(newEdges).toHaveLength(1)
    const e = newEdges[0]
    expect(e.id).not.toBe('e1')
    expect(e.source?.nodeId).not.toBe('a')
    expect(e.target?.nodeId).not.toBe('b')
  })

  it('多次粘贴 id 不冲突', () => {
    const base = [node('a', 0, 0)]
    const p1 = duplicateNodesForPaste(base, [], ['a'], 10, 0)
    const p2 = duplicateNodesForPaste([...base, ...p1.nodes], [], ['a'], 20, 0)
    const allIds = [...p1.nodes, ...p2.nodes].map((n) => n.id)
    expect(new Set(allIds).size).toBe(allIds.length)
  })

  it('空选中集返回空结果', () => {
    const r = duplicateNodesForPaste([node('a')], [], [], 10, 10)
    expect(r.nodes).toEqual([])
    expect(r.edges).toEqual([])
  })
})

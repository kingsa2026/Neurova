/**
 * KnowledgeGraphPage 归一化与图表组装测试（补课 2.4：真渲染替换卡片假图）。
 *
 * 归一化契约：后端节点 {id,label,type,description,weight} →
 * {category: type ?? 'default', name: label ?? id}（原页面只读 category，
 * type 永远落 default——这是"图谱页无图渲染/恒 default"的根因之一）。
 */
import { describe, it, expect } from 'vitest'

// normalizeNode 从页面抽出的纯函数（保持单文件引入）
import { normalizeNode } from '@/pages/knowledge-graph/normalize'

describe('normalizeNode', () => {
  it('maps type→category and label→name', () => {
    const n = normalizeNode({ id: 'a', label: 'AI', type: 'concept', weight: 2 })
    expect(n).toMatchObject({ category: 'concept', name: 'AI', weight: 2 })
  })

  it('falls back to default category when type missing', () => {
    const n = normalizeNode({ id: 'b', name: 'B' })
    expect(n.category).toBe('default')
    expect(n.name).toBe('B')
  })

  it('keeps description for tooltip', () => {
    const n = normalizeNode({ id: 'c', label: 'C', description: 'desc text' })
    expect(n.description).toBe('desc text')
  })
})

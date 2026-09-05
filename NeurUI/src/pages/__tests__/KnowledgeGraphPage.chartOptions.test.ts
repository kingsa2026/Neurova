/**
 * 知识图谱 ECharts 配置纯函数测试（2026-09-05 悬停溢出 + label 辨识性修复）。
 *
 * 回归背景：
 * 1. tooltip 长描述单行溢出容器（截图实锤）——confine/宽度/换行三件套缺一不可
 * 2. label color:'inherit' 继承节点色——青色节点配青色文字在深底上不可读
 */
import { describe, it, expect } from 'vitest'

import {
  buildTooltipOption,
  buildNodeLabelOption,
  buildEdgeLabelOption,
  categoryColor,
  escapeHtml,
  truncateText,
  buildTooltipFormatter,
} from '@/pages/knowledge-graph/chartOptions'

describe('buildTooltipOption', () => {
  const opt = buildTooltipOption()

  it('confines tooltip inside chart container', () => {
    expect(opt.confine).toBe(true)
    expect(opt.appendToBody).toBe(false)
  })

  it('wraps long text instead of single-line overflow', () => {
    expect(opt.extraCssText).toContain('white-space:normal')
    expect(opt.extraCssText).toContain('word-break:break-word')
    expect(opt.extraCssText).toContain('max-width')
  })
})

describe('buildNodeLabelOption', () => {
  it('uses fixed high-contrast color, not node-inherited color', () => {
    const dark = buildNodeLabelOption({ isDark: true })
    const light = buildNodeLabelOption({ isDark: false })

    expect(dark.color).not.toBe('inherit')
    expect(light.color).not.toBe('inherit')
    expect(dark.color).not.toBe(light.color)
  })

  it('adds counter-color text border for readability on any node color', () => {
    const dark = buildNodeLabelOption({ isDark: true })
    const light = buildNodeLabelOption({ isDark: false })

    expect(dark.textBorderWidth).toBeGreaterThan(0)
    expect(light.textBorderWidth).toBeGreaterThan(0)
    expect(dark.textBorderColor).not.toBe(light.textBorderColor)
  })

  it('dark theme uses light text, light theme uses dark text', () => {
    expect(buildNodeLabelOption({ isDark: true }).color).toBe('#e2e8f0')
    expect(buildNodeLabelOption({ isDark: false }).color).toBe('#1e293b')
  })
})

describe('buildEdgeLabelOption', () => {
  it('hidden by default, themed when shown', () => {
    const edge = buildEdgeLabelOption({ isDark: true })
    expect(edge.show).toBe(false)
    expect(edge.color).not.toBe('inherit')
  })
})

describe('categoryColor', () => {
  it('maps known categories and falls back to default', () => {
    expect(categoryColor('entity')).toBe('#06b6d4')
    expect(categoryColor('unknown-cat')).toBe('#6366f1')
    expect(categoryColor(undefined)).toBe('#6366f1')
  })
})

describe('escapeHtml / truncateText', () => {
  it('escapes HTML metacharacters from knowledge content', () => {
    expect(escapeHtml('<script>alert(1)</script>')).toBe(
      '&lt;script&gt;alert(1)&lt;/script&gt;'
    )
    expect(escapeHtml('a&b"c\'d')).toBe('a&amp;b&quot;c&#39;d')
    expect(escapeHtml(null)).toBe('')
  })

  it('truncates long text with ellipsis, keeps short text intact', () => {
    expect(truncateText('x'.repeat(200))).toHaveLength(161)
    expect(truncateText('x'.repeat(200)).endsWith('…')).toBe(true)
    expect(truncateText('  short  ')).toBe('short')
  })
})

describe('buildTooltipFormatter', () => {
  const fmt = buildTooltipFormatter()

  it('renders node with escaped name and wrapped description', () => {
    const html = fmt({
      dataType: 'node',
      name: 'Neurova <v2>',
      data: { category: 'concept', description: 'a & b ' + '长'.repeat(200) },
    })
    expect(html).toContain('<b>Neurova &lt;v2&gt;</b>')
    expect(html).toContain('a &amp; b')
    expect(html).toContain('…')
    expect(html).not.toContain('<script')
  })

  it('renders edge as source → target with relation', () => {
    const html = fmt({
      dataType: 'edge',
      data: { source: 'A', target: 'B', relation: 'related_to' },
    })
    expect(html).toBe('A → B (related_to)')
  })
})

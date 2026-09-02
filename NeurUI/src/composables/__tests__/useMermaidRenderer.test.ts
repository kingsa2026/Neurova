/**
 * useMermaidRenderer 测试（补课 E）。
 *
 * 不加载真 mermaid（重依赖）——mock 动态 import 链路，
 * 验证：占位扫描/成功替换/失败保留源码/流式不完整不标 done/防抖。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useMermaidRenderer } from '@/composables/useMermaidRenderer'

const mockRender = vi.fn()

vi.mock('mermaid', () => ({
  default: {
    initialize: vi.fn(),
    render: (...args: unknown[]) => mockRender(...args),
  },
}))

function placeholder(code: string): string {
  return `<div class="nr-mermaid" data-mermaid-code="${encodeURIComponent(code)}"><pre class="nr-mermaid-src">${code}</pre></div>`
}

describe('useMermaidRenderer', () => {
  beforeEach(() => {
    mockRender.mockReset()
    document.body.innerHTML = ''
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders placeholder into svg on success', async () => {
    mockRender.mockResolvedValue({ svg: '<svg>graph</svg>' })
    const container = document.createElement('div')
    container.innerHTML = placeholder('graph TD; A-->B')
    document.body.appendChild(container)

    const { renderIn } = useMermaidRenderer(() => false)
    await renderIn(container)

    const el = container.querySelector('.nr-mermaid') as HTMLElement
    expect(el.getAttribute('data-mermaid-done')).toBe('1')
    expect(el.innerHTML).toContain('<svg>graph</svg>')
  })

  it('keeps source pre on render failure (incomplete stream code)', async () => {
    mockRender.mockRejectedValue(new Error('Parse error'))
    const container = document.createElement('div')
    container.innerHTML = placeholder('graph TD; A-')
    document.body.appendChild(container)

    const { renderIn } = useMermaidRenderer(() => false)
    await renderIn(container)

    const el = container.querySelector('.nr-mermaid') as HTMLElement
    // 不标 done（流式下轮重试），源码 pre 保留
    expect(el.getAttribute('data-mermaid-done')).toBeNull()
    expect(el.querySelector('.nr-mermaid-src')).toBeTruthy()
  })

  it('is idempotent: done placeholders are skipped', async () => {
    mockRender.mockResolvedValue({ svg: '<svg>ok</svg>' })
    const container = document.createElement('div')
    container.innerHTML = placeholder('graph TD; A-->B')
    document.body.appendChild(container)

    const { renderIn } = useMermaidRenderer(() => false)
    await renderIn(container)
    await renderIn(container)
    expect(mockRender).toHaveBeenCalledTimes(1)
  })

  it('respects theme getter', async () => {
    mockRender.mockResolvedValue({ svg: '<svg>x</svg>' })
    const container = document.createElement('div')
    container.innerHTML = placeholder('graph TD; A-->B')
    document.body.appendChild(container)

    const themeSpy = vi.fn(() => true)
    const { renderIn } = useMermaidRenderer(themeSpy)
    await renderIn(container)
    expect(themeSpy).toHaveBeenCalled()
  })
})

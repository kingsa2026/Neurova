import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import GlassStatCard from '@/components/GlassStatCard.vue'

function mountCard(props: Record<string, unknown> = {}) {
  return mount(GlassStatCard, {
    props: { label: '测试', value: 42, ...props },
    global: {
      stubs: {
        GlassPanel: { template: '<div><slot /></div>' },
      },
    },
  })
}

describe('GlassStatCard sparkline', () => {
  it('does not produce Infinity/NaN path for single-point series', () => {
    // 回归：step = width / (length - 1) 在单点时除以 0 → path 含 Infinity/NaN
    const wrapper = mountCard({ sparkData: [5] })
    const path = wrapper.find('.nr-stat-spark svg path')
    expect(path.exists()).toBe(true)
    const d = path.attributes('d') ?? ''
    expect(d).not.toContain('NaN')
    expect(d).not.toContain('Infinity')
    expect(d).toContain('M')
  })

  it('renders valid path for multi-point series', () => {
    const wrapper = mountCard({ sparkData: [1, 3, 2, 5] })
    const d = wrapper.find('.nr-stat-spark svg path').attributes('d') ?? ''
    expect(d).toContain('L')
    expect(d).not.toContain('NaN')
  })
})

describe('GlassStatCard trend badge', () => {
  it('renders positive badge with plus sign', () => {
    const wrapper = mountCard({ trend: 15 })
    expect(wrapper.find('.nr-stat-trend').text()).toBe('+15%')
  })

  it('hides the badge when trend is 0 (no delta info)', () => {
    // 回归：trend===0 也渲染 "+0%" 徽章，语义误导
    const wrapper = mountCard({ trend: 0 })
    expect(wrapper.find('.nr-stat-trend').exists()).toBe(false)
  })

  it('renders negative badge without plus sign', () => {
    const wrapper = mountCard({ trend: -8 })
    expect(wrapper.find('.nr-stat-trend').text()).toBe('-8%')
  })
})

/**
 * GlassCard extra 插槽契约测试（红绿灯 TDD）
 *
 * 根因（2026-09-03 逐 tab 排查）: MemorySettingsPage / SleepStatusPage /
 * MetacognitionPage / SleepSettingsPage 共 4 处使用 <template #extra>
 * （标题右侧内容：分组描述等），但 GlassCard 从未声明 extra 插槽 ——
 * 内容被 Vue 静默丢弃, memorySettings.sectionXxxDesc（8 条 × 11 语言）
 * 上线后一直不可见。
 *
 * 契约:
 *   1. 传 #extra 时, 内容必须渲染在标题行右侧（与 title 同行）。
 *   2. 未传 #extra 时, 布局行为不变（header 无额外行）。
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import GlassCard from '@/components/GlassCard.vue'

const globalStubs = {
  GlassPanel: { template: '<div class="nr-glass-panel"><slot/></div>' },
}

describe('GlassCard extra 插槽', () => {
  it('#extra 内容渲染在标题行（与标题同行）', () => {
    const wrapper = mount(GlassCard, {
      props: { title: '记忆压缩' },
      slots: { extra: '<span class="extra-mark">分组描述文本</span>' },
      global: { stubs: globalStubs },
    })
    const row = wrapper.find('.nr-glass-card-header-row')
    expect(row.exists()).toBe(true)
    expect(row.text()).toContain('记忆压缩')
    expect(row.text()).toContain('分组描述文本')
    expect(wrapper.find('.nr-glass-card-extra .extra-mark').exists()).toBe(true)
  })

  it('未传 #extra 时 header 布局保持兼容（无 header-row 额外层）', () => {
    const wrapper = mount(GlassCard, {
      props: { title: '温度系统' },
      slots: { default: '<div>body</div>' },
      global: { stubs: globalStubs },
    })
    expect(wrapper.text()).toContain('温度系统')
    expect(wrapper.find('.nr-glass-card-header-row').exists()).toBe(false)
  })
})

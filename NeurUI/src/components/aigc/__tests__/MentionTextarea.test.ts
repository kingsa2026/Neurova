/** MentionTextarea：@ 触发候选弹层、选中插入并回报资产映射（R5）。 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import MentionTextarea from '@/components/aigc/MentionTextarea.vue'

const CANDS = [
  { name: '林凡', id: 'c1' },
  { name: '苏瑶', id: 'c2' },
]

const mountTA = () =>
  mount(MentionTextarea, { props: { modelValue: '', candidates: CANDS, rows: 2 } })

describe('MentionTextarea', () => {
  it('输入 @ 弹出资产候选', async () => {
    const wrapper = mountTA()
    const el = wrapper.find('textarea').element as HTMLTextAreaElement
    // 组件 textarea 为 :value 受控（modelValue prop 固定），测试直接设 DOM 值
    el.value = '场景里 @'
    el.selectionStart = el.value.length
    const vm = wrapper.vm as any
    await vm.onInput({ target: el })
    expect(vm.showPicker).toBe(true)
    expect(wrapper.findAll('.mention-option').length).toBe(2)
  })

  it('选中插入 @名称 并 emit refs 映射', async () => {
    const wrapper = mountTA()
    const vm = wrapper.vm as any
    vm.showPicker = true
    await vm.pick(CANDS[0])
    const events = wrapper.emitted('update:modelValue')
    expect(events?.at(-1)?.[0]).toContain('@林凡')
    const refs = wrapper.emitted('refs')?.at(-1)?.[0]
    expect(refs).toEqual([{ name: '林凡', id: 'c1' }])
  })

  it('粘贴含 @角色 的文本自动解析映射', async () => {
    const wrapper = mountTA()
    const vm = wrapper.vm as any
    vm.syncSelected('林凡转身，@苏瑶 看向窗外')
    const refs = wrapper.emitted('refs')?.at(-1)?.[0]
    expect(refs).toEqual([{ name: '苏瑶', id: 'c2' }])
  })
})

/**
 * GlassInput 表单可访问性契约测试（2026-09-16 浏览器实测发现）
 *
 * 根因: GlassInput 未接入 Ant Design FormItem 的 provide/inject 契约 ——
 * 内置 a-input 通过 useInjectFormItemContext() 把 FormItem 生成的 id 绑到
 * input 上，a-form-item 的 <label for> 指向该 id；GlassInput 缺这一步，
 * label for 悬空 → getByLabel 定位不到、点击 label 不聚焦、读屏无名称。
 * 同根因断链还有: 不调 onFieldBlur/onFieldChange → blur/change 校验不触发。
 *
 * 契约:
 *   1. 独立使用（label prop）: input 有 id，label[for] === input.id。
 *   2. a-form-item 包裹: input.id === FormItem label 的 for（id 由 FormItem 单源）。
 *   3. blur 时调用 formItemContext.onFieldBlur（触发 blur 校验）。
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h, ref } from 'vue'
import { Form, FormItem } from 'ant-design-vue'
import GlassInput from '../GlassInput.vue'

describe('GlassInput · label 关联（独立 label prop）', () => {
  it('input 有 id 且自带 label 的 for 指向它', () => {
    const wrapper = mount(GlassInput, { props: { label: '用户名', modelValue: '' } })
    const input = wrapper.find('input')
    const label = wrapper.find('label')
    expect(input.attributes('id')).toBeTruthy()
    expect(label.attributes('for')).toBe(input.attributes('id'))
  })
})

describe('GlassInput · 接入 Ant Design FormItem 契约', () => {
  function mountInFormItem() {
    const model = ref({ username: '' })
    const Host = defineComponent({
      setup: () => () =>
        h(Form, { model: model.value }, () => [
          h(FormItem, { label: '用户名', name: 'username' }, () => [
            h(GlassInput, { modelValue: model.value.username, 'onUpdate:modelValue': (v: string) => (model.value.username = v) }),
          ]),
        ]),
    })
    return mount(Host, { global: { components: { AForm: Form, AFormItem: FormItem } } })
  }

  it('input.id 与 FormItem 渲染的 label[for] 一致（getByLabel 可定位）', () => {
    const wrapper = mountInFormItem()
    const label = wrapper.find('label')
    const input = wrapper.find('input')
    expect(label.exists(), 'FormItem 应渲染 label').toBe(true)
    const forId = label.attributes('for')
    expect(forId, 'FormItem label 应有 for').toBeTruthy()
    expect(input.attributes('id'), 'GlassInput 必须把 FormItem id 绑到 input').toBe(forId)
  })

  it('input blur 触发 FormItem blur 校验（onFieldBlur 真实接线）', async () => {
    const model = ref({ username: '' })
    const Host = defineComponent({
      setup: () => () =>
        h(Form, { model: model.value }, () => [
          h(FormItem, { label: '用户名', name: 'username', rules: [{ required: true, message: '请输入用户名', trigger: 'blur' }] }, () => [
            h(GlassInput, { modelValue: model.value.username }),
          ]),
        ]),
    })
    const wrapper = mount(Host, { global: { components: { AForm: Form, AFormItem: FormItem } } })
    await wrapper.find('input').trigger('blur')
    // async-validator 异步落错，等待微任务 + 定时器冲刷
    await new Promise((r) => setTimeout(r, 100))
    expect(wrapper.text(), 'blur 应触发必填校验并显示错误').toContain('请输入用户名')
  })
})

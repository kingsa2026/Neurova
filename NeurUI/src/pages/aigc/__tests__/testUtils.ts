/** AIGC 拆分页测试共享工具：真实 zh-CN 语言包 + antd 组件 stub 集。 */
import { expect } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/i18n/locales/zh-CN'

export function makeAigcI18n() {
  return createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })
}

export const AIGC_STUBS = {
  GlassPanel: { template: '<div><slot /></div>' },
  GlassCard: { props: ['title'], template: '<div><slot /></div>' },
  GlassButton: { template: '<button @click="$emit(\'click\')"><slot /></button>' },
  'a-tabs': { template: '<div><slot /></div>' },
  'a-tab-pane': { template: '<div><slot /></div>' },
  'a-form': { template: '<div><slot /></div>' },
  'a-form-item': { props: ['label'], template: '<div><slot /></div>' },
  'a-textarea': { template: '<textarea />' },
  'a-input': { props: ['value'], template: '<input />' },
  'a-input-number': { template: '<input />' },
  'a-slider': { template: '<div />' },
  'a-select': {
    props: ['options'],
    template: '<select class="stub-select"><option v-for="o in options || []" :key="o.value" :value="o.value">{{ o.label }}</option></select>',
  },
  'a-select-option': { props: ['value'], template: '<option><slot /></option>' },
  'a-empty': { template: '<div><slot /></div>' },
  'a-modal': { template: '<div><slot /></div>' },
  'a-descriptions': { template: '<div><slot /></div>' },
  'a-descriptions-item': { template: '<div><slot /></div>' },
  'a-progress': { template: '<div />' },
  'a-radio-group': { template: '<div><slot /></div>' },
  'a-radio-button': { props: ['value'], template: '<span><slot /></span>' },
  'a-tag': { template: '<span><slot /></span>' },
  'a-tooltip': { template: '<span><slot /></span>' },
  'a-upload': {
    props: ['customRequest'],
    template: '<button class="upload-stub" @click="$props.customRequest && $props.customRequest({ file: new File([\'x\'], \'ref.png\', { type: \'image/png\' }) })"><slot /></button>',
  },
  'a-spin': { template: '<div><slot /></div>' },
}

/** 按选择器取 select 的 option value 列表 */
export function optionValues(wrapper: any, selector: string): string[] {
  const sel = wrapper.find(selector)
  expect(sel.exists(), `应存在 ${selector}`).toBe(true)
  return sel.findAll('option').map((o: any) => o.attributes('value') ?? '')
}

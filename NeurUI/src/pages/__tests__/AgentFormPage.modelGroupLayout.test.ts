import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

/**
 * Agent 编辑/新建页·模型与所属分组布局＋分组跟随语义（用户需求 2026-11-11）。
 *
 * 需求两半：
 * 1. 模型 ID 与所属分组互换位置——模型跟供应商同行（第一行右侧），分组独占下一行；
 * 2. 所属分组不再让用户选树——自动跟随创建者所属部门组（后端 specs/2026-11-07 批 D
 *    已有缺省绑定：`agent.py` 创建时 `group_id=body.group_id or _creatorDeptGroupId(...)`；
 *    提交链 `group_id: formState.group_id || undefined` 空值即不传 → 缺省生效）。
 *
 * 修复前：分组是 a-tree-select 手动树选（第一行右侧）、模型在第二行。
 */

vi.mock('@/api/modules/providers', () => ({
  listProviders: vi.fn().mockResolvedValue({ data: { providers: [], builtin: [] } }),
}))
vi.mock('@/api/modules/models', () => ({
  listModels: vi.fn().mockResolvedValue({ data: [] }),
}))
vi.mock('@/api/modules/groups', () => ({
  listGroups: vi.fn().mockResolvedValue([
    { group_id: 'dept-1', name: '研发部', group_type: 'custom', parent_group_id: null },
  ]),
}))
vi.mock('@/stores/agents', () => ({
  useAgentStore: () => ({
    agents: [] as Array<Record<string, unknown>>,
    error: null as string | null,
    loadAgents: vi.fn().mockResolvedValue(undefined),
    createAgent: vi.fn().mockResolvedValue({ id: 'new-agent' }),
    updateAgent: vi.fn().mockResolvedValue({ id: 'a1' }),
  }),
}))
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: {} as Record<string, string> }),
  useRouter: () => ({ push: vi.fn() }),
}))

import AgentFormPage from '../AgentFormPage.vue'

const messages = {
  'zh-CN': {
    common: { save: '保存', cancel: '取消', error: '失败' },
    agent: {
      name: '名称', agentId: 'Agent ID', idReadonly: '不可改', idHint: '唯一标识',
      idPlaceholder: 'agent id', provider: '供应商', selectProvider: '请选择服务商',
      model: '模型', selectModel: '请选择模型',
      group: '所属分组', groupDefaultHint: '缺省绑定创建者所在部门组',
      description: '描述', systemPrompt: '系统提示词', systemPromptPlaceholder: '提示词',
      temperature: '温度', maxTokens: '最大 Token', personality: '个性', constitution: '章程',
      tts: '语音', ttsEnabled: '启用语音', ttsVoice: '音色', ttsSpeed: '语速', ttsPitch: '音调',
    },
  },
}

const globalStubs = {
  GlassCard: { props: ['title'], template: '<div class="glass-card"><slot name="header"/><slot/></div>' },
  GlassButton: { props: ['variant', 'size', 'loading'], template: '<button :disabled="loading"><slot/></button>' },
  'a-row': { template: '<div class="a-row"><slot/></div>' },
  'a-col': { props: ['span'], template: '<div class="a-col"><slot/></div>' },
  'a-form': { template: '<form><slot/></form>' },
  'a-form-item': { props: ['label', 'extra'], template: '<div class="form-item-stub" :data-label="label"><label>{{ label }}</label><slot/></div>' },
  'a-input': { props: ['value', 'placeholder', 'readonly', 'disabled'], template: '<input class="a-input-stub" :value="value ?? placeholder ?? \'\'" :readonly="readonly" :disabled="disabled" />' },
  'a-select': { props: ['value', 'options', 'placeholder', 'loading', 'disabled'], template: '<select class="a-select-stub"><option v-for="o in (options || [])" :key="o.value" :value="o.value">{{ o.label }}</option></select>' },
  'a-tree-select': { props: ['value', 'treeData', 'placeholder'], template: '<div class="a-tree-select-stub"/>' },
  'a-textarea': { props: ['value', 'rows', 'placeholder'], template: '<textarea/>' },
  'a-slider': { props: ['value'], template: '<input type="range"/>' },
  'a-input-number': { props: ['value'], template: '<input/>' },
  'a-switch': { props: ['checked'], template: '<button class="a-switch-stub"/>' },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages })
  return mount(AgentFormPage, { global: { plugins: [i18n], stubs: globalStubs } })
}

function formItemIndex(wrapper: ReturnType<typeof mountPage>, label: string): number {
  return wrapper.findAll('.form-item-stub').findIndex(
    (f) => (f.attributes('data-label') ?? '') === label,
  )
}

describe('AgentFormPage — 模型/分组互换＋分组跟随（新建态）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('分组不再用树形选择（a-tree-select 退役）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.find('.a-tree-select-stub').exists()).toBe(false), (
      '所属分组不应再让用户树选——自动跟随创建者部门组（后端缺省绑定已存在）')
  })

  it('分组只读展示跟随文案（缺省绑定创建者所在部门组）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const groupItem = wrapper.findAll('.form-item-stub').find(
      (f) => (f.attributes('data-label') ?? '') === '所属分组',
    )
    expect(groupItem).toBeDefined()
    const readonlyInput = groupItem!.find('input.a-input-stub')
    expect(readonlyInput.exists()).toBe(true), '分组应是只读 input（不再树选）'
    expect(readonlyInput.attributes('value')).toContain('缺省绑定创建者所在部门组'), (
      '新建态分组应只读显示"跟随创建者部门组"语义，而不是空树选')
    expect(readonlyInput.attributes('readonly')).toBeDefined(), '分组 input 必须只读'
  })

  it('模型列在所属分组之前（互换后模型与供应商同行、分组独占下一行）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const modelIdx = formItemIndex(wrapper, '模型')
    const groupIdx = formItemIndex(wrapper, '所属分组')
    expect(modelIdx).toBeGreaterThanOrEqual(0)
    expect(groupIdx).toBeGreaterThanOrEqual(0)
    expect(modelIdx).toBeLessThan(groupIdx), (
      '互换后模型应在所属分组之前（修复前分组在第一行右侧、模型在第二行）')
  })
})

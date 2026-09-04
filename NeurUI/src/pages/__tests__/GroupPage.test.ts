/**
 * GroupPage 用户组管理测试 — 功能模块勾选
 *
 * 契约:
 *  1. 组卡片按后端 group_id 契约渲染（原前端用 id，与后端断链）。
 *  2. 编辑弹窗内按菜单结构渲染功能模块勾选（全部模块 + 已启用项预勾选）。
 *  3. 保存时 allowed_modules 随 PUT /groups/{id} 提交。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

const listGroups = vi.fn()
const updateGroup = vi.fn()
const createGroup = vi.fn()
const deleteGroup = vi.fn()
const listGroupMembers = vi.fn()
const addGroupMember = vi.fn()
const removeGroupMember = vi.fn()

vi.mock('@/api/modules/groups', () => ({
  listGroups: (...a: unknown[]) => listGroups(...a),
  updateGroup: (...a: unknown[]) => updateGroup(...a),
  createGroup: (...a: unknown[]) => createGroup(...a),
  deleteGroup: (...a: unknown[]) => deleteGroup(...a),
  listGroupMembers: (...a: unknown[]) => listGroupMembers(...a),
  addGroupMember: (...a: unknown[]) => addGroupMember(...a),
  removeGroupMember: (...a: unknown[]) => removeGroupMember(...a),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { username: 'admin', role: 'admin' } }),
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn() },
  Modal: { confirm: vi.fn() },
}))

import GroupPage from '../GroupPage.vue'
import { ALL_MODULE_KEYS, MODULE_SECTIONS } from '@/config/modules'

const messages = {
  system: { groups: '用户组', allowedModules: '可用功能模块', allowedModulesHint: '勾选后仅显示所选功能模块；全部不勾选 = 不限制' },
  common: { globalSettingHint: '全局', adminOnlyHint: '仅管理员', create: '创建', edit: '编辑', delete: '删除', name: '名称', description: '描述', confirm: '确认', success: '成功', error: '失败', noData: '暂无数据', required: '必填', all: '全选', none: '清空', selectAll: '全选' },
  collab: { members: '成员', addMember: '添加成员' },
  agent: { deleteConfirm: '确认删除？' },
  nav: {
    agentZone: 'Agent 区', userZone: '用户区', topNav: '系统配置',
    chat: '对话', memory: '记忆', agentfiles: '文件',
    models: '模型服务', monitor: '资源监控', settings: '系统设置', marketplace: '市场管理',
    dashboard: '总览', agents: 'Agent 管理', knowledge: '知识库',
  },
}

const globalStubs = {
  GlassCard: { props: ['title'], template: '<div class="glass-card"><h3>{{ title }}</h3><slot/><slot name="header"/><slot name="footer"/></div>' },
  GlassButton: { props: ['variant', 'size'], emits: ['click'], template: '<button class="glass-btn" @click="$emit(\'click\')"><slot/></button>' },
  'a-spin': { template: '<div><slot/></div>' },
  'a-modal': { template: '<div class="ant-modal"><slot/></div>' },
  'a-form': { template: '<form><slot/></form>' },
  'a-form-item': { template: '<div class="ant-form-item"><slot/></div>' },
  'a-input': { template: '<input />' },
  'a-textarea': { template: '<textarea />' },
  'a-checkbox': {
    props: ['checked', 'value', 'indeterminate'],
    emits: ['change'],
    template: '<label class="ant-checkbox" :data-value="value" :data-checked="checked ? \'1\' : \'0\'" :data-indeterminate="indeterminate ? \'1\' : \'0\'" @click="$emit(\'change\', !checked)"><slot/></label>',
  },
  'a-pagination': { template: '<div />' },
  'a-empty': { template: '<div class="ant-empty" />' },
  'a-tag': { template: '<span class="ant-tag"><slot/></span>' },
  'a-list': { template: '<div><slot/></div>' },
  'a-list-item': { template: '<div><slot/></div>' },
  'a-popconfirm': { template: '<span><slot /></span>' },
}

function makeI18n() {
  return createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
}

function mountPage() {
  return mount(GroupPage, {
    global: { plugins: [makeI18n(), createPinia()], stubs: globalStubs },
  })
}

const backendGroups = [
  { group_id: 'g1', name: '市场组', description: '只开市场', allowed_modules: ['/marketplace'], members: ['alice'], members_count: 1, is_system: false },
  { group_id: 'g2', name: '管理员', description: '', allowed_modules: [], members: [], members_count: 0, is_system: true },
]

beforeEach(() => {
  vi.clearAllMocks()
  listGroups.mockResolvedValue(backendGroups)
  listGroupMembers.mockResolvedValue([{ id: 'alice', username: 'alice' }])
  updateGroup.mockResolvedValue({})
})

describe('GroupPage 用户组管理', () => {
  it('按 group_id 契约渲染组卡片', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const cards = wrapper.findAll('.glass-card')
    expect(cards.length).toBe(2)
    expect(cards[0].text()).toContain('市场组')
  })

  it('编辑弹窗渲染全部功能模块勾选项，已启用项预勾选', async () => {
    const wrapper = mountPage()
    await flushPromises()
    // 打开第一组的编辑弹窗
    const editBtns = wrapper.findAll('.glass-btn')
    await editBtns.find(b => b.text() === '编辑')!.trigger('click')
    await flushPromises()

    const boxes = wrapper.findAll('.ant-checkbox[data-value]')
    expect(boxes.length).toBe(ALL_MODULE_KEYS.length)
    const checked = boxes.filter(b => b.attributes('data-checked') === '1').map(b => b.attributes('data-value'))
    expect(checked).toEqual(['/marketplace'])
  })

  it('分区标题带全选勾选框：勾选后该分类下模块全选，再点清空该分类', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.findAll('.glass-btn').find(b => b.text() === '编辑')!.trigger('click')
    await flushPromises()

    const zoneBoxes = wrapper.findAll('.ant-checkbox[data-zone]')
    expect(zoneBoxes.length).toBe(3)
    const topNav = MODULE_SECTIONS.find(s => s.zone === 'topNav')!

    // 勾选 topNav 分区 → 分区内模块全部选中
    await zoneBoxes.find(b => b.attributes('data-zone') === 'topNav')!.trigger('click')
    await flushPromises()
    const boxes = wrapper.findAll('.ant-checkbox[data-value]')
    for (const item of topNav.items) {
      const box = boxes.find(b => b.attributes('data-value') === item.key)!
      expect(box.attributes('data-checked'), item.key).toBe('1')
    }
    // 分区勾选框自身呈选中态
    expect(zoneBoxes.find(b => b.attributes('data-zone') === 'topNav')!.attributes('data-checked')).toBe('1')

    // 再点一次 → 清空该分区（其他分区不受影响）
    await wrapper.findAll('.ant-checkbox[data-zone]').find(b => b.attributes('data-zone') === 'topNav')!.trigger('click')
    await flushPromises()
    const boxes2 = wrapper.findAll('.ant-checkbox[data-value]')
    for (const item of topNav.items) {
      const box = boxes2.find(b => b.attributes('data-value') === item.key)!
      expect(box.attributes('data-checked'), item.key).toBe('0')
    }
  })

  it('分区部分选中时呈半选态（indeterminate）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.findAll('.glass-btn').find(b => b.text() === '编辑')!.trigger('click')
    await flushPromises()

    // 勾选 topNav 分区下第一个模块
    const topNav = MODULE_SECTIONS.find(s => s.zone === 'topNav')!
    const firstKey = topNav.items[0].key
    await wrapper.findAll('.ant-checkbox[data-value]').find(b => b.attributes('data-value') === firstKey)!.trigger('click')
    await flushPromises()

    const zoneBox = wrapper.findAll('.ant-checkbox[data-zone]').find(b => b.attributes('data-zone') === 'topNav')!
    expect(zoneBox.attributes('data-checked')).toBe('0')
    expect(zoneBox.attributes('data-indeterminate')).toBe('1')
  })

  it('保存时 allowed_modules 随更新请求提交', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.findAll('.glass-btn').find(b => b.text() === '编辑')!.trigger('click')
    await flushPromises()

    // 勾选第二个模块（默认只有 /marketplace）
    const boxes = wrapper.findAll('.ant-checkbox[data-value]')
    const second = boxes[1]
    expect(second.attributes('data-checked')).toBe('0')
    await second.trigger('click')

    // 触发弹窗保存
    const okBtn = wrapper.findAll('.glass-btn').find(b => b.text() === '确定' || b.text() === '确认' || b.text() === '保存')
    // Modal stub 不渲染 footer 按钮 — 直接调用组件保存逻辑
    await (wrapper.vm as any).saveGroup()
    await flushPromises()

    expect(updateGroup).toHaveBeenCalledTimes(1)
    const payload = updateGroup.mock.calls[0][1]
    expect(payload.allowed_modules).toEqual(['/marketplace', boxes[1].attributes('data-value')])
  })
})

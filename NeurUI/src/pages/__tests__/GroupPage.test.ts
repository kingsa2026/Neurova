/**
 * GroupPage 用户组管理测试 — 双栏布局（左分组树 × 右成员面板）
 *
 * 契约（用户示意图 2026-11-09）:
 *  1. 分组树分两段：系统分组（is_system）＋自定义分组（部门层级）；组节点带成员数徽章。
 *  2. 未选中分组时，右侧成员面板默认显示未分组用户（全部用户 − 各组成员并集）。
 *  3. 点击选中分组 → 右面板显示该组成员；再次点击同一分组 → 回落未分组用户。
 *  4. 组节点行内操作：系统组只有 成员/编辑；自定义组有 成员/改名/编辑/删除。
 *  5. 改名弹窗提交 updateGroup(id, { name })。
 *  6. 编辑弹窗：系统组的名称/描述/上级部门禁用（后端只放行系统组的权限面）。
 *  7. 编辑弹窗按菜单结构渲染功能模块勾选（沿用原契约）＋保存随 PUT 提交。
 *  8. 右面板添加成员走 addGroupMember 并刷新分组。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'
import { Modal } from 'ant-design-vue'

const listGroups = vi.fn()
const updateGroup = vi.fn()
const createGroup = vi.fn()
const deleteGroup = vi.fn()
const addGroupMember = vi.fn()
const removeGroupMember = vi.fn()
const listUsers = vi.fn()
const listKnowledgeCategories = vi.fn()

vi.mock('@/api/modules/groups', () => ({
  listGroups: (...a: unknown[]) => listGroups(...a),
  updateGroup: (...a: unknown[]) => updateGroup(...a),
  createGroup: (...a: unknown[]) => createGroup(...a),
  deleteGroup: (...a: unknown[]) => deleteGroup(...a),
  listGroupMembers: vi.fn(),
  addGroupMember: (...a: unknown[]) => addGroupMember(...a),
  removeGroupMember: (...a: unknown[]) => removeGroupMember(...a),
}))
vi.mock('@/api/modules/enhanced-users', () => ({
  listUsers: (...a: unknown[]) => listUsers(...a),
}))
vi.mock('@/api/modules/knowledge', () => ({
  listKnowledgeCategories: (...a: unknown[]) => listKnowledgeCategories(...a),
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
  system: {
    groups: '用户组管理', builtinGroups: '系统分组', customGroups: '自定义分组',
    ungroupedUsers: '未分组用户', ungroupedHint: '尚未归属任何分组的用户',
    reloginHint: '分组或成员变更需重新登录后生效',
    allowedModules: '可用功能模块', allowedModulesHint: '勾选后仅显示所选功能模块；全部不勾选 = 不限制',
    allowedCategories: '知识库分类白名单', allowedCategoriesHint: '勾选后仅访问所选分类；全部不勾选 = 不限制',
    defaultCategory: '缺省业务分类', defaultCategoryHint: '缺省分类', categoriesUnrestricted: '不限制',
    parentGroup: '上级部门', parentGroupHint: '层级', parentGroupNone: '无',
  },
  common: { globalSettingHint: '全局', adminOnlyHint: '仅管理员', create: '创建', edit: '编辑', delete: '删除', rename: '重命名', name: '名称', description: '描述', confirm: '确认', success: '成功', error: '失败', noData: '暂无数据', required: '必填', all: '全选', none: '清空', selectAll: '全选' },
  collab: { members: '成员', addMember: '添加成员' },
  agent: { deleteConfirm: '确认删除？' },
  nav: {
    agentZone: 'Agent 区', userZone: '用户区', topNav: '系统配置',
    chat: '对话', memory: '记忆', agentfiles: '文件',
    models: '模型服务', monitor: '资源监控', settings: '系统设置', marketplace: '市场管理',
    dashboard: '总览', agents: 'Agent 管理', knowledge: '知识库',
  },
}

/** a-tree 扁平化替身：全节点平铺渲染 title 插槽，点击行为与 a-tree 一致（选中再点 = 取消） */
const treeStub = {
  props: ['treeData', 'selectedKeys'],
  emits: ['select'],
  computed: {
    flatNodes(this: { treeData?: Array<Record<string, unknown>> }): Array<Record<string, unknown>> {
      const out: Array<Record<string, unknown>> = []
      const walk = (nodes?: Array<Record<string, unknown>>) => {
        for (const n of nodes ?? []) {
          out.push(n)
          walk(n.children as Array<Record<string, unknown>> | undefined)
        }
      }
      walk(this.treeData)
      return out
    },
  },
  methods: {
    onSelect(
      this: { selectedKeys?: string[]; $emit: (event: string, ...args: unknown[]) => void },
      node: Record<string, unknown>,
    ) {
      const keys = this.selectedKeys || []
      this.$emit('select', keys.includes(node.key as string) ? [] : [node.key])
    },
  },
  template: `
    <div class="ant-tree">
      <div v-for="node in flatNodes" :key="String(node.key)" class="ant-tree-treenode"
           :data-key="String(node.key)"
           :data-selected="((selectedKeys || []).includes(node.key)) ? '1' : '0'"
           @click="onSelect(node)">
        <slot name="title" :data="node" />
      </div>
    </div>`,
}

const globalStubs = {
  GlassCard: { props: ['title'], template: '<div class="glass-card"><h3>{{ title }}</h3><slot/><slot name="header"/><slot name="footer"/></div>' },
  GlassButton: { props: ['variant', 'size'], emits: ['click'], template: '<button class="glass-btn" @click="$emit(\'click\', $event)"><slot/></button>' },
  'a-spin': { template: '<div><slot/></div>' },
  'a-modal': { props: ['title', 'open'], template: '<div class="ant-modal" :data-title="title"><slot/></div>' },
  'a-form': { template: '<form><slot/></form>' },
  'a-form-item': { template: '<div class="ant-form-item"><slot/></div>' },
  'a-input': { props: ['value', 'disabled'], emits: ['update:value'], template: '<input class="a-input" :disabled="disabled || undefined" :value="value" @input="$emit(\'update:value\', $event.target.value)" />' },
  'a-textarea': { props: ['value', 'disabled'], emits: ['update:value'], template: '<textarea :disabled="disabled || undefined" />' },
  'a-tree-select': { props: ['value', 'disabled'], template: '<div class="a-tree-select" :data-disabled="disabled ? \'1\' : \'0\'" />' },
  'a-select': { props: ['value'], template: '<div class="a-select" />' },
  'a-auto-complete': { props: ['value', 'options'], emits: ['update:value'], template: '<input class="member-input" :value="value" @input="$emit(\'update:value\', $event.target.value)" />' },
  'a-checkbox': {
    props: ['checked', 'value', 'indeterminate'],
    emits: ['change'],
    template: '<label class="ant-checkbox" :data-value="value" :data-checked="checked ? \'1\' : \'0\'" :data-indeterminate="indeterminate ? \'1\' : \'0\'" @click="$emit(\'change\', !checked)"><slot/></label>',
  },
  'a-empty': { template: '<div class="ant-empty" />' },
  'a-tag': { template: '<span class="ant-tag"><slot/></span>' },
  'a-list': {
    props: ['dataSource'],
    template: `<div class="a-list">
      <template v-for="(item, i) in (dataSource || [])" :key="i">
        <div class="a-list-row"><slot name="renderItem" :item="item" :index="i" /></div>
      </template>
      <slot v-if="!(dataSource || []).length" name="empty" />
    </div>`,
  },
  'a-list-item': { template: '<div class="a-list-item"><slot/></div>' },
  'a-popconfirm': { template: '<span><slot /></span>' },
  'a-tree': treeStub,
}

function makeI18n() {
  return createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
}

function mountPage() {
  return mount(GroupPage, {
    global: { plugins: [makeI18n(), createPinia()], stubs: globalStubs },
  })
}

type MountedPage = ReturnType<typeof mountPage>

const backendGroups = [
  { group_id: 'g-sys', name: '管理员', description: '', is_system: true, members: ['root'], members_count: 1, allowed_modules: [], parent_group_id: null },
  { group_id: 'g-mkt', name: '市场组', description: '只开市场', is_system: false, members: ['alice'], members_count: 1, allowed_modules: ['/marketplace'], parent_group_id: null },
  { group_id: 'g-dev', name: '研发组', description: '', is_system: false, members: ['bob'], members_count: 1, allowed_modules: [], parent_group_id: 'g-mkt' },
]
const backendUsers = {
  items: [
    { id: 'u1', username: 'root', role: 'admin' },
    { id: 'u2', username: 'alice', role: 'user' },
    { id: 'u3', username: 'bob', role: 'user' },
    { id: 'u4', username: 'carol', role: 'user' },
  ],
}

const treeRow = (wrapper: MountedPage, key: string) =>
  wrapper.findAll('.ant-tree-treenode').find(r => r.attributes('data-key') === key)!

const rowAction = (wrapper: MountedPage, key: string, label: string) =>
  treeRow(wrapper, key)!.findAll('button.node-action').find(b => b.text() === label)

const rightPanel = (wrapper: MountedPage) => wrapper.find('.panel-members')

beforeEach(() => {
  vi.clearAllMocks()
  listGroups.mockResolvedValue(backendGroups)
  listUsers.mockResolvedValue(backendUsers)
  listKnowledgeCategories.mockResolvedValue({ data: [] })
  updateGroup.mockResolvedValue({})
  addGroupMember.mockResolvedValue({})
})

describe('GroupPage 双栏布局：分组树 × 成员面板', () => {
  it('树分两段：系统分组在前（含 is_system 组），自定义分组在后（部门层级）', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const keys = wrapper.findAll('.ant-tree-treenode').map(r => r.attributes('data-key'))
    // 两段小节存在且系统段在前
    expect(keys.indexOf('section:system')).toBeGreaterThanOrEqual(0)
    expect(keys.indexOf('section:custom')).toBeGreaterThan(keys.indexOf('section:system'))
    // 三个组节点全部在树上
    expect(keys).toContain('g-sys')
    expect(keys).toContain('g-mkt')
    expect(keys).toContain('g-dev')
    // 小节标题与组名渲染
    expect(treeRow(wrapper, 'section:system')!.text()).toContain('系统分组')
    expect(treeRow(wrapper, 'g-sys')!.text()).toContain('管理员')
    expect(treeRow(wrapper, 'g-dev')!.text()).toContain('研发组')
  })

  it('未选中分组时右面板默认显示未分组用户（全部用户 − 各组成员并集）', async () => {
    const wrapper = mountPage()
    await flushPromises()

    expect(rightPanel(wrapper).find('.panel-title').text()).toContain('未分组用户')
    const panelText = rightPanel(wrapper).text()
    // carol 不在任何组 → 出现；alice/bob/root 已有归属 → 不出现在未分组面板
    expect(panelText).toContain('carol')
    expect(panelText).not.toContain('alice')
    expect(panelText).not.toContain('bob')
  })

  it('点击选中分组 → 右面板显示该组成员；再点同一分组 → 回落未分组用户', async () => {
    const wrapper = mountPage()
    await flushPromises()

    await treeRow(wrapper, 'g-mkt')!.trigger('click')
    await flushPromises()
    expect(treeRow(wrapper, 'g-mkt')!.attributes('data-selected')).toBe('1')
    expect(rightPanel(wrapper).find('.panel-title').text()).toContain('市场组')
    expect(rightPanel(wrapper).text()).toContain('alice')
    expect(rightPanel(wrapper).text()).not.toContain('carol')

    await treeRow(wrapper, 'g-mkt')!.trigger('click')
    await flushPromises()
    expect(rightPanel(wrapper).find('.panel-title').text()).toContain('未分组用户')
  })

  it('行内操作按系统组收窄：系统组只有 成员/编辑，自定义组有 成员/改名/编辑/删除', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const sysLabels = treeRow(wrapper, 'g-sys')!.findAll('button.node-action').map(b => b.text())
    expect(sysLabels).toEqual(['成员', '编辑'])

    const customLabels = treeRow(wrapper, 'g-mkt')!.findAll('button.node-action').map(b => b.text())
    expect(customLabels).toEqual(['成员', '重命名', '编辑', '删除'])
  })

  it('成员入口点击选中分组（右面板切到该组成员）', async () => {
    const wrapper = mountPage()
    await flushPromises()

    await rowAction(wrapper, 'g-dev', '成员')!.trigger('click')
    await flushPromises()
    expect(treeRow(wrapper, 'g-dev')!.attributes('data-selected')).toBe('1')
    expect(rightPanel(wrapper).find('.panel-title').text()).toContain('研发组')
  })

  it('改名弹窗提交 updateGroup(id, { name })', async () => {
    const wrapper = mountPage()
    await flushPromises()

    await rowAction(wrapper, 'g-mkt', '重命名')!.trigger('click')
    await flushPromises()
    const renameModal = wrapper.findAll('.ant-modal').find(m => m.attributes('data-title') === '重命名')!
    const input = renameModal.find('input.a-input')
    await input.setValue('市场一部')
    await (wrapper.vm as unknown as { saveRename: () => Promise<void> }).saveRename()
    await flushPromises()

    expect(updateGroup).toHaveBeenCalledWith('g-mkt', { name: '市场一部' })
  })

  it('编辑弹窗：系统组的名称输入禁用，自定义组可用', async () => {
    const wrapper = mountPage()
    await flushPromises()

    await rowAction(wrapper, 'g-sys', '编辑')!.trigger('click')
    await flushPromises()
    const editModal = wrapper.findAll('.ant-modal').find(m => m.attributes('data-title') === '编辑')!
    expect(editModal.find('input.a-input').attributes('disabled')).toBeDefined()

    // 换开自定义组的编辑弹窗（stub 不渲染遮罩，直接点即可）
    await rowAction(wrapper, 'g-mkt', '编辑')!.trigger('click')
    await flushPromises()
    const editModal2 = wrapper.findAll('.ant-modal').find(m => m.attributes('data-title') === '编辑')!
    expect(editModal2.find('input.a-input').attributes('disabled')).toBeUndefined()
  })

  it('编辑弹窗渲染全部功能模块勾选项，已启用项预勾选', async () => {
    const wrapper = mountPage()
    await flushPromises()

    await rowAction(wrapper, 'g-mkt', '编辑')!.trigger('click')
    await flushPromises()

    const boxes = wrapper.findAll('.ant-checkbox[data-value]')
    expect(boxes.length).toBe(ALL_MODULE_KEYS.length)
    const checked = boxes.filter(b => b.attributes('data-checked') === '1').map(b => b.attributes('data-value'))
    expect(checked).toEqual(['/marketplace'])
  })

  it('分区标题带全选勾选框：勾选后该分类下模块全选，再点清空该分类', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await rowAction(wrapper, 'g-mkt', '编辑')!.trigger('click')
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
    await rowAction(wrapper, 'g-mkt', '编辑')!.trigger('click')
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
    await rowAction(wrapper, 'g-mkt', '编辑')!.trigger('click')
    await flushPromises()

    // 勾选第二个模块（默认只有 /marketplace）
    const boxes = wrapper.findAll('.ant-checkbox[data-value]')
    const second = boxes[1]
    expect(second.attributes('data-checked')).toBe('0')
    await second.trigger('click')

    // Modal stub 不渲染 footer 按钮 — 直接调用组件保存逻辑
    await (wrapper.vm as unknown as { saveGroup: () => Promise<void> }).saveGroup()
    await flushPromises()

    expect(updateGroup).toHaveBeenCalledTimes(1)
    const payload = updateGroup.mock.calls[0][1]
    expect(payload.allowed_modules).toEqual(['/marketplace', boxes[1].attributes('data-value')])
  })

  it('右面板添加成员走 addGroupMember 并刷新分组', async () => {
    const wrapper = mountPage()
    await flushPromises()

    await treeRow(wrapper, 'g-mkt')!.trigger('click')
    await flushPromises()

    const input = rightPanel(wrapper).find('input.member-input')
    await input.setValue('carol')
    const addBtn = rightPanel(wrapper).findAll('.glass-btn').find(b => b.text() === '添加成员')!
    await addBtn.trigger('click')
    await flushPromises()

    expect(addGroupMember).toHaveBeenCalledWith('g-mkt', { username: 'carol' })
    // 添加后刷新分组列表
    expect(listGroups.mock.calls.length).toBeGreaterThanOrEqual(2)
  })

  it('删除走确认弹窗后调用 deleteGroup', async () => {
    const wrapper = mountPage()
    await flushPromises()
    deleteGroup.mockResolvedValue({})

    await rowAction(wrapper, 'g-mkt', '删除')!.trigger('click')
    expect(Modal.confirm).toHaveBeenCalledTimes(1)
    const cfg = (Modal.confirm as ReturnType<typeof vi.fn>).mock.calls[0][0] as { onOk: () => Promise<void> }
    await cfg.onOk()
    await flushPromises()

    expect(deleteGroup).toHaveBeenCalledWith('g-mkt')
  })
})

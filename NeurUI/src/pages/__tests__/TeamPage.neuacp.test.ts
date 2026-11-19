/**
 * TeamPage 名册增强（ACP 外部编码代理接入 B6）
 *
 * 验收（设计文档 §5.1/§5.5）：名册读 members_detail 渲染名称/角色/执行体徽标
 * （内置 / ACP·工具 / 插件·工具，外部成员主色描边）、admin 移除成员走
 * DELETE 后刷新、外部成员配置 Tab 仅 admin 可见、外部代理状态卡仅 admin 可见。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api/modules/teams', () => ({
  listTeams: vi.fn(),
  createTeam: vi.fn().mockResolvedValue({}),
  updateTeam: vi.fn().mockResolvedValue({}),
  deleteTeam: vi.fn().mockResolvedValue({}),
  addTeamMembers: vi.fn().mockResolvedValue({}),
}))
vi.mock('@/api/modules/neuacp', () => ({
  fetchNeuacpCatalog: vi.fn().mockResolvedValue([]),
  testNeuacpConnection: vi.fn(),
  fetchNeuacpStatus: vi.fn(),
  removeTeamMember: vi.fn().mockResolvedValue({}),
}))
vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
  Modal: { confirm: vi.fn() },
}))

import TeamPage from '../TeamPage.vue'
import { message } from 'ant-design-vue'
import { listTeams } from '@/api/modules/teams'
import { removeTeamMember, fetchNeuacpStatus } from '@/api/modules/neuacp'
import { useAuthStore } from '@/stores/auth'
import zhCN from '@/i18n/locales/zh-CN'

const executorAcp = {
  kind: 'acp' as const,
  tool: 'opencode',
  transport: 'stdio' as const,
  command: ['opencode', 'acp'],
  cwd: 'E:/workspace/demo',
  env_keys: [],
  permission_mode: 'chain' as const,
  remote: null,
}
const executorPlugin = {
  kind: 'plugin' as const,
  tool: 'zcode',
  transport: 'stdio' as const,
  command: ['zcode', '--output-format', 'stream-json'],
  cwd: 'E:/workspace/demo',
  env_keys: [],
  permission_mode: 'chain' as const,
  remote: null,
}

const teamsFixture = [
  {
    id: 'team-1',
    name: '交付团队',
    description: '编码交付',
    tenant_id: 'default',
    members: ['alice', 'opencode-coder', 'zcode-coder'],
    members_detail: [
      { user_id: 'alice', name: 'alice', role: 'member', prompt: '', joined_at: 1 },
      { user_id: 'opencode-coder', name: 'opencode-coder', role: 'coder', prompt: '写补丁', joined_at: 2, executor: executorAcp },
      { user_id: 'zcode-coder', name: 'zcode-coder', role: 'coder', prompt: '跑脚本', joined_at: 3, executor: executorPlugin },
    ],
  },
]

const stubs = {
  GlassCard: {
    props: ['title', 'subtitle'],
    template: '<div class="glass-card"><h3>{{ title }}</h3><slot /></div>',
  },
  GlassButton: {
    props: ['variant', 'size', 'loading'],
    emits: ['click'],
    template: '<button class="glass-btn" @click="$emit(\'click\')"><slot /></button>',
  },
  'a-spin': { template: '<div><slot /></div>' },
  'a-empty': { props: ['description'], template: '<div class="empty">{{ description }}</div>' },
  'a-tag': { template: '<span class="tag"><slot /></span>' },
  'a-modal': {
    props: ['open', 'title', 'footer'],
    template: '<div v-if="open" class="modal"><slot /></div>',
  },
  'a-form': { template: '<form><slot /></form>' },
  'a-form-item': { props: ['label'], template: '<div class="fi"><slot /></div>' },
  'a-input': { props: ['value'], template: '<input />' },
  'a-textarea': { props: ['value'], template: '<textarea />' },
  'a-select': { props: ['value', 'mode'], template: '<select><slot /></select>' },
  'a-select-option': { props: ['value', 'disabled'], template: '<option><slot /></option>' },
  'a-popconfirm': {
    props: ['title'],
    template: '<span class="popconfirm" @click="$emit(\'confirm\')"><slot /></span>',
  },
  'a-pagination': { template: '<div class="pagination" />' },
  'a-tabs': { props: ['activeKey'], template: '<div class="tabs"><slot /></div>' },
  'a-tab-pane': { props: ['tab', 'key'], template: '<div class="tab-pane"><slot /></div>' },
}

function mountPage(role: 'admin' | 'user' = 'admin') {
  const pinia = createPinia()
  setActivePinia(pinia)
  const authStore = useAuthStore()
  authStore.user = {
    id: 'u-1',
    username: 'tester',
    email: 't@n.io',
    role,
    status: 'active',
    allowed_modules: [],
  } as any
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })
  return mount(TeamPage, { global: { plugins: [i18n, pinia], stubs } })
}

beforeEach(() => {
  vi.clearAllMocks()
  ;(listTeams as ReturnType<typeof vi.fn>).mockResolvedValue(teamsFixture)
  ;(fetchNeuacpStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
    processes: [{ pid: 42, tool: 'opencode' }],
    note: 'pool ok',
  })
})

describe('TeamPage — 名册 members_detail 渲染', () => {
  it('成员行渲染名称/角色/执行体徽标（内置 / ACP·工具 / 插件·工具）', async () => {
    const w = mountPage()
    await flushPromises()
    const text = w.text()
    expect(text).toContain('alice')
    expect(text).toContain('opencode-coder')
    expect(text).toContain('ACP·opencode')
    expect(text).toContain('插件·zcode')
    expect(text).toContain('内置')
    const badges = w.findAll('.member-badge')
    expect(badges.length).toBe(3)
    expect(w.findAll('.member-badge.is-external').length).toBe(2)
  })

  it('members_detail 缺省时回退 members 字符串数组渲染', async () => {
    ;(listTeams as ReturnType<typeof vi.fn>).mockResolvedValue([
      { id: 'team-2', name: '旧团队', members: ['bob'] },
    ])
    const w = mountPage()
    await flushPromises()
    expect(w.text()).toContain('bob')
  })
})

describe('TeamPage — 移除成员', () => {
  it('admin 确认后调 DELETE 并刷新名册', async () => {
    const w = mountPage()
    await flushPromises()
    const removeBtn = w.findAll('.member-remove .glass-btn')[0]
    expect(removeBtn).toBeTruthy()
    await removeBtn.trigger('click')
    await flushPromises()
    expect(removeTeamMember).toHaveBeenCalledTimes(1)
    expect(removeTeamMember).toHaveBeenCalledWith('team-1', 'alice')
    expect(listTeams).toHaveBeenCalledTimes(2)
    expect(message.success).toHaveBeenCalled()
  })

  it('非 admin 不显示移除按钮/外部成员入口/状态卡', async () => {
    const w = mountPage('user')
    await flushPromises()
    expect(w.findAll('.member-remove').length).toBe(0)
    expect(w.text()).not.toContain('外部代理运行状态')
    expect(fetchNeuacpStatus).not.toHaveBeenCalled()
  })
})

describe('TeamPage — 外部代理状态卡（admin）', () => {
  it('admin 挂载时拉取状态并展示进程数与说明', async () => {
    const w = mountPage()
    await flushPromises()
    expect(fetchNeuacpStatus).toHaveBeenCalledTimes(1)
    expect(w.text()).toContain('外部代理运行状态')
    expect(w.text()).toContain('1')
    expect(w.text()).toContain('pool ok')
  })

  it('状态拉取失败时诚实展示失败标注', async () => {
    ;(fetchNeuacpStatus as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('403'))
    const w = mountPage()
    await flushPromises()
    expect(w.text()).toContain('状态加载失败')
  })
})

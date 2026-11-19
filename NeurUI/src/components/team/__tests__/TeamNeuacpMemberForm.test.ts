/**
 * TeamNeuacpMemberForm —— 外部编码代理成员配置表单（ACP 接入 B6）
 *
 * 验收（设计文档 §5.2）：目录下拉（kind 标注/本机安装探测/需 Node 提示/安装指引）、
 * 启动命令预填可改、cwd 必填、成员名必填、env_keys 只录键名、
 * auto 权限模式仅 admin 且二次确认、测试连接展示握手结果/错误原文、
 * 提交经 addTeamMembers 携带 executor 全字段。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api/modules/teams', () => ({
  addTeamMembers: vi.fn().mockResolvedValue({}),
}))
vi.mock('@/api/modules/neuacp', () => ({
  fetchNeuacpCatalog: vi.fn(),
  testNeuacpConnection: vi.fn(),
  fetchNeuacpStatus: vi.fn(),
  removeTeamMember: vi.fn(),
}))
vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
  Modal: { confirm: vi.fn() },
}))

import TeamNeuacpMemberForm from '../TeamNeuacpMemberForm.vue'
import { addTeamMembers } from '@/api/modules/teams'
import { fetchNeuacpCatalog, testNeuacpConnection } from '@/api/modules/neuacp'
import { message, Modal } from 'ant-design-vue'
import { useAuthStore } from '@/stores/auth'
import zhCN from '@/i18n/locales/zh-CN'

const catalog = [
  {
    tool: 'opencode',
    known: true,
    kind: 'acp',
    origin: 'builtin',
    command: ['opencode', 'acp'],
    requires_node: false,
    disabled: false,
    installed: true,
    install_hint: '',
  },
  {
    tool: 'claude-code',
    known: true,
    kind: 'acp',
    origin: 'builtin',
    command: ['npx', '@agentclientprotocol/claude-agent-acp'],
    requires_node: true,
    disabled: false,
    installed: false,
    install_hint: 'npm i -g @agentclientprotocol/claude-agent-acp',
  },
  {
    tool: 'zcode',
    known: true,
    kind: 'plugin',
    origin: 'builtin',
    command: ['zcode', '--output-format', 'stream-json', '--no-color'],
    requires_node: false,
    disabled: false,
    installed: false,
    install_hint: 'https://z.ai/claude-code',
  },
]

const stubs = {
  GlassButton: {
    props: ['variant', 'size', 'loading'],
    emits: ['click'],
    template: '<button class="glass-btn" @click="$emit(\'click\')"><slot /></button>',
  },
  'a-form': { template: '<form><slot /></form>' },
  'a-form-item': { props: ['label'], template: '<div class="fi" :data-label="label"><slot /></div>' },
  'a-input': { props: ['value'], template: '<input class="a-input" />' },
  'a-textarea': { props: ['value'], template: '<textarea class="a-textarea" />' },
  'a-select': { props: ['value', 'mode', 'placeholder'], template: '<select class="a-select"><slot /></select>' },
  'a-select-option': {
    props: ['value', 'disabled'],
    template: '<option class="a-option" :disabled="disabled || undefined"><slot /></option>',
  },
}

function mountForm(role: 'admin' | 'user' = 'admin') {
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
  return mount(TeamNeuacpMemberForm, {
    props: { teamId: 'team-1' },
    global: { plugins: [i18n, pinia], stubs },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  ;(fetchNeuacpCatalog as ReturnType<typeof vi.fn>).mockResolvedValue(catalog)
  ;(addTeamMembers as ReturnType<typeof vi.fn>).mockResolvedValue({})
  ;(testNeuacpConnection as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true })
})

describe('TeamNeuacpMemberForm — 目录下拉', () => {
  it('挂载拉取 catalog，选项带原生/适配器/插件标注与本机安装状态', async () => {
    const w = mountForm()
    await flushPromises()
    expect(fetchNeuacpCatalog).toHaveBeenCalledTimes(1)
    const text = w.text()
    // 原生（opencode 命令首词非 npx）+ 本机可用
    expect(text).toContain('opencode')
    expect(text).toContain('原生')
    expect(text).toContain('本机可用')
    // 适配器（npx 启动）+ 需 Node + 未安装展示安装指引
    expect(text).toContain('适配器')
    expect(text).toContain('需 Node')
    expect(text).toContain('npm i -g @agentclientprotocol/claude-agent-acp')
    // 插件形态标注
    expect(text).toContain('插件')
  })

  it('选择工具后启动命令预填 catalog 默认命令', async () => {
    const w = mountForm()
    await flushPromises()
    const vm = w.vm as any
    vm.handleToolChange('zcode')
    expect(vm.form.tool).toBe('zcode')
    expect(vm.form.command).toBe('zcode --output-format stream-json --no-color')
  })
})

describe('TeamNeuacpMemberForm — 提交校验与载荷', () => {
  it('缺成员名/工作目录/启动命令时不提交并逐项警告', async () => {
    const w = mountForm()
    await flushPromises()
    const vm = w.vm as any
    vm.handleToolChange('opencode')
    vm.form.name = ''
    vm.form.cwd = ''
    vm.form.command = ''
    await vm.handleSubmit()
    expect(addTeamMembers).not.toHaveBeenCalled()
    expect(message.warning).toHaveBeenCalledTimes(3)
  })

  it('提交经 addTeamMembers 携带 executor 全字段（stdio）', async () => {
    const w = mountForm()
    await flushPromises()
    const vm = w.vm as any
    vm.handleToolChange('opencode')
    vm.form.name = 'opencode-coder'
    vm.form.role = 'coder'
    vm.form.prompt = '负责前端组件实现'
    vm.form.cwd = 'E:/workspace/demo'
    vm.form.transport = 'stdio'
    vm.form.envKeys = ['OPENCODE_API_KEY']
    vm.form.permissionMode = 'chain'
    await vm.handleSubmit()
    expect(addTeamMembers).toHaveBeenCalledTimes(1)
    const [teamId, body] = (addTeamMembers as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(teamId).toBe('team-1')
    expect(body.members).toEqual(['opencode-coder'])
    expect(body.prompt).toBe('负责前端组件实现')
    expect(body.executor).toEqual({
      kind: 'acp',
      tool: 'opencode',
      transport: 'stdio',
      command: ['opencode', 'acp'],
      cwd: 'E:/workspace/demo',
      env_keys: ['OPENCODE_API_KEY'],
      permission_mode: 'chain',
      remote: null,
    })
  })

  it('ssh 传输时 remote 携带连接参数；stdio 时 remote 为 null', async () => {
    const w = mountForm()
    await flushPromises()
    const vm = w.vm as any
    vm.handleToolChange('opencode')
    vm.form.name = 'remote-coder'
    vm.form.cwd = 'E:/workspace/demo'
    vm.form.command = 'opencode acp'
    vm.form.transport = 'ssh'
    vm.form.sshHost = '10.0.0.5'
    vm.form.sshPort = '2222'
    vm.form.sshUser = 'deploy'
    vm.form.sshKeyRef = 'ssh-deploy-key'
    await vm.handleSubmit()
    const [, body] = (addTeamMembers as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(body.executor.remote).toEqual({
      host: '10.0.0.5',
      port: 2222,
      user: 'deploy',
      key_ref: 'ssh-deploy-key',
    })
  })

  it('提交成功后发出 submitted 事件', async () => {
    const w = mountForm()
    await flushPromises()
    const vm = w.vm as any
    vm.handleToolChange('opencode')
    vm.form.name = 'coder-1'
    vm.form.cwd = 'E:/workspace/demo'
    await vm.handleSubmit()
    await flushPromises()
    expect(w.emitted('submitted')).toBeTruthy()
    expect(message.success).toHaveBeenCalled()
  })
})

describe('TeamNeuacpMemberForm — 测试连接', () => {
  it('成功展示协议版本与服务端能力', async () => {
    const w = mountForm()
    await flushPromises()
    const vm = w.vm as any
    vm.handleToolChange('opencode')
    vm.form.cwd = 'E:/workspace/demo'
    vm.form.command = 'opencode acp'
    ;(testNeuacpConnection as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      protocolVersion: '1',
      serverCapabilities: { tools: true, fs_read: true },
    })
    await vm.handleTestConnection()
    expect(testNeuacpConnection).toHaveBeenCalledTimes(1)
    const [payload] = (testNeuacpConnection as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(payload).toMatchObject({ kind: 'acp', tool: 'opencode', cwd: 'E:/workspace/demo' })
    expect(w.text()).toContain('握手成功')
    expect(w.text()).toContain('tools')
  })

  it('失败展示错误原文', async () => {
    const w = mountForm()
    await flushPromises()
    const vm = w.vm as any
    vm.handleToolChange('opencode')
    vm.form.cwd = 'E:/workspace/demo'
    vm.form.command = 'opencode acp'
    ;(testNeuacpConnection as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error('spawn opencode ENOENT'),
    )
    await vm.handleTestConnection()
    expect(vm.testResult.ok).toBe(false)
    expect(w.text()).toContain('spawn opencode ENOENT')
  })

  it('未选工具时点测试连接只警告不发请求', async () => {
    const w = mountForm()
    await flushPromises()
    const vm = w.vm as any
    vm.form.tool = ''
    await vm.handleTestConnection()
    expect(testNeuacpConnection).not.toHaveBeenCalled()
    expect(message.warning).toHaveBeenCalled()
  })
})

describe('TeamNeuacpMemberForm — 权限模式', () => {
  it('admin 选 auto 需二次确认：确认生效、取消回退审批链', async () => {
    const w = mountForm('admin')
    await flushPromises()
    const vm = w.vm as any
    expect(vm.isAdmin).toBe(true)
    vm.onPermissionModeChange('auto')
    expect(Modal.confirm).toHaveBeenCalledTimes(1)
    const cfg = (Modal.confirm as ReturnType<typeof vi.fn>).mock.calls[0][0]
    cfg.onCancel()
    expect(vm.form.permissionMode).toBe('chain')
    vm.onPermissionModeChange('auto')
    const cfg2 = (Modal.confirm as ReturnType<typeof vi.fn>).mock.calls[1][0]
    cfg2.onOk()
    expect(vm.form.permissionMode).toBe('auto')
  })

  it('非 admin auto 不可用：直接改值被拒且不弹确认', async () => {
    const w = mountForm('user')
    await flushPromises()
    const vm = w.vm as any
    expect(vm.isAdmin).toBe(false)
    vm.onPermissionModeChange('auto')
    expect(Modal.confirm).not.toHaveBeenCalled()
    expect(vm.form.permissionMode).toBe('chain')
  })
})

/**
 * CredentialManager —— SSH 多主机 + 社交平台凭据管理（登录用户自管，按用户隔离）
 *
 * 验收：挂载拉取两列表并渲染；addSSHHost 密码/私钥模式提交正确字段、缺值警告；
 * removeSSHHost 删除；saveSocialCredentials 选平台填值提交、未选平台警告。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

vi.mock('@/api/modules/settings', () => ({
  listSSHCredentials: vi.fn(),
  upsertSSHCredential: vi.fn().mockResolvedValue({}),
  deleteSSHCredential: vi.fn().mockResolvedValue({}),
  listSocialCredentials: vi.fn(),
  setSocialCredential: vi.fn().mockResolvedValue({}),
  clearSocialCredential: vi.fn().mockResolvedValue({}),
}))
vi.mock('ant-design-vue', () => ({ message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }))

import CredentialManager from '../CredentialManager.vue'
import { message } from 'ant-design-vue'
import {
  listSSHCredentials, upsertSSHCredential, deleteSSHCredential,
  listSocialCredentials, setSocialCredential,
} from '@/api/modules/settings'

const messages = {
  common: { success: '成功', error: '失败', delete: '删除' },
  settings: {
    sshHostsTitle: 'SSH 远程主机', sshHostsHint: 'h', sshHostsEmpty: '无主机', sshHost: '主机', sshUser: '用户',
    sshPort: '端口', sshAuthType: '认证', sshAuthPassword: '密码', sshAuthKey: '私钥', sshAuthAgent: '系统',
    sshPrivateKey: '私钥', sshPassword: '密码', sshAddHost: '添加主机', sshHostRequired: '请填写主机', sshCredentialRequired: '请填写凭据',
    socialCredentialsTitle: '社交平台凭据', socialCredentialsHint: 'h', socialPlatform: '平台', socialSave: '保存',
    socialConfigured: '已配置', socialNotConfigured: '未配置', socialClear: '清除', socialPlatformRequired: '请选择平台',
    socialCredentialRequired: '请填写凭据值', socialAlreadySet: '已设置',
  },
}

const stubs = {
  GlassCard: { props: ['title'], template: '<div class="gc"><h3>{{ title }}</h3><slot /><slot name="footer" /></div>' },
  GlassButton: { props: ['variant', 'size', 'loading'], emits: ['click'], template: '<button @click="$emit(\'click\')"><slot /></button>' },
  'a-form': { template: '<form><slot /></form>' },
  'a-form-item': { props: ['label'], template: '<div class="fi" :data-label="label"><slot /></div>' },
  'a-input': { props: ['value'], template: '<input />' },
  'a-input-password': { props: ['value'], template: '<input type="password" />' },
  'a-textarea': { props: ['value'], template: '<textarea />' },
  'a-input-number': { props: ['value'], template: '<input class="num" />' },
  'a-select': { props: ['value'], template: '<select><slot /></select>' },
  'a-select-option': { props: ['value'], template: '<option><slot /></option>' },
  'a-tag': { template: '<span class="tag"><slot /></span>' },
}

function mountCM() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
  return mount(CredentialManager, { global: { plugins: [i18n], stubs } })
}

describe('CredentialManager', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(listSSHCredentials as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { hosts: [{ host: '10.0.0.5', user: 'root', port: 22, auth: 'password' }] } })
    ;(listSocialCredentials as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { platforms: [{ platform: 'github', keys: [{ key: 'github_token', set: true }], configured: true }] } })
    ;(upsertSSHCredential as ReturnType<typeof vi.fn>).mockResolvedValue({})
    ;(deleteSSHCredential as ReturnType<typeof vi.fn>).mockResolvedValue({})
    ;(setSocialCredential as ReturnType<typeof vi.fn>).mockResolvedValue({})
  })

  it('挂载拉取并渲染 SSH 主机 + 社交平台状态', async () => {
    const w = mountCM()
    await flushPromises()
    expect(listSSHCredentials).toHaveBeenCalled()
    expect(listSocialCredentials).toHaveBeenCalled()
    expect(w.text()).toContain('10.0.0.5')
    expect(w.text()).toContain('root@')
    expect(w.text()).toContain('github')
    expect(w.text()).toContain('已配置')
  })

  it('addSSHHost 密码模式提交 password', async () => {
    const w = mountCM()
    await flushPromises()
    const vm = w.vm as any
    vm.sshForm = { host: '1.2.3.4', user: 'deploy', port: 22, auth: 'password', key_text: '', password: 'pw' }
    await vm.addSSHHost()
    expect(upsertSSHCredential).toHaveBeenCalledWith(expect.objectContaining({ host: '1.2.3.4', user: 'deploy', password: 'pw', key_text: '' }))
  })

  it('addSSHHost 私钥模式提交 key_text', async () => {
    const w = mountCM()
    await flushPromises()
    const vm = w.vm as any
    vm.sshForm = { host: 'h', user: 'u', port: 22, auth: 'key', key_text: 'PRIVATE', password: '' }
    await vm.addSSHHost()
    expect(upsertSSHCredential).toHaveBeenCalledWith(expect.objectContaining({ host: 'h', key_text: 'PRIVATE', password: '' }))
  })

  it('addSSHHost 缺 host 警告不提交', async () => {
    const w = mountCM()
    await flushPromises()
    const vm = w.vm as any
    vm.sshForm = { host: '', user: '', port: 22, auth: 'password', key_text: '', password: 'p' }
    await vm.addSSHHost()
    expect(upsertSSHCredential).not.toHaveBeenCalled()
    expect(message.warning).toHaveBeenCalled()
  })

  it('removeSSHHost 调删除', async () => {
    const w = mountCM()
    await flushPromises()
    await (w.vm as any).removeSSHHost('10.0.0.5')
    expect(deleteSSHCredential).toHaveBeenCalledWith('10.0.0.5')
  })

  it('saveSocialCredentials 选平台填值提交', async () => {
    const w = mountCM()
    await flushPromises()
    const vm = w.vm as any
    vm.selectSocialPlatform('github')
    vm.socialForm.credentials.github_token = 'ghp_x'
    await vm.saveSocialCredentials()
    expect(setSocialCredential).toHaveBeenCalledWith('github', { github_token: 'ghp_x' })
  })

  it('saveSocialCredentials 未选平台警告不提交', async () => {
    const w = mountCM()
    await flushPromises()
    const vm = w.vm as any
    vm.socialForm = { platform: '', credentials: { github_token: 'x' } }
    await vm.saveSocialCredentials()
    expect(setSocialCredential).not.toHaveBeenCalled()
    expect(message.warning).toHaveBeenCalled()
  })
})

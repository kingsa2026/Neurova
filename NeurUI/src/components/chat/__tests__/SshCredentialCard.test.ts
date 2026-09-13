/**
 * 会话内按需 SSH 凭据卡（SshCredentialCard）
 *
 * 验收：填 user+password 保存 → upsertSSHCredential({host,user,port,password,key_text:''}) + emit done；
 * 私钥模式提交 key_text；缺凭据值时警告不提交；取消 emit cancel。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

const upsert = vi.fn()
vi.mock('@/api/modules/settings', () => ({ upsertSSHCredential: (...a: any[]) => upsert(...a) }))
vi.mock('ant-design-vue', () => ({ message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }))

import SshCredentialCard from '../SshCredentialCard.vue'
import { message } from 'ant-design-vue'

const messages = {
  common: { success: '成功', error: '失败', cancel: '取消' },
  settings: {
    sshUser: '用户', sshPort: '端口', sshAuthType: '认证', sshAuthPassword: '密码', sshAuthKey: '私钥',
    sshPrivateKey: '私钥', sshPassword: '密码', sshAddHost: '保存', sshCredentialRequired: '请填写凭据',
  },
  chat: { sshCredentialTitle: '配置 SSH 凭据', sshCredentialHint: '首次连接 {host}' },
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
}

function mountCard(host = '10.0.0.9') {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
  return mount(SshCredentialCard, { props: { host }, global: { plugins: [i18n], stubs } })
}

describe('SshCredentialCard', () => {
  beforeEach(() => {
    upsert.mockReset().mockResolvedValue({})
    vi.clearAllMocks()
  })

  it('密码模式保存 → upsert + emit done', async () => {
    const w = mountCard()
    const vm = w.vm as any
    vm.form = { user: 'root', port: 22, auth: 'password', key_text: '', password: 'pw' }
    await vm.save()
    expect(upsert).toHaveBeenCalledWith({ host: '10.0.0.9', user: 'root', port: 22, key_text: '', password: 'pw' })
    expect(w.emitted('done')).toBeTruthy()
  })

  it('私钥模式提交 key_text', async () => {
    const w = mountCard('h2')
    const vm = w.vm as any
    vm.form = { user: 'u', port: 22, auth: 'key', key_text: 'PRIVATE', password: '' }
    await vm.save()
    expect(upsert).toHaveBeenCalledWith(expect.objectContaining({ host: 'h2', key_text: 'PRIVATE', password: '' }))
  })

  it('缺凭据值时警告不提交', async () => {
    const w = mountCard()
    const vm = w.vm as any
    vm.form = { user: 'u', port: 22, auth: 'password', key_text: '', password: '' }
    await vm.save()
    expect(upsert).not.toHaveBeenCalled()
    expect(message.warning).toHaveBeenCalled()
    expect(w.emitted('done')).toBeFalsy()
  })

  it('取消 emit cancel', async () => {
    const w = mountCard()
    ;(w.vm as any).$emit('cancel')
    expect(w.emitted('cancel')).toBeTruthy()
  })
})

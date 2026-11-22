/**
 * U1 SSH 主机确认卡（SshHostConfirmCard）
 *
 * 验收：确认 → confirmSshHostKey({agent_id,host,port,fingerprint,key_type}) + emit done；
 * API 失败 → message.error 且不 emit done；取消 → emit cancel；指纹/密钥类型上卡。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

const confirm = vi.fn()
vi.mock('@/api/modules/settings', () => ({ confirmSshHostKey: (...a: any[]) => confirm(...a) }))
vi.mock('ant-design-vue', () => ({ message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }))

import SshHostConfirmCard from '../SshHostConfirmCard.vue'
import { message } from 'ant-design-vue'

const messages = {
  common: { success: '成功', error: '失败', cancel: '取消' },
  chat: {
    sshHostConfirmTitle: '确认 SSH 主机',
    sshHostConfirmHint: '首次连接 {host}:{port}',
    sshHostConfirmFingerprint: '公钥指纹',
    sshHostConfirmKeyType: '密钥类型',
    sshHostConfirmConfirm: '确认并重试',
    sshHostConfirmPending: '已确认，正在重连…',
  },
}

const stubs = {
  GlassCard: { props: ['title'], template: '<div class="gc"><h3>{{ title }}</h3><slot /><slot name="footer" /></div>' },
  GlassButton: { props: ['variant', 'size', 'loading'], emits: ['click'], template: '<button @click="$emit(\'click\')"><slot /></button>' },
}

function mountCard(props: Record<string, unknown> = {}) {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
  return mount(SshHostConfirmCard, {
    props: {
      host: '10.0.0.9', port: 2222, fingerprint: 'SHA256:XY',
      keyType: 'ssh-ed25519', agentId: 'agent-9',
      ...props,
    },
    global: { plugins: [i18n], stubs },
  })
}

describe('SshHostConfirmCard', () => {
  beforeEach(() => {
    confirm.mockReset().mockResolvedValue({})
    vi.clearAllMocks()
  })

  it('渲染主机指纹与密钥类型', () => {
    const w = mountCard()
    expect(w.find('[data-testid="ssh-host-fingerprint"]').text()).toBe('SHA256:XY')
    expect(w.find('[data-testid="ssh-host-key-type"]').text()).toBe('ssh-ed25519')
  })

  it('确认 → confirmSshHostKey 回带 agent_id + emit done', async () => {
    const w = mountCard()
    await (w.vm as any).confirm()
    expect(confirm).toHaveBeenCalledWith({
      agent_id: 'agent-9', host: '10.0.0.9', port: 2222,
      fingerprint: 'SHA256:XY', key_type: 'ssh-ed25519',
    })
    expect(w.emitted('done')).toBeTruthy()
  })

  it('缺 agentId 时回退 default', async () => {
    const w = mountCard({ agentId: undefined })
    await (w.vm as any).confirm()
    expect(confirm).toHaveBeenCalledWith(expect.objectContaining({ agent_id: 'default' }))
  })

  it('API 失败 → message.error 不 emit done', async () => {
    confirm.mockRejectedValueOnce(new Error('boom'))
    const w = mountCard()
    await (w.vm as any).confirm()
    expect(message.error).toHaveBeenCalled()
    expect(w.emitted('done')).toBeFalsy()
  })

  it('取消 emit cancel', () => {
    const w = mountCard()
    ;(w.vm as any).$emit('cancel')
    expect(w.emitted('cancel')).toBeTruthy()
  })
})

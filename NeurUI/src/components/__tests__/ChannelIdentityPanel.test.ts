/**
 * 渠道身份绑定面板（工单 2026-10-10 批 4b）+ 其 API 客户端。
 *
 * 判据不在"渲染得好不好看"，在三条会被随手改坏的语义：
 * 1. 前端**不指定归属**：发码只带 (agent, 渠道)，body 里出现 `user_id` 就等于把
 *    "这个渠道身份算谁"交给点面板的人；
 * 2. 权限态与空态**不合并**：403 显示"无权查看"，不能退化成"还没有绑定"——
 *    后者会把权限问题伪装成空数据，用户永远想不到去要权限；
 * 3. 解绑留痕：`revoked` 行继续显示（这张表要答得出"这人以前算谁的"），
 *    且解绑动作只出现在生效中的行上。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

const listChannelIdentityBindings = vi.fn()
const issueChannelBindingCode = vi.fn()
const revokeChannelIdentityBinding = vi.fn()

vi.mock('@/api/modules/channel-configs', () => ({
  listChannelIdentityBindings: (...a: unknown[]) => listChannelIdentityBindings(...a),
  issueChannelBindingCode: (...a: unknown[]) => issueChannelBindingCode(...a),
  revokeChannelIdentityBinding: (...a: unknown[]) => revokeChannelIdentityBinding(...a),
}))

import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

import ChannelIdentityPanel from '../ChannelIdentityPanel.vue'
import zhCN from '@/i18n/locales/zh-CN'

const ACTIVE = {
  agent_id: 'kai', channel_type: 'feishu', channel_user_id: 'ou_9',
  user_id: 'u1', neuser_id: 'ne-u1', bound_by: 'bind-code', status: 'active',
  created_at: 1, updated_at: 1,
}
const REVOKED = {
  agent_id: 'kai', channel_type: 'telegram', channel_user_id: 'tg_5',
  user_id: 'u1', neuser_id: 'ne-u1', bound_by: 'bind-code', status: 'revoked',
  created_at: 1, updated_at: 2,
}

function mountPanel() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as never } })
  return mount(ChannelIdentityPanel, {
    props: { agentId: 'kai', channelTypes: ['feishu', 'telegram'] },
    global: {
      plugins: [i18n],
      stubs: {
        'a-select': {
          props: ['value', 'options'],
          emits: ['update:value', 'change'],
          template: `<select class="cid-select" :value="value"
            @change="$emit('update:value', $event.target.value); $emit('change', $event.target.value)">
            <option v-for="o in (options || [])" :key="o.value" :value="o.value">{{ o.label }}</option>
          </select>`,
        },
        'a-spin': { template: '<div><slot/></div>' },
        'a-tag': { template: '<span class="tag"><slot/></span>' },
        GlassButton: {
          props: ['disabled'],
          emits: ['click'],
          template: '<button class="gb" :disabled="disabled" @click="$emit(\'click\')"><slot/></button>',
        },
      },
    },
  })
}

describe('ChannelIdentityPanel — 列表与留痕', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    listChannelIdentityBindings.mockResolvedValue({ bindings: [ACTIVE, REVOKED] })
  })

  it('按 agent 取数，且已解绑的行继续显示（答得出"这人以前算谁的"）', async () => {
    const wrapper = mountPanel()
    await flushPromises()

    expect(listChannelIdentityBindings).toHaveBeenCalledWith('kai')
    const rows = wrapper.findAll('[data-testid="identity-row"]')
    expect(rows).toHaveLength(2)
    expect(rows[1].text()).toContain('已解绑')
  })

  it('解绑动作只出现在生效中的行上', async () => {
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.find('[data-testid="identity-revoke-ou_9"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="identity-revoke-tg_5"]').exists()).toBe(false)
  })

  it('点解绑带上 (agent, 渠道, 发送者) 三元组并重取列表', async () => {
    revokeChannelIdentityBinding.mockResolvedValue({ revoked: true })
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.find('[data-testid="identity-revoke-ou_9"]').trigger('click')
    await flushPromises()

    expect(revokeChannelIdentityBinding).toHaveBeenCalledWith({
      agent_id: 'kai', channel_type: 'feishu', channel_user_id: 'ou_9',
    })
    // 两次：首屏 + 解绑后（屏幕状态始终来自服务端那唯一事实源）
    expect(listChannelIdentityBindings).toHaveBeenCalledTimes(2)
  })
})

describe('ChannelIdentityPanel — 发码不带归属', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    listChannelIdentityBindings.mockResolvedValue({ bindings: [] })
  })

  it('发码只传 (agent, 渠道)，提示语用后端返回的原文', async () => {
    issueChannelBindingCode.mockResolvedValue({
      code: '123456', command: '绑定 123456', expires_in: 600, bound_user_id: 'u1',
    })
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.find('.cid-select').setValue('feishu')
    await wrapper.find('[data-testid="identity-issue"]').trigger('click')
    await flushPromises()

    expect(issueChannelBindingCode).toHaveBeenCalledWith('kai', 'feishu')
    expect(wrapper.find('[data-testid="identity-issued-command"]').text()).toContain('绑定 123456')
  })

  it('渠道下拉只用页面传入的已配置渠道，不前端硬编码平台名', async () => {
    const wrapper = mountPanel()
    await flushPromises()

    const options = wrapper.findAll('.cid-select option').map((o) => o.text())
    expect(options).toEqual(['feishu', 'telegram'])
  })
})

describe('ChannelIdentityPanel — 权限态不伪装成空态', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('403 说"无权查看"，且不渲染"还没有绑定"的空态', async () => {
    listChannelIdentityBindings.mockRejectedValue({ response: { status: 403 } })
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.find('[data-testid="identity-error"]').text()).toContain('无权查看')
    expect(wrapper.find('[data-testid="identity-empty"]').exists()).toBe(false)
  })

  it('真的没有绑定时才给空态，且不出错误条', async () => {
    listChannelIdentityBindings.mockResolvedValue({ bindings: [] })
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.find('[data-testid="identity-empty"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="identity-error"]').exists()).toBe(false)
  })
})

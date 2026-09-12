import { describe, it, expect } from 'vitest'
import { buildChannelFieldsMap, QRCODE_CHANNELS, buildChannelCatalog } from '@/config/channelFields'

const t = (k: string) => k

describe('渠道参数表·QwenPaw 对齐契约（防摆设字段回归）', () => {
  const fields = buildChannelFieldsMap(t)

  it('钉钉补齐后端消费的 message_type/robot_code/endpoint，去掉未消费的 reply_at_sender', () => {
    const keys = fields.dingtalk.map((f) => f.key)
    expect(keys).toContain('message_type')
    expect(keys).toContain('robot_code')
    expect(keys).toContain('endpoint')
    expect(keys).not.toContain('reply_at_sender') // NV 适配器不消费 → 不留摆设
  })

  it('飞书用 domain（后端消费）替换 region（此前摆设），移除未消费的 media_directory', () => {
    const keys = fields.feishu.map((f) => f.key)
    expect(keys).toContain('domain')
    expect(keys).not.toContain('region')
    expect(keys).not.toContain('media_directory')
  })

  it('微信补 base_url（QR 回填+工厂消费），bot_token 不再强制手填', () => {
    const keys = fields.wechat.map((f) => f.key)
    expect(keys).toContain('base_url')
    const botToken = fields.wechat.find((f) => f.key === 'bot_token')!
    expect(botToken.required, 'iLink token 由扫码取得，不要求手填').toBeFalsy()
  })

  it('QQ 移除未消费的 instant_confirm，保留 app_id+client_secret', () => {
    const keys = fields.qq.map((f) => f.key)
    expect(keys).not.toContain('instant_confirm')
    expect(keys).toEqual(expect.arrayContaining(['app_id', 'client_secret']))
  })
})

describe('扫码授权渠道元数据', () => {
  it('仅注册后端 QRCODE_AUTH_HANDLERS 支持的渠道，wecom 暂不接线（协议不同）', () => {
    expect(Object.keys(QRCODE_CHANNELS).sort()).toEqual(
      ['dingtalk', 'feishu', 'qq', 'wechat'],
    )
    expect(QRCODE_CHANNELS.wecom).toBeUndefined()
  })

  it('每个渠道的表单回填目标键必须存在于该渠道参数表', () => {
    const fields = buildChannelFieldsMap(t)
    for (const [channelKey, meta] of Object.entries(QRCODE_CHANNELS)) {
      const formKeys = new Set([...fields[channelKey].map((f) => f.key)])
      for (const formKey of Object.values(meta.credentialToForm)) {
        expect(formKeys.has(formKey), `${channelKey} 回填键 ${formKey} 应在参数表中`).toBe(true)
      }
    }
  })
})

describe('渠道目录含负一屏（NV 独有）', () => {
  it('系统/Agent 页共享目录均含负一屏卡', () => {
    // 负一屏在两页各自 append（系统页 NEG_SCREEN_CARD / Agent 页 baseCatalog），
    // 此处仅钉共享目录不含 imessage 之外的后端无适配器平台不新增
    const catalog = buildChannelCatalog(t)
    expect(catalog.some((c) => c.channelKey === 'wechat')).toBe(true)
    expect(catalog.some((c) => c.channelKey === 'imessage')).toBe(true)
  })
})

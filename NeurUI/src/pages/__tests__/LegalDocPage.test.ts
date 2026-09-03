/**
 * LegalDocPage（服务条款/隐私政策）TDD 测试（2026-09-03）
 *
 * 用户契约：
 * 1. 服务条款页：标题 + 版权保护段落（termsS3）必须出现"版权"相关内容；
 * 2. 隐私政策页：标题 + 日志/运行环境参数收集声明（privacyS3）必须出现；
 * 3. 段落经 i18n 渲染（不出现原始键名）。
 */
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

vi.mock('@/stores/app', () => ({
  useAppStore: () => ({ isDark: false }),
}))

vi.mock('@/components/StarBackground.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/GlassPanel.vue', () => ({ default: { template: '<div><slot /></div>' } }))

import LegalDocPage from '@/pages/LegalDocPage.vue'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      auth: { login: '登录' },
      legal: {
        termsTitle: '服务条款',
        termsUpdated: '更新日期：2026 年 9 月 3 日',
        termsS1: '一、总则',
        termsS1Body: '本条款适用于您对本平台的访问与使用。',
        termsS2: '二、服务内容',
        termsS2Body: '本平台提供智能对话、记忆管理、工作流编排等服务。',
        termsS3: '三、知识产权与版权保护（重点）',
        termsS3Body: '本平台及其代码、界面、文档、模型与内容，其著作权及相关权利归开发者/作者所有。您不得复制、修改或侵害平台版权。',
        termsS4: '四、用户行为规范',
        termsS4Body: '您承诺不利用本平台从事违法犯罪活动。',
        termsS5: '五、数据安全与隐私',
        termsS5Body: '您应妥善保管账号密码。',
        termsS6: '六、数据收集声明（改进依据）',
        termsS6Body: '平台会收集部分使用日志与运行环境参数，仅用于质量改进。',
        termsS7: '七、服务变更与终止',
        termsS7Body: '平台有权变更服务。',
        termsS8: '八、免责声明',
        termsS8Body: '平台在法律允许范围内不承担责任。',
        termsS9: '九、条款修改',
        termsS9Body: '平台可能修订条款。',
        termsS10: '十、联系我们',
        termsS10Body: '如有疑问请联系官方渠道。',
        privacyTitle: '隐私政策',
        privacyUpdated: '更新日期：2026 年 9 月 3 日',
        privacyS1: '一、引言',
        privacyS1Body: '我们重视您的隐私与数据安全。',
        privacyS2: '二、我们收集的信息',
        privacyS2Body: '我们收集注册信息与使用数据。',
        privacyS3: '三、使用日志与运行环境参数（改进依据）',
        privacyS3Body: '为改进产品体验，我们会记录操作系统与浏览器版本、功能使用频次、性能指标、异常堆栈等运行环境参数，不含对话正文。',
        privacyS4: '四、信息用途',
        privacyS4Body: '信息用于改进产品与保障安全。',
        privacyS5: '五、存储与保护',
        privacyS5Body: '数据存储于本地部署环境。',
        privacyS6: '六、信息的共享与披露',
        privacyS6Body: '我们不会出售您的个人信息。',
        privacyS7: '七、您的权利',
        privacyS7Body: '您有权查看、更正、导出或删除数据。',
        privacyS8: '八、政策更新',
        privacyS8Body: '政策可能适时更新。',
        privacyS9: '九、联系我们',
        privacyS9Body: '如有疑问请联系官方渠道。',
      },
    },
  },
})

const mountPage = (type: 'terms' | 'privacy') =>
  mount(LegalDocPage, {
    props: { type },
    global: { plugins: [i18n] },
  })

describe('LegalDocPage', () => {
  it('服务条款：标题与版权保护段落', () => {
    const wrapper = mountPage('terms')
    const text = wrapper.text()
    expect(text).toContain('服务条款')
    expect(text).toContain('知识产权与版权保护')
    expect(text).toContain('著作权及相关权利归开发者/作者所有')
    // 不出现原始键名
    expect(text).not.toContain('legal.termsS3')
    expect(text).not.toContain('legal.termsS3Body')
  })

  it('隐私政策：标题与日志/运行环境参数收集声明', () => {
    const wrapper = mountPage('privacy')
    const text = wrapper.text()
    expect(text).toContain('隐私政策')
    expect(text).toContain('使用日志与运行环境参数')
    expect(text).toContain('操作系统与浏览器版本')
    expect(text).not.toContain('legal.privacyS3')
    expect(text).not.toContain('legal.privacyS3Body')
  })
})

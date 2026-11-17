/**
 * S2 MonitorPage 邮箱健康卡（源级契约，同 ChatPage.upstreamSilence 取舍——
 * 页面体量与 antd 全量注册成本下，锁住"后端改了前端不会报红"的四件事）：
 * 1. 卡片数据源是既有 getMonitorResources() 响应的 mailbox 字段（不新增 API 调用）；
 * 2. 七项读数逐项消费（在途租约/待就绪/ACK/回收/去重/会话数/优先级分布）；
 * 3. mailbox 缺席（fail-soft null）时整卡不渲染——不拿零读数冒充"邮箱健康"；
 * 4. 文案键真实存在且 11 语言齐平。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const source = readFileSync(resolve(process.cwd(), 'src/pages/MonitorPage.vue'), 'utf-8')
const monitorApi = readFileSync(resolve(process.cwd(), 'src/api/modules/monitor.ts'), 'utf-8')

const LOCALES = [
  'zh-CN', 'en-US', 'ja-JP', 'ko-KR', 'de-DE', 'es-ES',
  'fr-FR', 'it-IT', 'ru-RU', 'ar-SA', 'hi-IN',
]

describe('S2 邮箱健康卡', () => {
  it('数据源为既有 resources 响应的 mailbox 字段（不新增 API 调用）', () => {
    expect(source).toContain('resources')
    expect(source).toMatch(/mailbox/)
    expect(source).toContain('getMonitorResources')
    // 不许新增第二个邮箱查询口（get 恒 3 处：resources/connections/alerts；
    // 泛型形态 api.get<T>( 也计入）
    expect(monitorApi.match(/api\.get[<(]/g)?.length).toBe(3)
  })

  it('七项读数逐项消费（leased/ready/acked/reclaimed/deduped/sessions/优先级分布）', () => {
    for (const key of ['leasedTotal', 'readyTotal', 'ackedTotal', 'reclaimedTotal', 'dedupedTotal', 'sessions', 'priorityDistribution']) {
      expect(source, `MonitorPage 缺 ${key} 读数`).toContain(key)
    }
  })

  it('mailbox 缺席时整卡不渲染（fail-soft 不拿零冒充健康）', () => {
    expect(source).toMatch(/v-if="[^"]*mailbox/)
  })
})

describe('S2 文案面', () => {
  it.each(LOCALES)('%s 有 system.mailboxHealth 与七项读数键', (locale) => {
    const file = readFileSync(resolve(process.cwd(), `src/i18n/locales/${locale}.ts`), 'utf-8')
    for (const key of ['mailboxHealth', 'mailboxLeased', 'mailboxReady', 'mailboxAcked', 'mailboxReclaimed', 'mailboxDeduped', 'mailboxSessions', 'mailboxPriorityDist', 'priorityNormal', 'priorityHigh', 'priorityUrgent']) {
      const line = file.split('\n').find((ln) => ln.includes(`${key}:`)) ?? ''
      expect(line, `${locale} 缺 system.${key}`).not.toBe('')
    }
  })
})

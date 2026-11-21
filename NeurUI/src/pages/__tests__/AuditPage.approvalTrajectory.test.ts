/**
 * S8 AuditPage 审批审计轨迹面板（源级契约，同 MonitorPage.mailboxHealth 取舍——
 * AuditPage 依赖 ontology/governance 多模块，整体挂载成本高）。
 *
 * 后端 GET /v1/audit/approvals?run_id=（admin 门）已存在，AuditPage 此前没有
 * 审批轨迹查询视图——审批链 L0/L1/L2 的请求/决定留痕在管理面不可查。
 * 本档锁住四件"后端改了前端不会报红"的事：
 * 1. 面板挂 getApprovalTrajectory（audit 模块单源），不裸写 URL；
 * 2. runId 必填——空输入不发请求（审计按 run 成对拉取，无 run 即无轨迹）；
 * 3. 请求+决定成对展示（状态徽标 decided/pending + 决定/决策人/决定时间/时延列
 *    + 展开行事件原样）；
 * 4. 文案键真实存在且 11 语言齐平。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const source = readFileSync(resolve(process.cwd(), 'src/pages/AuditPage.vue'), 'utf-8')
const auditApi = readFileSync(resolve(process.cwd(), 'src/api/modules/audit.ts'), 'utf-8')
const approvalGrantUtil = readFileSync(resolve(process.cwd(), 'src/utils/approvalGrant.ts'), 'utf-8')

const LOCALES = [
  'zh-CN', 'en-US', 'ja-JP', 'ko-KR', 'de-DE', 'es-ES',
  'fr-FR', 'it-IT', 'ru-RU', 'ar-SA', 'hi-IN',
]

describe('S8 审批审计轨迹面板', () => {
  it('面板经 audit 模块单源查询（不裸写 URL、不新开端点域）', () => {
    expect(source).toContain('getApprovalTrajectory')
    // 模块内 URL 由 BASE='/audit' + '/approvals' 拼装
    expect(auditApi).toContain("const BASE = '/audit'")
    expect(auditApi).toContain('${BASE}/approvals')
    expect(source).not.toMatch(/['"]\/audit\/approvals['"]/)
  })

  it('runId 必填——空输入不发请求', () => {
    expect(source).toMatch(/approvalAuditRunId\.value\.trim\(\)/)
    expect(source).toMatch(/if \(!runId\)[\s\S]{0,120}return/)
  })

  it('请求+决定成对展示（状态徽标+决定/决策人/决定时间/时延列+事件展开）', () => {
    for (const key of ['decided_at', 'decided_by', 'latency_ms', 'request_event', 'decision_event', "record.status === 'decided'", 'approvalAuditPending']) {
      expect(source, `AuditPage 缺成对展示字段 ${key}`).toContain(key)
    }
    expect(source).toContain('approval-audit-panel')
  })
})

describe('S8 文案面', () => {
  it.each(LOCALES)('%s 有 audit.approvalTrajectoryTitle 与成对展示键', (locale) => {
    const file = readFileSync(resolve(process.cwd(), `src/i18n/locales/${locale}.ts`), 'utf-8')
    for (const key of ['approvalTrajectoryTitle', 'approvalRunIdRequired', 'approvalAuditEmpty', 'approvalAuditLevel', 'approvalAuditStatus', 'approvalAuditDecided', 'approvalAuditPending', 'approvalAuditRequested', 'approvalAuditDecidedAt', 'approvalAuditDecision', 'approvalAuditDecidedBy', 'approvalAuditLatency', 'approvalAuditRequestEvent', 'approvalAuditDecisionEvent']) {
      const line = file.split('\n').find((ln) => ln.includes(`${key}:`)) ?? ''
      expect(line, `${locale} 缺 audit.${key}`).not.toBe('')
    }
  })
})

/**
 * D1 记忆式放行徽标（批三配套展示层）：裁决记录里 decision_source="memory_grant"
 * 或裁决人标记 "memory_grant:<grant_id>" 命中时，决策人列显示「记忆放行」小徽标，
 * title 带授权单编号；普通链路裁决不渲染（向后兼容）。
 */
describe('S8 审批轨迹记忆放行徽标', () => {
  it('决策人列按 memoryGrantOf 识别记忆放行并渲染徽标', () => {
    expect(source).toContain('memoryGrantOf')
    // title 文案收口在共享 util（t 注入），页面只负责接线
    expect(source).toContain('memoryGrantTitleOf')
    expect(source).toContain('memory-grant-chip')
    expect(source).toContain('audit.memoryGrantBadge')
    expect(approvalGrantUtil).toContain('audit.memoryGrantTitle')
  })

  it('识别器收口在共享 util（AuditPage 与协作档案同源，不各写各的）', () => {
    expect(source).toContain("from '@/utils/approvalGrant'")
  })

  it.each(LOCALES)('%s 有 audit.memoryGrantBadge 与 memoryGrantTitle 文案', (locale) => {
    const file = readFileSync(resolve(process.cwd(), `src/i18n/locales/${locale}.ts`), 'utf-8')
    for (const key of ['memoryGrantBadge', 'memoryGrantTitle']) {
      const line = file.split('\n').find((ln) => ln.includes(`${key}:`)) ?? ''
      expect(line, `${locale} 缺 audit.${key}`).not.toBe('')
    }
  })
})

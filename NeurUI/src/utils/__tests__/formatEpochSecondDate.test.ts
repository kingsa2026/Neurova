import { describe, expect, it } from 'vitest'
import { formatEpochSecondDate } from '../displayText'

/**
 * 知识库文档"创建时间全一样且与实际不符"的回归钉（N-约定：epoch 秒）。
 *
 * 根因：后端 created_at/updated_at 契约是秒级 epoch（KnowledgeItem/files_api
 * 均为 float），页面私有 formatDate 直接 `new Date(秒值)` —— JS 按毫秒解析，
 * 全部落在 1970-01-21 同一天。本测试钉住单源函数必须按秒 ×1000 解析。
 */
describe('formatEpochSecondDate', () => {
  it('treatsEpochSecondsAsSecondsNotMilliseconds', () => {
    // 1791279148.074471 = 2026-09-18 前后（本地时区）；按毫秒解析会落 1970-01-21
    const out = formatEpochSecondDate(1791279148.074471)
    expect(out).not.toContain('1970')
    expect(out).toContain('2026')
  })

  it('rendersDistinctDatesForDistinctValues', () => {
    // 相邻两条不同时间不得渲染成同一日期（"全一样"症状的反向钉）
    const a = formatEpochSecondDate(1791279148.074471)
    const b = formatEpochSecondDate(1791279148.074471 + 86400)
    expect(a).not.toBe(b)
  })

  it('emptyValueRendersTablePlaceholder', () => {
    expect(formatEpochSecondDate(undefined)).toBe('—')
    expect(formatEpochSecondDate(null)).toBe('—')
    expect(formatEpochSecondDate(0)).toBe('—')
  })
})

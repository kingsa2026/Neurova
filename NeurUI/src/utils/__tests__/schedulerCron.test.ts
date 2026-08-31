/**
 * schedulerCron 纯函数测试 — 可视化 Cron 构建器（TDD）
 *
 * 根因: 调度器创建任务 cron 用裸文本输入, 用户要求下拉频率 +
 * 周一到周日自选多选 → buildCron/parseCron 支撑可视化 UI。
 */
import { describe, expect, it } from 'vitest'
import { buildCron, parseCron, WEEK_DOW } from '../schedulerCron'

describe('buildCron', () => {
  it('daily: 每天按时间执行', () => {
    expect(buildCron('daily', '09:30', [], 1)).toBe('30 9 * * *')
  })

  it('weekly: 周一到周日多选生成 APScheduler dow 列表(0=周一, 升序去重)', () => {
    expect(buildCron('weekly', '08:00', [1, 3, 5], 1)).toBe('0 8 * * 0,2,4')
    expect(buildCron('weekly', '08:00', [5, 5, 1], 1)).toBe('0 8 * * 0,4')
    expect(buildCron('weekly', '08:00', [7], 1)).toBe('0 8 * * 6') // 周日 → 6
  })

  it('weekly: 未选星期退化为每天(不生成空 dow)', () => {
    expect(buildCron('weekly', '08:00', [], 1)).toBe('0 8 * * *')
  })

  it('monthly: 每月指定日', () => {
    expect(buildCron('monthly', '12:15', [], 15)).toBe('15 12 15 * *')
  })

  it('缺失时间分段安全回落 00:00', () => {
    expect(buildCron('daily', '', [], 1)).toBe('0 0 * * *')
    expect(buildCron('monthly', '08', [], 32)).toBe('0 8 31 * *') // 越界钳制
  })
})

describe('parseCron', () => {
  it('daily 标准形回填', () => {
    const p = parseCron('30 9 * * *')
    expect(p).toMatchObject({ frequency: 'daily', time: '09:30', advanced: false })
  })

  it('weekly 多星期回填(APScheduler 0=周一 → UI 1=周一)', () => {
    const p = parseCron('0 8 * * 0,2,4')
    expect(p).toMatchObject({ frequency: 'weekly', time: '08:00', weekdays: [1, 3, 5], advanced: false })
  })

  it('monthly 回填', () => {
    const p = parseCron('15 12 15 * *')
    expect(p).toMatchObject({ frequency: 'monthly', time: '12:15', dayOfMonth: 15, advanced: false })
  })

  it('无法表达的形态(间隔/范围)回退 advanced 保留原文', () => {
    expect(parseCron('*/5 * * * *').advanced).toBe(true)
    expect(parseCron('0 8 * * 1-5').advanced).toBe(true)
    expect(parseCron('bad').advanced).toBe(true)
  })

  it('weekly 单星期同样回填(APScheduler 6=周日 → UI 7)', () => {
    const p = parseCron('0 8 * * 6')
    expect(p).toMatchObject({ frequency: 'weekly', time: '08:00', weekdays: [7], advanced: false })
  })
})

describe('WEEK_DOW', () => {
  it('恒为 1..7 升序', () => {
    expect(WEEK_DOW).toEqual([1, 2, 3, 4, 5, 6, 7])
  })
})

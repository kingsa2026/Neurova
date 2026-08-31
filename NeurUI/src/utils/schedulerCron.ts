/**
 * schedulerCron — 调度 Cron 表达式的可视化构建/解析纯函数。
 *
 * 根因（用户反馈）: 创建调度任务时 Cron 表达式是裸文本输入
 * （placeholder "0 /5 * * *"）, 用户易写错且不符合直觉。
 * 改进为可视化构建: 调度频率下拉(每天/每周/每月) + 时间选择 +
 * 每周循环周一到周日自选(多选) / 每月日期选择。
 *
 * 星期语义（重要）: UI 用 1=周一 .. 7=周日; APScheduler CronTrigger 的
 * day_of_week 数字为 0=周一 .. 6=周日。构建时须 aps = dow - 1,
 * 解析时须 dow = aps + 1, 否则"周一"会偏移成周二(调度错位)。
 *
 * 契约:
 *   1. buildCron:
 *      - daily:         m h * * *
 *      - weekly:        m h * * <aps-dow>(0=周一,升序去重)
 *      - monthly:       m h <day> * *
 *   2. parseCron(编辑回填):
 *      - 标准 daily/weekly/monthly 形态回填频率+时间+星期/日期;
 *      - 其他形态(如 /5 间隔、字段含范围)回退 advanced 模式保留原文,
 *        用户仍可再编辑(编辑框存在)。
 *   3. 周序常量 WEEK_DOW = [1..7](UI 序)。
 */

export type CronFrequency = 'daily' | 'weekly' | 'monthly'

export interface CronParsed {
  frequency: CronFrequency
  /** HH:mm */
  time: string
  /** 1=周一 ... 7=周日 */
  weekdays: number[]
  /** 每月第几日 1-31 */
  dayOfMonth: number
  /** 无法可视化表达的表达式: 保留原文由用户高级编辑 */
  advanced: boolean
}

export const WEEK_DOW = [1, 2, 3, 4, 5, 6, 7]

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

export function buildCron(
  frequency: CronFrequency,
  time: string,
  weekdays: number[],
  dayOfMonth: number,
): string {
  const [hour, minute = 0] = time.split(':').map((v) => parseInt(v, 10))
  const h = Number.isFinite(hour) ? hour : 0
  const m = Number.isFinite(minute) ? minute : 0
  if (frequency === 'daily') {
    return `${m} ${h} * * *`
  }
  if (frequency === 'weekly') {
    const dow = [...new Set(weekdays)].filter((d) => d >= 1 && d <= 7).sort((a, b) => a - b)
    if (dow.length === 0) return `${m} ${h} * * *` // 未选星期时退化为每天
    // APScheduler day_of_week 数字: 0=周一..6=周日
    const apsDow = dow.map((d) => d - 1)
    return `${m} ${h} * * ${apsDow.join(',')}`
  }
  // monthly
  const day = Math.min(31, Math.max(1, Math.floor(Number.isFinite(dayOfMonth) ? dayOfMonth : 1)))
  return `${m} ${h} ${day} * *`
}

/** 纯整数分段(无 /x 间隔、范围、逗号) 才可可视化 */
function isPlainField(field: string): boolean {
  return /^\d+$/.test(field.trim())
}

export function parseCron(cron: string): CronParsed {
  const fallback: CronParsed = {
    frequency: 'daily',
    time: '09:00',
    weekdays: [],
    dayOfMonth: 1,
    advanced: true,
  }
  if (!cron) return { ...fallback, time: '09:00', advanced: false }
  const parts = cron.trim().split(/\s+/)
  if (parts.length !== 5) return fallback
  const [min, hour, day, month, dow] = parts
  if (!isPlainField(min) || !isPlainField(hour)) return fallback
  const mm = pad(Math.min(59, parseInt(min, 10)))
  const hh = pad(Math.min(23, parseInt(hour, 10)))

  // 每周: 日/月为 * 且星期字段为逗号列表 或 单数字(APScheduler 数字 0=周一)
  if (day === '*' && month === '*' && /^[\d,]+$/.test(dow)) {
    const weekdays = [...new Set(dow.split(',').map((v) => parseInt(v, 10) + 1))]
      .filter((d) => d >= 1 && d <= 7)
      .sort((a, b) => a - b)
    if (weekdays.length > 0) {
      return { frequency: 'weekly', time: `${hh}:${mm}`, weekdays, dayOfMonth: 1, advanced: false }
    }
  }
  // 每月: dow 为 * 且日为纯数字
  if (month === '*' && dow === '*' && isPlainField(day)) {
    const d = Math.min(31, Math.max(1, parseInt(day, 10)))
    return { frequency: 'monthly', time: `${hh}:${mm}`, weekdays: [], dayOfMonth: d, advanced: false }
  }
  // 每天: 日/月/周 均为 *
  if (day === '*' && month === '*' && dow === '*') {
    return { frequency: 'daily', time: `${hh}:${mm}`, weekdays: [], dayOfMonth: 1, advanced: false }
  }
  return { ...fallback, time: `${hh}:${mm}` }
}

/** 与后端 cron 字段兼容: 数字星期转人类可读(1=周一) */
export function weekdayLabelKey(dow: number): string {
  const map: Record<number, string> = {
    1: 'scheduler.monday',
    2: 'scheduler.tuesday',
    3: 'scheduler.wednesday',
    4: 'scheduler.thursday',
    5: 'scheduler.friday',
    6: 'scheduler.saturday',
    7: 'scheduler.sunday',
  }
  return map[dow] ?? 'scheduler.monday'
}

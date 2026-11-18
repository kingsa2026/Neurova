/**
 * S6/S15 压缩参数展示面契约（源级，与 ChatPage.contextCompact 同一取舍）。
 *
 * 后端 /v1/context/stats 已带 compression 压缩纪律参数（triggerRatio/
 * softTargetTokens/cooldownSteps，具名常量直读），设置页此前无消费页——
 * 参数展示无数据源。本档锁住四件"后端给了前端不接就报红"的事：
 * 1. 设置页真实拉取 getContextStats（数据源接通，不是写死的第二份常量）；
 * 2. 高级页渲染压缩参数卡片；
 * 3. 三个参数（触发水位/软目标/冷却步长）全部上屏；
 * 4. 文案键真实存在且 11 语言齐平。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const source = readFileSync(resolve(process.cwd(), 'src/pages/SettingPage.vue'), 'utf-8')

const LOCALES = [
  'zh-CN', 'en-US', 'ja-JP', 'ko-KR', 'de-DE', 'es-ES',
  'fr-FR', 'it-IT', 'ru-RU', 'ar-SA', 'hi-IN',
]

const KEYS = [
  'contextCompressionTitle',
  'contextCompressionHint',
  'contextCompressionTriggerRatio',
  'contextCompressionSoftTarget',
  'contextCompressionCooldownSteps',
]

describe('S6/S15 设置页压缩参数卡片', () => {
  it('数据源接通 getContextStats（不写死第二份常量）', () => {
    expect(source).toContain('getContextStats')
  })

  it('高级页渲染压缩参数卡片（contextCompressionTitle）', () => {
    expect(source).toContain("t('settings.contextCompressionTitle')")
  })

  it('三参数全部上屏（触发水位/软目标/冷却步长）', () => {
    expect(source).toContain('contextCompressionTriggerRatio')
    expect(source).toContain('contextCompressionSoftTarget')
    expect(source).toContain('contextCompressionCooldownSteps')
    expect(source).toContain('compressionStats')
  })
})

describe('S6/S15 压缩参数文案 11 locale 齐平', () => {
  it.each(LOCALES)('%s 五键齐平', (locale) => {
    const file = readFileSync(resolve(process.cwd(), `src/i18n/locales/${locale}.ts`), 'utf-8')
    for (const key of KEYS) {
      const line = file.split('\n').find((ln) => ln.includes(`${key}:`)) ?? ''
      expect(line, `${locale} 缺 ${key}`).not.toBe('')
    }
  })
})

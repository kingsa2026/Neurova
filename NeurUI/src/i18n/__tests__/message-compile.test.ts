/**
 * 语言包消息可编译性测试 — vue-i18n 编译错误防回归守卫
 *
 * 根因 (debug.mockPlaceholder 渲染崩溃):
 *   消息文本含字面量 {"answer":"mocked"} —— vue-i18n 把 { 解析为插值占位符起始
 *   token, "answer":"mocked" 不是合法标识符, 触发
 *   "Message compilation error: Invalid token in placeholder",
 *   MockEditor.vue 渲染时组件挂载抛错.
 *
 *   同类前科: 626e438 (${...} 变量引用文案), 修法为字面量插值转义 {'{'} / {'}'}.
 *
 * 契约:
 *   1. 11 个语言包的全部消息必须能被 vue-i18n runtime 翻译路径编译通过
 *      (逐 key 调用 t() 时 console.warn/error 零编译错误) —— 防止任何语言包
 *      混入未转义花括号等非法占位符语法.
 *   2. 转义后的 debug.mockPlaceholder 渲染文本必须为原始 JSON 示例
 *      ({"answer":"mocked"}), 防止转义写成双花括号或漏转义导致的显示偏差.
 */
import { describe, it, expect, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '../locales/zh-CN'
import enUS from '../locales/en-US'
import ruRU from '../locales/ru-RU'
import jaJP from '../locales/ja-JP'
import frFR from '../locales/fr-FR'
import arSA from '../locales/ar-SA'
import koKR from '../locales/ko-KR'
import esES from '../locales/es-ES'
import deDE from '../locales/de-DE'
import hiIN from '../locales/hi-IN'
import itIT from '../locales/it-IT'

type Messages = Record<string, unknown>

const locales: Record<string, Messages> = {
  'zh-CN': zhCN as Messages,
  'en-US': enUS as Messages,
  'ru-RU': ruRU as Messages,
  'ja-JP': jaJP as Messages,
  'fr-FR': frFR as Messages,
  'ar-SA': arSA as Messages,
  'ko-KR': koKR as Messages,
  'es-ES': esES as Messages,
  'de-DE': deDE as Messages,
  'hi-IN': hiIN as Messages,
  'it-IT': itIT as Messages,
}

function flatten(obj: Messages, prefix = ''): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      Object.assign(out, flatten(v as Messages, key))
    } else {
      out[key] = v as string
    }
  }
  return out
}

// createI18n 的 messages 泛型是递归 LocaleMessage 结构, 测试用 Record 扁平化值需放宽
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const looseMessages = (v: unknown): any => v

describe('locale messages are compilable by vue-i18n', () => {
  for (const [code, messages] of Object.entries(locales)) {
    it(`${code}: every message translates without compilation errors`, () => {
      const errors: string[] = []
      const collect = (...args: unknown[]): void => {
        errors.push(args.map(String).join(' '))
      }
      const errSpy = vi.spyOn(console, 'error').mockImplementation(collect)
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(collect)
      try {
        const i18n = createI18n({
          legacy: false,
          locale: code,
          fallbackLocale: 'zh-CN',
          missingWarn: false,
          fallbackWarn: false,
          messages: { [code]: looseMessages(messages) },
        })
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const t = (i18n.global as any).t
        for (const key of Object.keys(flatten(messages))) {
          t(key)
        }
      } finally {
        errSpy.mockRestore()
        warnSpy.mockRestore()
      }
      expect(errors, `${code} 存在不可编译消息 (${errors.length} 条)`).toEqual([])
    })
  }

  it('debug.mockPlaceholder renders literal JSON braces after escaping', () => {
    const i18n = createI18n({
      legacy: false,
      locale: 'zh-CN',
      messages: { 'zh-CN': looseMessages(zhCN) },
    })
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const t = (i18n.global as any).t
    expect(t('debug.mockPlaceholder')).toBe('输入 JSON，例如 {"answer":"mocked"}')
  })
})

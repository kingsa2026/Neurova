/**
 * 语言包键一致性测试 — 多语言适配完整性守卫
 *
 * 契约:
 *   1. zh-CN 为基准语言 (fallbackLocale), 所有语言的键集合必须与 zh-CN 完全一致:
 *      - 缺键 → 该语言用户看到 zh-CN 回退文本 (漏翻译)
 *      - 多键 → 死键, 增加维护负担且可能是改名残留
 *   2. 任何语言不允许存在空值 (空字符串/null/undefined),
 *      否则 UI 渲染空白标签.
 *   3. 键名必须是 camelCase 两层结构 (section.key),
 *      与现有 1500+ 键的约定一致, 防止深层嵌套导致 flatten 逻辑分叉.
 */
import { describe, it, expect } from 'vitest'
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

const refFlat = flatten(zhCN as Messages)
const refKeys = Object.keys(refFlat).sort()

describe('locale key consistency (zh-CN as reference)', () => {
  for (const [code, messages] of Object.entries(locales)) {
    if (code === 'zh-CN') continue

    it(`${code} has exactly the same key set as zh-CN`, () => {
      const flat = flatten(messages)
      const keys = new Set(Object.keys(flat))
      const missing = refKeys.filter((k) => !keys.has(k))
      const extra = [...keys].filter((k) => !(k in refFlat)).sort()
      expect(missing, `${code} 缺少 ${missing.length} 个键: ${missing.slice(0, 20).join(', ')}`).toEqual([])
      expect(extra, `${code} 多出 ${extra.length} 个死键: ${extra.slice(0, 20).join(', ')}`).toEqual([])
    })
  }
})

describe('locale value sanity', () => {
  for (const [code, messages] of Object.entries(locales)) {
    it(`${code} has no empty values`, () => {
      const flat = flatten(messages)
      const empty = Object.entries(flat)
        .filter(([, v]) => v === '' || v === null || v === undefined)
        .map(([k]) => k)
      expect(empty, `${code} 存在空值键: ${empty.slice(0, 20).join(', ')}`).toEqual([])
    })
  }

  it('zh-CN keys are two-level camelCase (section.key)', () => {
    const bad = refKeys.filter((k) => {
      const parts = k.split('.')
      return parts.length !== 2 || !/^[a-z][a-zA-Z0-9]*$/.test(parts[0]) || !/^[a-z][a-zA-Z0-9]*$/.test(parts[1])
    })
    expect(bad).toEqual([])
  })
})

// 消息可编译性守卫见 message-compile.test.ts（vue-i18n runtime 翻译路径 + 渲染契约）

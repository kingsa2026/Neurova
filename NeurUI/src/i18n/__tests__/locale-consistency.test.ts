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

/**
 * 占位符集合守卫：翻译可以改语序、改措辞，但**不能改插值名**。
 * 缺一个 → 该语言渲染出字面量 `{pinned}` 或空白；多一个 → 传参永远用不上。
 * 现查 keys 相等/非空/编译通过都看不见这一维（编译通过只证明语法合法）。
 */
function placeholders(text: string): Set<string> {
  // vue-i18n 插值：`{name}` / `{count, plural, ...}`。转义字面量 `{'x'}` 的首字符
  // 是引号，不会被下面的标识符规则收进来。
  const out = new Set<string>()
  for (const m of text.matchAll(/\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*[,}]/g)) {
    out.add(m[1])
  }
  return out
}

describe('locale placeholder consistency', () => {
  for (const [code, messages] of Object.entries(locales)) {
    if (code === 'zh-CN') continue

    it(`${code} uses exactly the same placeholders as zh-CN`, () => {
      const flat = flatten(messages)
      const mismatched: string[] = []
      for (const key of refKeys) {
        const expected = [...placeholders(refFlat[key])].sort()
        const actual = [...placeholders(flat[key] ?? '')].sort()
        if (expected.join(',') !== actual.join(',')) {
          mismatched.push(`${key}: 期望 {${expected.join(',')}} 实得 {${actual.join(',')}}`)
        }
      }
      expect(mismatched.slice(0, 20), `${code} 有 ${mismatched.length} 个键占位符漂移`).toEqual([])
    })
  }
})

/**
 * 未翻译中文值的只降不升棘轮（现状欠账，不冒充已收口）。
 *
 * 8 个语言仍有约 220 个键的值直接是中文（认证找回、通知等整段未翻）。逐条翻译
 * 是独立翻译批；这里先钉住"不许再增长"：新键在非中文语言里写中文，计数一升即红。
 * ja-JP 排除：日文汉字与中文同区间，字符判据无法区分（不假称已覆盖）。
 * 每翻完一批，把对应基线下调到新读数。
 */
const CJK_BACKLOG_BASELINE: Record<string, number> = {
  'en-US': 0,
  'ru-RU': 0,
  'fr-FR': 0,
  'ar-SA': 0,
  'ko-KR': 0,
  'es-ES': 0,
  'de-DE': 0,
  'hi-IN': 0,
  'it-IT': 0,
}

describe('untranslated Chinese values do not grow', () => {
  for (const [code, messages] of Object.entries(locales)) {
    if (code === 'zh-CN' || code === 'ja-JP') continue
    it(`${code} stays within its untranslated backlog baseline`, () => {
      const flat = flatten(messages)
      const count = Object.keys(flat).filter((k) => /[\u4e00-\u9fa5]/.test(flat[k] ?? '')).length
      expect(count, `${code} 的中文未翻键从 ${CJK_BACKLOG_BASELINE[code]} 涨到了 ${count}`)
        .toBeLessThanOrEqual(CJK_BACKLOG_BASELINE[code])
    })
  }
})

describe('locale value sanity', () => {  for (const [code, messages] of Object.entries(locales)) {
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
      // 数据词表豁免: <section>.suites.<data-id>.<field> 按 id 索引翻译词表
      // (如 benchmark.suites.reasoning-v1.name),id 是外部数据键而非 UI 命名,
      // 不适用 camelCase 规则;首段/末段仍须合规。
      if (parts.length === 4 && parts[1] === 'suites') {
        return !/^[a-z][a-zA-Z0-9]*$/.test(parts[0]) || !/^[a-z][a-zA-Z0-9]*$/.test(parts[3])
      }
      return parts.length !== 2 || !/^[a-z][a-zA-Z0-9]*$/.test(parts[0]) || !/^[a-z][a-zA-Z0-9]*$/.test(parts[1])
    })
    expect(bad).toEqual([])
  })
})

// 消息可编译性守卫见 message-compile.test.ts（vue-i18n runtime 翻译路径 + 渲染契约）

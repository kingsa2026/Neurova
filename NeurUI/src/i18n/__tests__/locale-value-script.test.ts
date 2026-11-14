/**
 * 语言包「值串语言」守卫 — 按 Unicode 文字特征做高精度检测。
 *
 * 背景：_ontologySection.ts 曾发生整段轮换污染（frFR 段整段是阿拉伯语、
 * arSA 段是意大利语、itIT 段是法语、ruRU 段是印地语、hiIN 段是俄语），
 * 既有守卫（键集合/占位符/中文残留计数）都查不出这种「值是另一门语言」的损坏。
 *
 * 契约（只保留高精度方向，避免把同形词/借词/品牌名误报成串语言）：
 *   西里尔字母只允许出现在 ru-RU；
 *   阿拉伯文只允许出现在 ar-SA；
 *   天城文只允许出现在 hi-IN；
 *   谚文只允许出现在 ko-KR；
 *   假名只允许出现在 ja-JP；
 *   CJK 汉字不允许出现在 en/fr/de/es/it/ru/ar/hi（zh/ja/ko 豁免：
 *   汉字是中文正文，也是日文汉字与韩文汉字人名等的正当成分）。
 *
 * 检测对象是 11 个语言包的**运行时扁平值**（含 ontology/knowledgeEval/canvas
 * 各分节合并后的最终值），任一语言出现不属于它的文字特征即红。
 */
import { describe, it, expect } from 'vitest'
import zhCN from '../locales/zh-CN'
import enUS from '../locales/en-US'
import jaJP from '../locales/ja-JP'
import koKR from '../locales/ko-KR'
import frFR from '../locales/fr-FR'
import deDE from '../locales/de-DE'
import esES from '../locales/es-ES'
import itIT from '../locales/it-IT'
import ruRU from '../locales/ru-RU'
import arSA from '../locales/ar-SA'
import hiIN from '../locales/hi-IN'

type Messages = Record<string, unknown>

const locales: Record<string, Messages> = {
  'zh-CN': zhCN as Messages,
  'en-US': enUS as Messages,
  'ja-JP': jaJP as Messages,
  'ko-KR': koKR as Messages,
  'fr-FR': frFR as Messages,
  'de-DE': deDE as Messages,
  'es-ES': esES as Messages,
  'it-IT': itIT as Messages,
  'ru-RU': ruRU as Messages,
  'ar-SA': arSA as Messages,
  'hi-IN': hiIN as Messages,
}

/** 文字特征 → Unicode 区段（与通用区段表一致，不含中日韩共用标点）。 */
const SCRIPT_RANGES: Record<string, Array<[number, number]>> = {
  cjk: [
    [0x4e00, 0x9fff],
    [0x3400, 0x4dbf],
    [0xf900, 0xfaff],
  ],
  kana: [
    [0x3040, 0x309f],
    [0x30a0, 0x30ff],
    [0x31f0, 0x31ff],
    [0xff66, 0xff9f],
  ],
  hangul: [
    [0xac00, 0xd7af],
    [0x1100, 0x11ff],
    [0x3130, 0x318f],
  ],
  cyrillic: [[0x0400, 0x04ff]],
  arabic: [
    [0x0600, 0x06ff],
    [0x0750, 0x077f],
    [0xfb50, 0xfdff],
    [0xfe70, 0xfeff],
  ],
  devanagari: [[0x0900, 0x097f]],
}

/** 各语言允许出现的文字特征；不在允许集内的特征即「值串了语言」。 */
const ALLOWED_SCRIPTS: Record<string, Set<string>> = {
  'zh-CN': new Set(['cjk']),
  'en-US': new Set([]),
  'ja-JP': new Set(['cjk', 'kana']),
  'ko-KR': new Set(['hangul', 'cjk']),
  'fr-FR': new Set([]),
  'de-DE': new Set([]),
  'es-ES': new Set([]),
  'it-IT': new Set([]),
  'ru-RU': new Set(['cyrillic']),
  'ar-SA': new Set(['arabic']),
  'hi-IN': new Set(['devanagari']),
}

const SCRIPT_TO_LANGUAGE: Record<string, string> = {
  cjk: 'zh/ja',
  kana: 'ja',
  hangul: 'ko',
  cyrillic: 'ru',
  arabic: 'ar',
  devanagari: 'hi',
}

function scriptsOf(text: string): Set<string> {
  const found = new Set<string>()
  for (const ch of text) {
    const cp = ch.codePointAt(0) ?? 0
    for (const [script, ranges] of Object.entries(SCRIPT_RANGES)) {
      if (ranges.some(([lo, hi]) => cp >= lo && cp <= hi)) {
        found.add(script)
      }
    }
  }
  return found
}

function flatten(obj: Messages, prefix = ''): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      Object.assign(out, flatten(v as Messages, key))
    } else {
      out[key] = String(v)
    }
  }
  return out
}

describe('locale value script sanity (no cross-language values)', () => {
  for (const [code, messages] of Object.entries(locales)) {
    it(`${code} contains only scripts allowed for its language`, () => {
      const allowed = ALLOWED_SCRIPTS[code]
      const flat = flatten(messages)
      const violations: string[] = []
      for (const [key, value] of Object.entries(flat)) {
        const bad = [...scriptsOf(value)].filter((s) => !allowed.has(s))
        if (bad.length > 0) {
          const suspects = bad.map((s) => SCRIPT_TO_LANGUAGE[s] ?? s).join('/')
          violations.push(
            `${key}: 含 ${bad.join('/')}（疑似 ${suspects}）值=${JSON.stringify(value.slice(0, 60))}`,
          )
        }
      }
      expect(
        violations.slice(0, 20),
        `${code} 有 ${violations.length} 个键的值疑似串了语言`,
      ).toEqual([])
    })
  }
})

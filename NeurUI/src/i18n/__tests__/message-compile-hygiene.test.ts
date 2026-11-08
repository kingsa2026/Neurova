/**
 * 语言包消息编译卫生守卫 — vue-i18n v11 起消息编译错误在运行时直接抛出
 *
 * 契约:
 *   1. 全部 11 个语言的每条叶子消息，必须能被 vue-i18n 的消息编译器无错编译。
 *      v10 及以前编译失败只告警并回退渲染原文；v11 的 core-base compile() 在
 *      onError 时无条件 throw SyntaxError（生产构建同样）——一条非法消息等于
 *      渲染到它的组件在运行时崩，且只有真的渲染到才会炸，静态看不见。
 *   2. 已知非法形态与正字：
 *      - 字面 `@`（linked 消息前缀是保留字）必须写成 {'@'}
 *      - 字面 `{`/`}`（会被当占位符解析）必须写成 {'{'} / {'}'}
 *      两类各在本仓真实出现过一次（渠道页夹具裸 @、KnowledgePage 夹具裸花括号），
 *      升级 v11 时被暴露为测试红。本守卫把「能编译」钉成 CI 判据，防止新增文案
 *      再埋运行时炸弹。
 */
import { describe, it, expect } from 'vitest'
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

describe('locale message compile hygiene (v11 compiler throws at runtime)', () => {
  for (const [code, messages] of Object.entries(locales)) {
    it(`${code}: 每条消息都能无错编译（编译失败 = 运行时 throw）`, () => {
      const flat = flatten(messages)
      expect(Object.keys(flat).length).toBeGreaterThan(500)
      const i18n = createI18n({ legacy: false, locale: code, messages })
      const broken: string[] = []
      for (const key of Object.keys(flat)) {
        try {
          i18n.global.t(key)
        } catch (err) {
          broken.push(`${key}: ${err instanceof Error ? err.message.split('\n')[0] : String(err)}`)
        }
      }
      expect(broken).toEqual([])
    })
  }
})

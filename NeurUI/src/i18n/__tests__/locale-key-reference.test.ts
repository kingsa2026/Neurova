/**
 * 语言包键引用一致性测试 — 「源码引用键必须存在于 zh-CN」守卫
 *
 * 根因（runtime [intlify] Not found warning）:
 *   CanvasDesignerPage i18nOpts(['friendly', 'canvas.optToneFriendly']) 与
 *   t('chat.asrRestartLimit') 等引用了语言包中不存在的键——
 *   两个现有守卫均不覆盖: locale-consistency 只比 11 语言键集互相一致,
 *   message-compile 只编译「存在的消息」, 缺失键仅运行时 warn + UI 显示 raw key。
 *
 * 契约:
 *   1. NeurUI/src 全部源码中 t('key') / i18nOpts 字面量键引用必须存在于
 *      zh-CN 语言包（含 _canvasStores 合并键）——缺失即红, 防「引用未定义键」回归。
 *   2. 其余 10 语言的对齐由 locale-consistency.test.ts 守卫。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import zhCN from '../locales/zh-CN'
import { STORE_CANVAS } from '../locales/_canvasStores'

type Messages = Record<string, unknown>

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

const refKeys = new Set([
  ...Object.keys(flatten(zhCN as Messages)),
  ...Object.keys(STORE_CANVAS).map((k) => `canvas.${k}`),
])

function walk(dir: string): string[] {
  const out: string[] = []
  for (const f of readdirSync(dir)) {
    if (f === '__tests__' || f === 'node_modules') continue
    // 隐藏目录（如 .mimosa 编辑器工具状态快照）是工具产物不是源码——
    // 其内部示例片段会被误当 t() 引用导致守卫假红（2026-09-16 全量回归实锤）
    if (f.startsWith('.')) continue
    const p = join(dir, f)
    if (statSync(p).isDirectory()) {
      out.push(...walk(p))
    } else if (/\.(vue|ts)$/.test(f) && !/\.(test|spec)\.ts$/.test(f)) {
      // 测试文件不是运行时源码：其内部的 t('key') 字面量（报错文案示例、
      // mock 断言）会被误当源码引用——如 hardcoded-copy 守卫自身的提示文案
      // 含 t('key') 曾致本守卫假红（2026-09-16 全量回归实锤）
      out.push(p)
    }
  }
  return out
}

describe('source-referenced i18n keys exist in zh-CN', () => {
  it('所有 t() / i18nOpts 字面量键引用均有对应语言包键', () => {
    const srcRoot = join(process.cwd(), 'src')
    const referenced = new Set<string>()
    for (const file of walk(srcRoot)) {
      const src = readFileSync(file, 'utf8')
      const tRe = /\bt\(\s*['"]([^'"]+)['"]\s*[),]/g
      let m: RegExpExecArray | null
      while ((m = tRe.exec(src))) referenced.add(m[1])
      const blocks = src.match(/i18nOpts\(\[[\s\S]*?\]\)/g) || []
      for (const block of blocks) {
        const i18nRe = /'([a-z][a-zA-Z0-9]*\.[a-zA-Z0-9]+)'/g
        let m2: RegExpExecArray | null
        while ((m2 = i18nRe.exec(block))) referenced.add(m2[1])
      }
    }
    const missing = [...referenced].filter((k) => !refKeys.has(k)).sort()
    expect(missing, `源码引用但语言包缺失 ${missing.length} 个键: ${missing.join(', ')}`).toEqual([])
  })
})

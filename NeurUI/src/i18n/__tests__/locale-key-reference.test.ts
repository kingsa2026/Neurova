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
 *   2. 键存在于语言包、但**不在引用它的那个段里**同样算错：运行时 `t('a.k')` 只在
 *      `a` 段里找 `k`，寄生在别的段里键集是全的、11 语言是一致的、上面那条也绿，
 *      用户照样看见裸键。2026-10-23 的 `skillEvo.adopt*` 整批寄生在 `skill` 段里
 *      活了整整一个批次——上一版这条守卫只查"键存不存在"，抓不到这种形状。
 *   3. 其余 10 语言的对齐由 locale-consistency.test.ts 守卫。
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

/** zh-CN 的扁平键全集（含 `_canvasStores` 换算到 `canvas.` 段的那批）。 */
function liveReferenceKeys(): Set<string> {
  return new Set([
    ...Object.keys(flatten(zhCN as Messages)),
    ...Object.keys(STORE_CANVAS).map((k) => `canvas.${k}`),
  ])
}

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

/** 源码里所有 `t('a.b')` 与 i18nOpts 块内的两段键，逐条收集（只取字面量）。 */
function collectReferencedKeys(): Set<string> {
  const srcRoot = join(process.cwd(), 'src')
  const referenced = new Set<string>()
  const tRe = /\bt\(\s*['"]([^'"]+)['"]\s*[),]/g
  const i18nRe = /'([a-z][a-zA-Z0-9]*\.[a-zA-Z0-9]+)'/g
  for (const file of walk(srcRoot)) {
    const src = readFileSync(file, 'utf8')
    let m: RegExpExecArray | null
    while ((m = tRe.exec(src))) referenced.add(m[1])
    for (const block of src.match(/i18nOpts\(\[[\s\S]*?\]\)/g) || []) {
      let m2: RegExpExecArray | null
      while ((m2 = i18nRe.exec(block))) referenced.add(m2[1])
    }
  }
  return referenced
}

describe('source-referenced i18n keys exist in zh-CN', () => {
  it('所有 t() / i18nOpts 字面量键引用均有对应语言包键', () => {
    const referenceKeys = liveReferenceKeys()
    const missing = [...collectReferencedKeys()].filter((k) => !referenceKeys.has(k)).sort()
    expect(missing, `源码引用但语言包缺失 ${missing.length} 个键: ${missing.join(', ')}`).toEqual([])
  })
})

describe('同一批文案不跨 section 寄生', () => {
  it('源码引用的每个 section.key 里，section 是该键真所在的段', () => {
    // 判据：源码写的 `a.k` 必须在 `a` 段上逐级取得到。运行时 `t('a.k')` 只在 `a` 段里
    // 找 `k`，取不到就回落成裸键；而"键集里有、只是挂在别的段"同样取不到——上一版守卫
    // 只问「全量键集里有没有」，寄生键因此全绿（2026-10-23 的 `skillEvo.adopt*` 四键
    // 整批躺在 `skill` 段里，11 语言一致、键集齐、全量查找也都命中）。
    const located = liveReferenceKeys()
    const misplaced = [...collectReferencedKeys()]
      .filter((key) => {
        const dot = key.indexOf('.')
        if (dot < 0) return false
        const section = key.slice(0, dot)
        const leaf = key.slice(dot + 1)
        // 缺键（该叶子名整个语言包里都没有）由上面那条负责，这里只判"在别的段里躺着"
        const elsewhere = [...located].some((k) => k.endsWith(`.${leaf}`))
        if (!elsewhere) return false
        // 定位到 `section` 段对象上逐级下钻——运行时 `t()` 就是这么取的
        let node: any = (zhCN as any)[section]
        for (const part of leaf.split('.')) {
          if (!node || typeof node !== 'object') return true
          node = node[part]
        }
        return typeof node === 'undefined'
      })
      .sort()
    expect(
      misplaced,
      `这些键存在但不属于引用它们的那个段（文案寄生了）: ${misplaced.join(', ')}`,
    ).toEqual([])
  })
})

/**
 * 语言读数的单一来源（台账 §6-145 裁定乙：UI 拉覆盖层 + 本人偏好）。
 *
 * 这一档钉的是三件容易各自长开的事：
 * 1. 「当前界面语言存在哪儿、谁读它」以前有两处（`i18n/index.ts` 裸 `localStorage.getItem('locale')`
 *    与 `stores/app.ts` 经 `secureStorage` 的另一处）——同一件事两份取法，改存储通道时必漏一处；
 * 2. 后端语言码（`zh`）与前端 locale（`zh-CN`）之间的映射若在各调用点各写一刀，
 *    就是 §6-140/§6-145 那条「归一口径有两份、错的那份在关键路径上」的前端版本；
 * 3. 覆盖层的键是点分路径（`nav.home.title`），展开成消息树的这一步也必须只有一处。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

import {
  DEFAULT_LOCALE,
  LOCALE_STORAGE_KEY,
  isSupportedLocale,
  overlayTreeFromEntries,
  readStoredLocaleCode,
  supportedLocales,
  uiCodeForLanguageTag,
} from '@/i18n'

const SRC_ROOT = join(__dirname, '..', '..')

/** 报告里给相对路径（绝对路径会把开发机盘符写进判据输出，本仓常驻守卫点名那种）。 */
const relative = (file: string): string => file.slice(SRC_ROOT.length + 1).replace(/\\/g, '/')

function sourceFiles(dir: string): string[] {
  const found: string[] = []
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules' || entry === '__tests__' || entry.startsWith('.')) continue
    const full = join(dir, entry)
    const st = statSync(full)
    if (st.isDirectory()) found.push(...sourceFiles(full))
    else if (/\.(ts|vue|js)$/.test(entry)) found.push(full)
  }
  return found
}

describe('当前语言的读取只有一个点', () => {
  it('reads the stored locale when it is one the UI actually ships', () => {
    localStorage.setItem(LOCALE_STORAGE_KEY, 'ja-JP')
    expect(readStoredLocaleCode()).toBe('ja-JP')
  })

  it('falls back to the default instead of trusting an unknown stored value', () => {
    localStorage.setItem(LOCALE_STORAGE_KEY, 'pt-PT')
    expect(readStoredLocaleCode()).toBe(DEFAULT_LOCALE)
  })

  it('a code the UI ships is accepted, one it does not is not', () => {
    expect(isSupportedLocale('ar-SA')).toBe(true)
    expect(isSupportedLocale('pt')).toBe(false)
    expect(isSupportedLocale('')).toBe(false)
  })

  it('exactly one file reads the persisted locale key', () => {
    const readers = sourceFiles(SRC_ROOT).filter((file) => {
      const text = readFileSync(file, 'utf-8')
      // 只认「拿这个键去读存储」这一形态，注释与测试里提到不算
      return /getItem\(\s*(['"])locale\1\s*\)/.test(text)
        || /secureStorage\.get\(\s*LOCALE_STORAGE_KEY\s*\)/.test(text)
        || /secureStorage\.get\(\s*(['"])locale\1\s*\)/.test(text)
    })
    expect(readers.map(relative)).toEqual(['i18n/index.ts'])
  })
})

describe('后端语言码 → UI locale 的映射只有一处', () => {
  it.each([
    ['zh', 'zh-CN'],
    ['en', 'en-US'],
    ['ja', 'ja-JP'],
    ['ar', 'ar-SA'],
    ['ZH-cn', 'zh-CN'],
    ['zh-CN', 'zh-CN'],
  ])('maps %s onto the shipped locale %s', (tag, code) => {
    expect(uiCodeForLanguageTag(tag)).toBe(code)
  })

  it('returns null for a language the UI does not ship instead of picking one', () => {
    // 这一条是全部映射里最要紧的：本 UI 没有 `pt` 的语言包，
    // 把它"就近"落到 zh-CN 就是替用户选了一个他没说过的语言。
    expect(uiCodeForLanguageTag('pt')).toBeNull()
    expect(uiCodeForLanguageTag('')).toBeNull()
    expect(uiCodeForLanguageTag(null)).toBeNull()
    expect(uiCodeForLanguageTag(undefined)).toBeNull()
  })

  it('every supported locale round-trips through its own primary subtag', () => {
    for (const item of supportedLocales) {
      const primary = item.code.split('-')[0]
      expect(uiCodeForLanguageTag(primary)).toBe(item.code)
    }
  })

  it('no component hand-rolls that mapping next to the single point', () => {
    const offenders = sourceFiles(SRC_ROOT)
      .filter((file) => !file.endsWith(join('i18n', 'index.ts')))
      .filter((file) => /supportedLocales\s*\.\s*find\s*\(/.test(readFileSync(file, 'utf-8')))
      .map(relative)
    expect(offenders, '第二处「按语言码找 locale」的写法：' + offenders.join(', ')).toEqual([])
  })
})

describe('覆盖层键到消息树的展开', () => {
  it('expands dotted keys into the nested tree vue-i18n addresses', () => {
    const tree = overlayTreeFromEntries([{ key: 'nav.home.title', value: '主页' }])
    expect(tree).toEqual({ nav: { home: { title: '主页' } } })
  })

  it('keeps a dot-free key at the top level', () => {
    expect(overlayTreeFromEntries([{ key: 'saveLabel', value: '存' }])).toEqual({ saveLabel: '存' })
  })

  it('merges sibling paths without clobbering the shared parent', () => {
    const tree = overlayTreeFromEntries([
      { key: 'nav.home.title', value: '主页' },
      { key: 'nav.home.subtitle', value: '副标' },
      { key: 'nav.docs.title', value: '文档' },
    ])
    expect(tree).toEqual({
      nav: { home: { title: '主页', subtitle: '副标' }, docs: { title: '文档' } },
    })
  })

  it('drops entries whose value is not a string rather than rendering an object', () => {
    // t() 拿到对象会显示成 `[object Object]`，比缺文案更难查
    const tree = overlayTreeFromEntries([
      { key: 'a', value: 'ok' },
      { key: 'b', value: 42 as unknown as string },
      { key: 'c', value: null as unknown as string },
    ])
    expect(tree).toEqual({ a: 'ok' })
  })
})

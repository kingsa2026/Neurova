/**
 * 全站硬编码色守卫 —— 扫描 `src/**\/*.vue` 的 `<style>` 块。
 *
 * 旧契约只扫 variables.css / global.css 两个文件，20+ 页面组件的 `<style scoped>`
 * 全部绕过判据（切浅色主题后图表文字/状态色对比度不足即由此穿透）。
 *
 * 白名单 = variables.css 里定义过的颜色值（3 位简写归一为 6 位）+ transparent +
 * currentColor。`var(--x, #hex)` 里的 fallback 不计入——真正生效的是令牌，fallback
 * 只是安全网；把它计入会把"颜色是否走令牌"退化成"写不写 fallback"。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve, relative } from 'node:path'

const ROOT = resolve(process.cwd(), 'src')

function walkVue(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) out.push(...walkVue(full))
    else if (name.endsWith('.vue')) out.push(full)
  }
  return out
}

const normalizeHex = (hex: string): string => {
  const lower = hex.toLowerCase()
  return lower.length === 4 ? `#${[...lower.slice(1)].map((c) => c + c).join('')}` : lower
}

const variablesCss = readFileSync(resolve(ROOT, 'styles/variables.css'), 'utf-8').replace(
  /\/\*[\s\S]*?\*\//g,
  '',
)
const tokenValues = new Set<string>()
for (const rule of variablesCss.matchAll(/--nr-[\w-]+\s*:\s*([^;]+);/g)) {
  for (const hex of rule[1].matchAll(/#[0-9a-fA-F]{3,8}\b/g)) tokenValues.add(normalizeHex(hex[0]))
}

const STYLE_BLOCK = /<style[^>]*>([\s\S]*?)<\/style>/g
const HEX = /#[0-9a-fA-F]{3,8}\b/g

/** 收集一段 CSS 中位于 `var(...)` 之外的裸色值（注释先剥离）。 */
export function findBareHexLiterals(css: string): string[] {
  const body = css.replace(/\/\*[\s\S]*?\*\//g, '')
  const varSpans: Array<[number, number]> = []
  for (const match of body.matchAll(/var\(/g)) {
    let depth = 1
    let cursor = match.index! + match[0].length
    while (cursor < body.length && depth > 0) {
      if (body[cursor] === '(') depth++
      else if (body[cursor] === ')') depth--
      cursor++
    }
    varSpans.push([match.index!, cursor])
  }
  return [...body.matchAll(HEX)]
    .filter((hex) => !varSpans.some(([start, end]) => hex.index! >= start && hex.index! < end))
    .map((hex) => hex[0])
}

function scanFiles(files: string[]): string[] {
  const violations: string[] = []
  for (const file of files) {
    const text = readFileSync(file, 'utf-8')
    for (const block of text.matchAll(STYLE_BLOCK)) {
      for (const hex of findBareHexLiterals(block[1])) {
        if (!tokenValues.has(normalizeHex(hex))) {
          violations.push(`${relative(process.cwd(), file)}: ${hex}`)
        }
      }
    }
  }
  return violations
}

describe('硬编码色守卫', () => {
  it('扫描面覆盖全部 .vue（防止 glob 失效造成假绿）', () => {
    const files = walkVue(ROOT)
    expect(files.length).toBeGreaterThan(50)
    expect(files.some((f) => f.endsWith('DashboardPage.vue'))).toBe(true)
  })

  it('变异探针：裸色值必须被识别，var() fallback 与注释不得误报', () => {
    expect(findBareHexLiterals('<style>.a { color: #123456; }</style>'.replace(/<\/?style[^>]*>/g, '')))
      .toEqual(['#123456'])
    expect(findBareHexLiterals('/* #abcdef */ .a { color: var(--nr-text-primary, #8a8a92); }')).toEqual([])
  })

  it('全部 .vue 的 style 块内无令牌之外的硬编码色值', () => {
    expect(scanFiles(walkVue(ROOT))).toEqual([])
  })
})

/**
 * i18n 硬编码 UI 文案守卫（CI 常驻，替代一次性扫描器）。
 *
 * 背景：2026-09-16 全局扫描发现多页硬编码 UI 文案（经验页 tab、ModelPage
 * 字段标签、MemoryPage 弹窗字段等），语言包 key 齐备却漏绑 → 中文界面露
 * 英文/英文界面露中文。P0/P1 已修，本测试防新增回归。
 *
 * 规则：pages/views/layouts/components/workflow/projects 下 .vue 模板与
 * script 不得出现硬编码 UI 文案：
 *   A. 模板属性 placeholder/title/label/... 的静态中文字面量
 *   B. 文本节点裸中文（无 {{ }} 插值的模板文字）
 *   C. script 段赋给 UI 语义属性/提示调用的中文字面量
 *
 * 2026-09-16 P2 收口后 WHITELIST 已清空（GlassDemo 演示标注、moss 音色
 * 标签、厂商示例 placeholder 全部转 i18n），当前零豁免。若未来确需豁免，
 * 加回 WHITELIST 时必须同步加「死条目检测」断言防行漂移。
 *
 * CI 接线：frontend job 的 `npx vitest run` 全量执行本文件（vitest include
 * 模式 src 下所有 .test/.spec 文件已覆盖 src/tests/），无需单独 job。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const SRC = join(process.cwd(), 'src')
const SCAN_DIRS = ['pages', 'views', 'layouts', 'components', 'workflow', 'projects']

/**
 * 白名单（当前为空）：文件相对路径 → 豁免的行内容片段。
 * 重新启用时必须配套死条目检测（见上方注释），防行漂移后成永久死条目。
 */
const WHITELIST: Record<string, string[]> = {}

function* walkVue(dir: string): Generator<string> {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    const st = statSync(p)
    if (st.isDirectory()) yield* walkVue(p)
    else if (name.endsWith('.vue')) yield p
  }
}

const ATTR_ZH =
  /(?<![:@.\w-])\b(placeholder|title|label|content|ok-text|cancel-text|okText|cancelText|tooltip|description|message|extra|tab|header|text)\s*=\s*"([^"{}]*[\u4e00-\u9fff][^"{}]*)"/
const TEXT_ZH = />([^<>{}]*[\u4e00-\u9fff][^<>{}]*)</
const SCRIPT_ZH =
  /\b(title|label|placeholder|content|description|message|name|text|prompt)\s*[:=]\s*(['"])([^'"]*[\u4e00-\u9fff][^'"]*)\2/

function isWhitelisted(rel: string, line: string): boolean {
  return (WHITELIST[rel] ?? []).some((frag) => line.includes(frag))
}

function isCommentLine(line: string): boolean {
  const s = line.trim()
  return (
    s.startsWith('//') || s.startsWith('*') || s.startsWith('/*') ||
    s.startsWith('<!--') || s.endsWith('-->')
  )
}

describe('i18n 守卫 — 禁止模板硬编码 UI 文案', () => {
  it('pages/views/layouts 无白名单外硬编码中文文案', () => {
    const violations: string[] = []
    for (const dir of SCAN_DIRS) {
      for (const abs of walkVue(join(SRC, dir))) {
        const rel = relative(SRC, abs).replace(/\\/g, '/')
        const lines = readFileSync(abs, 'utf-8').split(/\r?\n/)
        const scriptStart = lines.findIndex((l) => l.trim().startsWith('<script'))
        lines.forEach((line, i) => {
          if (isCommentLine(line) || isWhitelisted(rel, line)) return
          const inScript = scriptStart !== -1 && i > scriptStart
          if (!inScript && ATTR_ZH.test(line)) {
            violations.push(`${rel}:${i + 1} attr: ${line.trim().slice(0, 90)}`)
          } else if (!inScript && TEXT_ZH.test(line)) {
            violations.push(`${rel}:${i + 1} text: ${line.trim().slice(0, 90)}`)
          } else if (inScript && SCRIPT_ZH.test(line)) {
            violations.push(`${rel}:${i + 1} script: ${line.trim().slice(0, 90)}`)
          }
        })
      }
    }
    expect(
      violations,
      `发现 ${violations.length} 处硬编码中文文案（改用 t('key') 绑定；确属豁免场景的加入测试顶部 WHITELIST 并注明原因）：\n` +
        violations.slice(0, 40).join('\n'),
    ).toEqual([])
  })

  it('白名单条目必须仍然命中源文件（防行漂移后白名单成死条目）', () => {
    const dead: string[] = []
    for (const [rel, frags] of Object.entries(WHITELIST)) {
      const src = readFileSync(join(SRC, rel), 'utf-8')
      for (const frag of frags) {
        if (!src.includes(frag)) dead.push(`${rel} :: ${frag}`)
      }
    }
    expect(dead, `白名单死条目（源文件已无此行，请从 WHITELIST 移除）：\n${dead.join('\n')}`).toEqual([])
  })
})

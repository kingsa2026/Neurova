/**
 * UiIcon 装配防回归网（2026-09-08 图标统一迁移）
 *
 * 事故：ChatPage.vue / SubAgentPanel.vue 模板使用 <UiIcon> 但未 import，
 * Vue 将其当未知 HTML 元素渲染为空标签 → 头像/图标位全空白。
 * 该类错误编译期不报错（vue-tsc 对未知元素宽松）、运行时无警告，只能靠静态扫描拦截。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

const SRC = resolve(__dirname, '../..')

function walkVueFiles(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    const st = statSync(p)
    if (st.isDirectory()) out.push(...walkVueFiles(p))
    else if (name.endsWith('.vue')) out.push(p)
  }
  return out
}

/** 从 UiIcon.vue 提取 ICON_SHAPES 的合法键集 */
function iconShapeKeys(): Set<string> {
  const src = readFileSync(join(SRC, 'components', 'UiIcon.vue'), 'utf8')
  const keys = new Set<string>()
  const re = /^  ([A-Za-z0-9_]+):\s*\{/gm
  let m: RegExpExecArray | null
  while ((m = re.exec(src))) keys.add(m[1])
  return keys
}

describe('UiIcon 装配完整性', () => {
  const vueFiles = walkVueFiles(SRC)
  const keys = iconShapeKeys()

  it('使用 <UiIcon> 的组件必须 import UiIcon（缺 import = 渲染成未知空元素）', () => {
    const missing = vueFiles.filter((f) => {
      const s = readFileSync(f, 'utf8')
      const uses = /<UiIcon[\s>]/.test(s)
      const imported = /import\s+UiIcon\s+from\s+['"]@\/components\/UiIcon\.vue['"]/.test(s)
      return uses && !imported
    })
    expect(missing, `以下文件使用了 <UiIcon> 但缺 import（渲染为空白）:\n${missing.join('\n')}`).toEqual([])
  })

  it('模板中静态 name="..." 必须是 ICON_SHAPES 合法键（未知名静默降级为 file 图形）', () => {
    const bad: string[] = []
    for (const f of vueFiles) {
      const s = readFileSync(f, 'utf8')
      const re = /<UiIcon[^>]*?\sname="([A-Za-z0-9_-]+)"/g
      let m: RegExpExecArray | null
      while ((m = re.exec(s))) {
        if (!keys.has(m[1])) bad.push(`${f} -> "${m[1]}"`)
      }
    }
    expect(bad, `未知图标名（静默渲染为 file 兜底）:\n${bad.join('\n')}`).toEqual([])
  })

  it('动态 :name 的取值域（variantIcon/streamPhaseMeta/getFileIcon/DOCK_ICONS/statusIcon）必须是合法键', () => {
    // 各动态来源的返回值清单，与实现处一一对应；新增取值须同步此处
    const dynamicValues: Array<[string, string[]]> = [
      ['utils/toolCardVariant.ts variantIcon', ['monitor', 'folder', 'search', 'keyboard', 'code', 'wrench']],
      ['ChatPage streamPhaseMeta', ['radar', 'brain', 'wrench', 'edit']],
      ['ChatPage getFileIcon', ['image', 'audio', 'fileText', 'file']],
      ['utils/artifacts.ts DOCK_ICONS', ['fileText', 'browser', 'image', 'audio', 'file', 'clock', 'archive', 'monitor']],
      ['SubAgentPanel statusIcon', ['clock', 'x', 'check']],
    ]
    const bad = dynamicValues.flatMap(([label, names]) =>
      names.filter((n) => !keys.has(n)).map((n) => `${label} -> "${n}"`),
    )
    expect(bad, `动态图标名不在 ICON_SHAPES 中:\n${bad.join('\n')}`).toEqual([])
  })
})

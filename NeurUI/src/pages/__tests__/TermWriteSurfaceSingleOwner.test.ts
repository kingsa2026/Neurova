/**
 * 术语写面单一属主守卫（教义第 7 条判据：该功能在仓内只剩一处实现被消费）。
 *
 * 判据形态是「源码形态」而非文案：把注释剥掉再比，避免退役说明里出现旧名字就撞红。
 *
 * 三格各自的用意：
 * 1. 术语 REST 的 URL 只允许出现在类型化出口 `api/modules/ontology.ts`——页面各自
 *    `request.post('/knowledge/ontology/terms')` 就是双口径的起点（图谱工作台曾自带一份
 *    只有 id/kind/label/basis 的窄实现，删掉后不许复活）；
 * 2. 图谱工作台不再自带术语 CRUD，改给 Studio 的真链接——页面仍保留 2D/3D 画布、
 *    按图谱检索、实例建边、规则写面、空间页签，这些是它不可替代的部分；
 * 3. **规则写面的唯一应用内消费者仍是图谱工作台**（正检）：Studio 的推理分区只读列表，
 *    `POST/PUT/DELETE /ontology/rules` 全仓只有那一处。删它＝永久失去 REST 规则 CRUD
 *    的入口，所以这一格钉的是「不许随手删」，与第 1 格方向相反。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { resolve } from 'node:path'

const SRC = resolve(process.cwd(), 'src')

function sourceFiles(): string[] {
  const out: string[] = []
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const full = resolve(dir, name)
      if (statSync(full).isDirectory()) {
        if (name === '__tests__') continue
        walk(full)
      } else if (/\.(ts|vue)$/.test(name)) {
        out.push(full)
      }
    }
  }
  walk(SRC)
  return out
}

/** 只留代码形态：块注释与行注释整段去掉（行注释不匹配字符串里的 `//`）。 */
function codeOnly(text: string): string {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:'"`])\/\/[^\n]*/g, '$1')
}

function filesMatching(needle: string): string[] {
  return sourceFiles()
    .filter((file) => codeOnly(readFileSync(file, 'utf-8')).includes(needle))
    .map((file) => file.slice(SRC.length + 1).replace(/\\/g, '/'))
    .sort()
}

describe('术语写面单一属主', () => {
  it('术语 REST 的 URL 只在类型化出口出现一次', () => {
    const hits = filesMatching('/ontology/terms')
    expect(hits).toEqual(['api/modules/ontology.ts'])
  })

  it('图谱工作台不再自带术语 CRUD，改指本体工作台的真链接', () => {
    const page = codeOnly(readFileSync(resolve(SRC, 'pages/GraphWorkbenchPage.vue'), 'utf-8'))
    for (const banned of ['termForm', 'workbenchNewTerm', 'startEditTerm', 'deleteTerm']) {
      expect(page, `图谱工作台仍带术语写面痕迹：${banned}`).not.toContain(banned)
    }
    expect(page, '图谱工作台应给本体工作台真链接（术语声明编辑的唯一入口）').toContain('/ontology-studio')
    // 不可替代的部分不能被一起带走（布局已是力导向：radialLayout 退役）
    for (const kept of ['GraphExplorer3D', 'forceLayout', '/knowledge/graph/instances', 'GeoMapPanel']) {
      expect(page, `图谱工作台丢了它唯一实装的能力：${kept}`).toContain(kept)
    }
  })

  it('规则写面的唯一应用内消费者仍是图谱工作台（删它即失去 REST 规则 CRUD 入口）', () => {
    const hits = filesMatching('/ontology/rules')
    expect(hits).toEqual(['pages/GraphWorkbenchPage.vue'])
  })
})

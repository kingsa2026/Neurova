/**
 * 原生 <select> 禁用契约
 *
 * 根因背景：Windows Chromium 下原生 <select> 的下拉弹层是操作系统级弹窗，
 * 不吃 CSS 变量、也不跟随页面 color-scheme（跟随浏览器应用模式），
 * 暗色主题下必然白底白字（服务商类型下拉两次事故的根源）。
 *
 * 契约：页面模板一律使用 a-select（DOM 弹层，吃 global.css 玻璃主题），
 * 禁止再引入原生 <select>。新增例外必须在下方 whitelist 登记并写明理由。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

const SRC = resolve(process.cwd(), 'src')

/** 递归收集 .vue 文件。 */
function collectVueFiles(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) out.push(...collectVueFiles(full))
    else if (name.endsWith('.vue')) out.push(full)
  }
  return out
}

// 无例外的白名单；出现原生 select 即违例
const WHITELIST: string[] = []

describe('原生 <select> 禁用契约（Windows 原生弹层不可主题化）', () => {
  it('全仓 .vue 模板不得包含原生 <select 标签', () => {
    const offenders: string[] = []
    for (const file of collectVueFiles(SRC)) {
      const content = readFileSync(file, 'utf-8')
      if (/<select[\s>]/.test(content)) {
        const rel = file.replace(/\\/g, '/')
        if (!WHITELIST.some((w) => rel.endsWith(w))) offenders.push(rel)
      }
    }
    expect(offenders, `以下文件仍在使用原生 <select>，暗色主题下弹层白底白字：\n${offenders.join('\n')}`).toEqual([])
  })
})

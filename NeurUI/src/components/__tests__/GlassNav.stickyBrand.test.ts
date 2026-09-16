/**
 * GlassNav 品牌区固定契约测试（防回归）
 *
 * 需求（2026-09-16）: 左上角 logo 调大，且不跟随菜单上下滚动 —— 固定悬停。
 *
 * 根因: 滚动容器曾设在 .nr-glass-nav-content（整列含品牌区）上，
 * 菜单超长时品牌区被一起卷走。修复 = 滚动下沉到 .nr-glass-nav-items，
 * 品牌区/底部区脱离滚动流固定。
 *
 * 契约（对齐 GlassButtonLightTheme 的 compileStyle 断言先例）:
 *   1. .nr-glass-nav-content 不再是滚动容器（无 overflow-y: auto）。
 *   2. .nr-glass-nav-items 是滚动容器（overflow-y: auto + min-height: 0，
 *      flex 子项缺 min-height: 0 则无法收缩出滚动条）。
 *   3. 结构上品牌区是 items 的兄弟而非子孙（脱离滚动流）。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { compileStyle } from '@vue/compiler-sfc'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import GlassNav from '../GlassNav.vue'

// 与 themes.test.ts 一致：vitest 固定从 NeurUI 根目录启动
const SFC_PATH = resolve(process.cwd(), 'src/components/GlassNav.vue')
const sfc = readFileSync(SFC_PATH, 'utf-8')

/** 提取所有 <style ...>...</style> 块内容，按出现顺序返回 */
function extractStyleBlocks(source: string): Array<{ css: string; scoped: boolean }> {
  const blocks: Array<{ css: string; scoped: boolean }> = []
  const re = /<style\b([^>]*)>([\s\S]*?)<\/style>/g
  let m: RegExpExecArray | null
  while ((m = re.exec(source)) !== null) {
    blocks.push({ css: m[2], scoped: /\bscoped\b/.test(m[1]) })
  }
  return blocks
}

/** 编译出组件实际的全部 CSS（scoped 块带 data-v 处理，普通块原样） */
function compiledCss(): string {
  return extractStyleBlocks(sfc)
    .map(({ css, scoped }) =>
      compileStyle({ source: css, filename: 'GlassNav.vue', id: 'data-v-test', scoped }).code,
    )
    .join('\n')
}

/** 取某选择器第一条规则的声明体（scoped 编译后类名后跟 [data-v-*]，需容忍） */
function ruleBody(css: string, selector: string): string {
  const m = css.match(new RegExp(`\\.${selector}(?:\\[[^\\]]*\\])*\\s*\\{([^}]*)\\}`))
  expect(m, `编译产物中应存在 .${selector} 规则`).not.toBeNull()
  return m![1]
}

describe('GlassNav · 品牌区固定（滚动下沉到菜单区）', () => {
  const allCss = compiledCss()

  it('.nr-glass-nav-content 不再是滚动容器（logo 不随菜单滚动的根修）', () => {
    const body = ruleBody(allCss, 'nr-glass-nav-content')
    expect(body).not.toMatch(/overflow-y:\s*auto/)
    expect(body).not.toMatch(/overflow:\s*auto/)
  })

  it('.nr-glass-nav-items 是滚动容器且可收缩（overflow-y: auto + min-height: 0）', () => {
    const body = ruleBody(allCss, 'nr-glass-nav-items')
    expect(body).toMatch(/overflow-y:\s*auto/)
    expect(body).toMatch(/min-height:\s*0/)
  })

  it('结构契约：品牌区与菜单区是兄弟，品牌区不在滚动容器内部', () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const wrapper = mount(GlassNav, { props: {}, global: { plugins: [pinia] } })
    const brand = wrapper.find('.nr-glass-nav-brand')
    expect(brand.exists()).toBe(true)
    expect(brand.element.closest('.nr-glass-nav-items')).toBeNull()
  })

  // 滚动条贴齐右侧分隔栏（2026-09-16）：滚动条渲染在滚动容器 border box 右缘，
  // 须让菜单区越过 content 右内边距外扩到侧栏边框；水平内边距单源为 --nr-nav-pad-x。
  it('菜单区右缘外扩贴分隔栏（负 margin-right + 等量 padding-right，单源变量）', () => {
    const navRule = ruleBody(allCss, 'nr-glass-nav')
    expect(navRule).toMatch(/--nr-nav-pad-x:\s*12px/)
    const content = ruleBody(allCss, 'nr-glass-nav-content')
    expect(content).toMatch(/padding:\s*16px\s+var\(--nr-nav-pad-x\)/)
    const items = ruleBody(allCss, 'nr-glass-nav-items')
    expect(items).toMatch(/margin-right:\s*calc\(\s*var\(--nr-nav-pad-x\)\s*\*\s*-1\s*\)/)
    expect(items).toMatch(/padding-right:\s*var\(--nr-nav-pad-x\)/)
  })
})

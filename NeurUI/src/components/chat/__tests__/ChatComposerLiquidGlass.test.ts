/**
 * 聊天输入区液态玻璃契约测试（2026-09-16 用户需求）
 *
 * 需求:
 *   1. /chat 用户输入面板（composer shell）实现液态玻璃效果（与登录页同参数）。
 *   2. 顶入队列卡片每张单独一条液态玻璃条。
 *
 * 契约（源码级，沿用 compileStyle/readFileSync 先例）:
 *   - 两组件均 import GlassSurface，并以登录页定案参数包裹
 *     （radius 27 / backgroundOpacity 0.12 / displace 0.5 / padding 0）。
 *   - 被包裹内容自身背景必须透明，否则挡住 backdrop 折射（登录页同构）。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { compileStyle } from '@vue/compiler-sfc'

function loadSource(relPath: string): { source: string; css: string } {
  const source = readFileSync(resolve(process.cwd(), relPath), 'utf-8')
  const css = [...source.matchAll(/<style\b([^>]*)>([\s\S]*?)<\/style>/g)]
    .map(([, attrs, body]) =>
      compileStyle({ source: body, filename: relPath, id: 'data-v-test', scoped: /\bscoped\b/.test(attrs) }).code,
    )
    .join('\n')
  return { source, css }
}

/** 断言 GlassSurface 使用点带登录页定案参数 */
function expectLoginParams(fragment: string, label: string): void {
  expect(fragment, `${label}: 应设 border-radius 27`).toMatch(/:border-radius="27"/)
  expect(fragment, `${label}: 应设 background-opacity 0.12`).toMatch(/:background-opacity="0\.12"/)
  expect(fragment, `${label}: 应设 displace 0.5`).toMatch(/:displace="0\.5"/)
  expect(fragment, `${label}: padding 归零由内容自带`).toMatch(/padding="0"/)
}

describe('Composer 外壳液态玻璃', () => {
  const { source, css } = loadSource('src/components/chat/ChatComposerArea.vue')

  it('import 并包裹 .nr-composer-shell（登录页同参数）', () => {
    expect(source).toMatch(/import GlassSurface from '@\/components\/GlassSurface\.vue'/)
    const m = source.match(/<GlassSurface[\s\S]*?<div class="nr-composer-shell"/)
    expect(m, 'GlassSurface 应直接包裹 composer shell').not.toBeNull()
    expectLoginParams(m![0], 'composer')
  })

  it('shell 透明底 + 强 backdrop 模糊（2026-09-16 用户定案：通透靠糊不靠实底）', () => {
    const body = css.match(/\.nr-composer-shell(?:\[[^\]]*\])*\s*\{([^}]*)\}/)![1]
    expect(body).toMatch(/background:\s*transparent/)
    const blur = body.match(/backdrop-filter:\s*blur\((\d+(?:\.\d+)?)px\)/)
    expect(blur, 'shell 应有 backdrop-filter blur').not.toBeNull()
    expect(Number(blur![1])).toBeGreaterThanOrEqual(16)
    expect(body).toMatch(/border-radius:\s*27px/)
  })
})

describe('顶入队列卡片 = 独立液态玻璃条', () => {
  const { source, css } = loadSource('src/components/chat/QueuedMessageCards.vue')

  it('每张卡片被 GlassSurface 包裹（v-for 内，登录页同参数）', () => {
    expect(source).toMatch(/import GlassSurface from '@\/components\/GlassSurface\.vue'/)
    const m = source.match(/<GlassSurface[\s\S]*?class="nr-queue-card"/)
    expect(m, 'GlassSurface 应包裹每张队列卡片').not.toBeNull()
    expectLoginParams(m![0], 'queue-card')
  })

  it('卡片背景透明，圆角与玻璃条一致', () => {
    const body = css.match(/\.nr-queue-card(?:\[[^\]]*\])*\s*\{([^}]*)\}/)![1]
    expect(body).toMatch(/background:\s*transparent/)
    expect(body).toMatch(/border-radius:\s*27px/)
  })
})

/**
 * 玻璃外壳不得裁剪上浮弹层（2026-09-16 用户报"模型选择被遮挡"）：
 * GlassSurface 根节点 overflow:hidden 是折射裁剪所需，但 composer 内的
 * 模型级联/斜杠面板向上浮出 shell 边界 → 该实例单独放开裁剪。
 * 模型菜单弹层同时 Teleport 到 body 并以 fixed 定位锚定触发按钮
 * （surface 的 backdrop-filter 会成为 fixed 后代的包含块，留在内部
 * 遮罩只能盖住 composer 盒，点击外部无法关闭）。
 */
describe('Composer 弹层不被玻璃裁剪', () => {
  const { source, css } = loadSource('src/components/chat/ChatComposerArea.vue')

  it('composer surface 实例带类名且 CSS 覆盖 overflow: visible', () => {
    expect(source).toMatch(/<GlassSurface[^>]*class="nr-composer-glass"/)
    const body = css.match(/\.nr-glass-surface\.nr-composer-glass(?:\[[^\]]*\])*\s*\{([^}]*)\}/)
    expect(body, '应存在 composer surface 覆盖规则').not.toBeNull()
    expect(body![1]).toMatch(/overflow:\s*visible/)
  })

  it('模型菜单 Teleport 到 body，fixed 定位锚定触发按钮', () => {
    expect(source).toMatch(/<Teleport to="body">[\s\S]{0,400}?nr-model-backdrop/)
    expect(source).toMatch(/position:\s*'fixed'/)
    expect(source).toMatch(/@click="toggleModelMenu"/)
  })
})

/**
 * 聊天消息折射穿过 composer 玻璃（2026-09-16 用户需求，同侧栏渗透手法）：
 * 消息滚动区负 margin 下延进输入区背后 + 等量 padding 保证末条消息初始不被
 * 遮挡；composer 渗透量动态（textarea 自增高/队列卡/横幅），由 ChatPage
 * ResizeObserver 写入 --nr-composer-h。输入区抬 z-index 悬浮于文字之上。
 */
describe('聊天文字折射穿过输入玻璃（渗透区布局）', () => {
  const chat = loadSource('src/pages/ChatPage.vue')
  const composer = loadSource('src/components/chat/ChatComposerArea.vue')

  it('消息区下渗透：负 margin-bottom + 含 composer 高度的 padding-bottom', () => {
    const body = chat.css.match(/\.nr-chat-messages(?:\[[^\]]*\])*\s*\{([^}]*)\}/)![1]
    expect(body).toMatch(/margin-bottom:\s*calc\(\s*var\(--nr-composer-h[^)]*\)\s*\*\s*-1\s*\)/)
    expect(body).toMatch(/padding-bottom:\s*calc\([^)]*var\(--nr-composer-h/)
  })

  it('输入区悬浮于消息文字之上（relative + z-index ≥ 2）', () => {
    const body = composer.css.match(/\.nr-chat-input-area(?:\[[^\]]*\])*\s*\{([^}]*)\}/)![1]
    expect(body).toMatch(/position:\s*relative/)
    const z = body.match(/z-index:\s*(\d+)/)
    expect(z).not.toBeNull()
    expect(Number(z![1])).toBeGreaterThanOrEqual(2)
  })

  it('ChatPage 以 ResizeObserver 动态写入 --nr-composer-h', () => {
    expect(chat.source).toMatch(/new ResizeObserver\(/)
    expect(chat.source).toMatch(/setProperty\(\s*'--nr-composer-h'/)
  })
})

/**
 * 控件区实底（2026-09-16 用户反馈）：玻璃会折射背后滚动文字，按钮/菜单/输入
 * 若保持透明底则文字识别受扰 → 这些控件底改不透明面板色 --nr-bg-surface。
 */
describe('Composer 控件区不透明底防折射干扰', () => {
  const { css } = loadSource('src/components/chat/ChatComposerArea.vue')
  function ruleBody(selector: string): string {
    const m = css.match(new RegExp(`\\.${selector}(?:\\[[^\\]]*\\])*\\s*\\{([^}]*)\\}`))
    expect(m, `编译产物中应存在 .${selector} 规则`).not.toBeNull()
    return m![1]
  }

  it('工具条 pill（按钮/菜单按钮）底为不透明面板色', () => {
    expect(ruleBody('nr-composer-pill')).toMatch(/background:\s*var\(--nr-bg-surface\)/)
  })

  it('文字输入区不透明面板底（2026-09-16 二次定案：回归 surface，!important 防 global.css 玻璃刷回灌）', () => {
    const body = ruleBody('nr-chat-textarea')
    expect(body).toMatch(/background:\s*var\(--nr-bg-surface\)\s*!important/)
  })
})

/**
 * 侧栏折叠/展开居中契约测试（2026-09-16 用户需求）
 *
 * 需求:
 *   1. 展开态 logo 在液态玻璃胶囊内水平居中。
 *   2. 折叠态用户头像在底部玻璃胶囊内水平居中（ChatLayout 折叠页脚同理）。
 *
 * 断言方式沿用 compileStyle 先例（GlassButtonLightTheme）：编译 SFC 样式产物。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { compileStyle } from '@vue/compiler-sfc'

function compiledCss(relPath: string): { css: string; source: string } {
  const source = readFileSync(resolve(process.cwd(), relPath), 'utf-8')
  const css = [...source.matchAll(/<style\b([^>]*)>([\s\S]*?)<\/style>/g)]
    .map(([, attrs, body]) =>
      compileStyle({ source: body, filename: relPath, id: 'data-v-test', scoped: /\bscoped\b/.test(attrs) }).code,
    )
    .join('\n')
  return { css, source }
}

function ruleBody(css: string, selector: string): string {
  const m = css.match(new RegExp(`\\.${selector}(?:\\[[^\\]]*\\])*\\s*\\{([^}]*)\\}`))
  expect(m, `编译产物中应存在 .${selector} 规则`).not.toBeNull()
  return m![1]
}

describe('展开态 logo 居中于液态玻璃胶囊', () => {
  const { css } = compiledCss('src/components/GlassNav.vue')

  it('.nr-glass-nav-brand 水平居中（justify-content: center）', () => {
    expect(ruleBody(css, 'nr-glass-nav-brand')).toMatch(/justify-content:\s*center/)
  })
})

describe('折叠态用户头像/页脚居中', () => {
  it('MainLayout: .nr-nav-user 绑定 is-collapsed 且折叠时居中', () => {
    const { css, source } = compiledCss('src/layouts/MainLayout.vue')
    expect(source).toMatch(/class="nr-nav-user"[^>]*:class="\{\s*'is-collapsed'/)
    expect(ruleBody(css, 'nr-nav-user\\.is-collapsed')).toMatch(/justify-content:\s*center/)
  })

  it('ChatLayout: .nr-chat-sidebar-footer 绑定 is-collapsed 且折叠时居中', () => {
    const { css, source } = compiledCss('src/layouts/ChatLayout.vue')
    expect(source).toMatch(/class="nr-chat-sidebar-footer"[^>]*:class="\{\s*'is-collapsed'/)
    const body = ruleBody(css, 'nr-chat-sidebar-footer\\.is-collapsed')
    expect(body).toMatch(/justify-content:\s*center/)
    // 32px 按钮 + 8×2 内边距 = 48 高，与品牌胶囊同径成圆
    expect(body).toMatch(/padding:\s*8px\s+0/)
  })
})

/**
 * 折叠玻璃胶囊正圆契约（2026-09-16）:
 * 胶囊宽 = 折叠侧栏宽 − content 左右 padding；胶囊高 = 内容高 + 各级纵向 padding。
 * 要求 宽 == 高 == 48，且 GlassSurface radius(27) ≥ 24 才能渲染为正圆。
 */
describe('折叠态玻璃胶囊为正圆（宽=高=48）', () => {
  const vars = readFileSync(resolve(process.cwd(), 'src/styles/variables.css'), 'utf-8')
  const nav = compiledCss('src/components/GlassNav.vue')
  const logo = compiledCss('src/components/BrandLogo.vue')
  const main = compiledCss('src/layouts/MainLayout.vue')

  it('两套皮肤折叠侧栏宽均为 72px（48 圆 + 24 content padding）', () => {
    const widths = [...vars.matchAll(/--nr-sidebar-collapsed-w:\s*(\d+)px/g)].map((m) => Number(m[1]))
    expect(widths.length).toBeGreaterThanOrEqual(2)
    for (const w of widths) expect(w).toBe(72)
  })

  it('品牌胶囊: 图形 32 高 + brand 纵向 padding 8×2 = 48；折叠渗透量随之为 64', () => {
    const imgH = Number(ruleBody(logo.css, 'nr-brand-logo-img\\.is-collapsed').match(/height:\s*(\d+)px/)![1])
    const brandPadV = Number(ruleBody(nav.css, 'nr-glass-nav-brand').match(/padding:\s*(\d+)px/)![1])
    expect(imgH + brandPadV * 2).toBe(48)
    const collapsed = ruleBody(nav.css, 'nr-glass-nav\\.is-collapsed')
    expect(collapsed).toMatch(/--nr-nav-brand-bleed:\s*64px/)
    expect(collapsed).toMatch(/--nr-nav-footer-bleed:\s*64px/)
  })

  it('底部胶囊: 头像 32 + nav-user 纵向 8×2 + 玻璃页脚折叠 padding 归零 = 48', () => {
    const avatarH = Number(ruleBody(main.css, 'nr-nav-avatar').match(/width:\s*(\d+)px/)![1])
    const userPadV = Number(ruleBody(main.css, 'nr-nav-user\\.is-collapsed').match(/padding:\s*(\d+)px/)![1])
    // 折叠态页脚包装须归零纵向 padding（选择器 .nr-glass-nav.is-collapsed .nr-glass-nav-footer）
    const collapsedFoot = nav.css.match(/\.nr-glass-nav\.is-collapsed(?:\[[^\]]*\])?\s+\.nr-glass-nav-footer(?:\[[^\]]*\])*\s*\{([^}]*)\}/)
    expect(collapsedFoot, '折叠态应清零玻璃页脚纵向 padding').not.toBeNull()
    expect(collapsedFoot![1]).toMatch(/padding:\s*0/)
    expect(avatarH + userPadV * 2).toBe(48)
  })
})

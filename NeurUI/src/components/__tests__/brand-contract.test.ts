/**
 * 品牌渲染契约 · 全站点防回归（根因: 契约曾被复制到 5+ 处, iOS 皮肤失去适配）
 *
 * 品牌 logo 的唯一渲染源必须是 <BrandLogo>（皮肤 × 深浅色自适应）。
 * 任何页面/布局不得再内联 NEUROVA 图片 logo 或不带皮肤的 N 字标。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const SRC = join(__dirname, '..', '..')

const files = {
  mainLayout: join(SRC, 'layouts', 'MainLayout.vue'),
  chatLayout: join(SRC, 'layouts', 'ChatLayout.vue'),
  glassNav: join(SRC, 'components', 'GlassNav.vue'),
  login: join(SRC, 'pages', 'LoginPage.vue'),
  register: join(SRC, 'pages', 'RegisterPage.vue'),
  forgot: join(SRC, 'pages', 'ForgotPasswordPage.vue'),
  legal: join(SRC, 'pages', 'LegalDocPage.vue'),
}

function read(p: string): string {
  return readFileSync(p, 'utf8')
}

describe('品牌渲染契约 · 全站点防回归', () => {
  const surface = [
    files.mainLayout,
    files.chatLayout,
    files.glassNav,
    files.login,
    files.register,
    files.forgot,
    files.legal,
  ]

  it('所有品牌面不得再内联 NEUROVA 图片 logo', () => {
    for (const p of surface) {
      expect(read(p), `文件内不得出现内联图片 logo: ${p}`).not.toContain('NEUROVA-LOGO350')
    }
  })

  it('布局与组件品牌面必须使用 BrandLogo 组件', () => {
    for (const p of [files.mainLayout, files.chatLayout, files.glassNav]) {
      const src = read(p)
      expect(src, `已导入 BrandLogo: ${p}`).toContain('BrandLogo')
      expect(src, `已使用 <BrandLogo>: ${p}`).toContain('<BrandLogo')
    }
  })

  it('认证页品牌面必须使用 size="lg" 的 BrandLogo（大标形态）', () => {
    for (const p of [files.login, files.register, files.forgot, files.legal]) {
      const src = read(p)
      expect(src, `认证页已使用 BrandLogo: ${p}`).toContain('<BrandLogo')
      expect(src, `认证页传入 size="lg" 大标: ${p}`).toMatch(/size=["']lg["']/)
    }
  })
})
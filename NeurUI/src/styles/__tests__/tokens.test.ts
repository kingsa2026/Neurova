/**
 * 验证设计令牌（JS 侧）—— 与 variables.css 中的 CSS 变量保持同步
 *
 * 结构（2026-09-05 双皮肤共存）:
 *   skinTokens.cosmic.{dark,light} — 原版星空/DeepSeek 风格
 *   skinTokens.ios.{dark,light}    — Apple iOS Liquid Glass 风格
 */
import { describe, it, expect } from 'vitest'
import { skinTokens } from '../tokens'

describe('Design Tokens (JS 侧设计令牌)', () => {
  it('双皮肤 × 双明暗四套令牌齐全', () => {
    for (const skin of ['cosmic', 'ios'] as const) {
      for (const mode of ['dark', 'light'] as const) {
        const t = skinTokens[skin][mode]
        expect(t, `${skin}.${mode} 应有 colors`).toBeDefined()
        expect(t.colors.primary).toBeDefined()
        expect(t.radius.md).toBeDefined()
        expect(t.shadows.md).toBeDefined()
      }
    }
  })

  describe('Cosmic（原版）', () => {
    it('深色使用星云紫 #6366f1', () => {
      expect(skinTokens.cosmic.dark.colors.primary).toBe('#6366f1')
      expect(skinTokens.cosmic.dark.colors.bgDeep).toBe('#06080f')
    })

    it('浅色使用 DeepSeek 蓝 #4d6bfe', () => {
      expect(skinTokens.cosmic.light.colors.primary).toBe('#4d6bfe')
      expect(skinTokens.cosmic.light.colors.bgDeep).toBe('#f5f6f7')
    })

    it('结构令牌为小圆角 + DM Sans', () => {
      expect(skinTokens.cosmic.dark.radius.md).toBe('10px')
      expect(skinTokens.cosmic.dark.font.body).toContain('DM Sans')
    })
  })

  describe('iOS (Liquid Glass)', () => {
    it('深色使用 iOS Accent 蓝 #0a84ff', () => {
      expect(skinTokens.ios.dark.colors.primary).toBe('#0a84ff')
      expect(skinTokens.ios.dark.colors.bgDeep).toBe('#000000')
    })

    it('浅色使用 #007aff', () => {
      expect(skinTokens.ios.light.colors.primary).toBe('#007aff')
      expect(skinTokens.ios.light.colors.bgDeep).toBe('#f2f2f7')
    })

    it('结构令牌为大圆角 + SF Pro', () => {
      expect(skinTokens.ios.dark.radius.md).toBe('14px')
      expect(skinTokens.ios.dark.font.body).toContain('SF Pro')
    })
  })

  describe('只读结构', () => {
    it('在完整结构下提供默认导出（iOS 深色，兼容旧消费方）', async () => {
      const { default: dft, tokens } = await import('../tokens')
      expect(dft).toBeDefined()
      expect(tokens).toBeDefined()
      expect(tokens.colors.primary).toBeDefined()
    })
  })
})
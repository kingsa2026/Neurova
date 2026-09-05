/**
 * 验证设计令牌（JS 侧）—— 与 variables.css 中的 CSS 变量保持同步
 *
 * 2026-09-05 起主题切换为 Apple iOS Liquid Glass 风格，
 * 主色小幅量的 iOS 深色 Accent 蓝 #0a84ff、强调色 iOS Cyan #64d2ff。
 */
import { describe, it, expect } from 'vitest'
import { tokens } from '../tokens'

describe('Design Tokens (JS 侧设计令牌)', () => {
  describe('colors', () => {
    it('colors.primary 应等于 #0a84ff', () => {
      expect(tokens.colors.primary).toBe('#0a84ff')
    })

    it('colors.accent 应等于 #64d2ff', () => {
      expect(tokens.colors.accent).toBe('#64d2ff')
    })

    it('colors.bgDeep 应存在且为字符串', () => {
      expect(tokens.colors.bgDeep).toBeDefined()
      expect(typeof tokens.colors.bgDeep).toBe('string')
    })
  })

  describe('spacing', () => {
    it('spacing.xs 应存在且为字符串', () => {
      expect(tokens.spacing.xs).toBeDefined()
      expect(typeof tokens.spacing.xs).toBe('string')
    })

    it('spacing.sm 应存在且为字符串', () => {
      expect(tokens.spacing.sm).toBeDefined()
      expect(typeof tokens.spacing.sm).toBe('string')
    })

    it('spacing.md 应存在且为字符串', () => {
      expect(tokens.spacing.md).toBeDefined()
      expect(typeof tokens.spacing.md).toBe('string')
    })

    it('spacing.lg 应存在且为字符串', () => {
      expect(tokens.spacing.lg).toBeDefined()
      expect(typeof tokens.spacing.lg).toBe('string')
    })

    it('spacing.xl 应存在且为字符串', () => {
      expect(tokens.spacing.xl).toBeDefined()
      expect(typeof tokens.spacing.xl).toBe('string')
    })
  })

  describe('radius', () => {
    it('radius.sm 应存在且为字符串', () => {
      expect(tokens.radius.sm).toBeDefined()
      expect(typeof tokens.radius.sm).toBe('string')
    })

    it('radius.md 应存在且为字符串', () => {
      expect(tokens.radius.md).toBeDefined()
      expect(typeof tokens.radius.md).toBe('string')
    })

    it('radius.lg 应存在且为字符串', () => {
      expect(tokens.radius.lg).toBeDefined()
      expect(typeof tokens.radius.lg).toBe('string')
    })

    it('radius.full 应存在且为字符串', () => {
      expect(tokens.radius.full).toBeDefined()
      expect(typeof tokens.radius.full).toBe('string')
    })
  })

  describe('transitions', () => {
    it('transitions.fast 应存在且为字符串', () => {
      expect(tokens.transitions.fast).toBeDefined()
      expect(typeof tokens.transitions.fast).toBe('string')
    })

    it('transitions.normal 应存在且为字符串', () => {
      expect(tokens.transitions.normal).toBeDefined()
      expect(typeof tokens.transitions.normal).toBe('string')
    })

    it('transitions.slow 应存在且为字符串', () => {
      expect(tokens.transitions.slow).toBeDefined()
      expect(typeof tokens.transitions.slow).toBe('string')
    })
  })

  describe('只读对象 (as const)', () => {
    it('tokens 应是 as const 对象（结构完整且各分组存在）', () => {
      // as const 是编译时保证，运行时验证对象结构完整
      expect(tokens).toBeDefined()
      expect(typeof tokens).toBe('object')
      expect(tokens.colors).toBeDefined()
      expect(tokens.spacing).toBeDefined()
      expect(tokens.radius).toBeDefined()
      expect(tokens.transitions).toBeDefined()
    })
  })
})

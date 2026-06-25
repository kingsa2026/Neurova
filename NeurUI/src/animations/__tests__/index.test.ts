/**
 * 阶段9 RED: 验证统一动画预设
 *
 * 测试动画 name 与 global.css 中的过渡类名前缀对应
 *   - fade       ↔ .fade-enter-active
 *   - fade-slide ↔ .fade-slide-enter-active
 *   - scale      ↔ .scale-enter-active
 */
import { describe, it, expect } from 'vitest'
import { animations, transitionPresets } from '../index'

describe('Animations (统一动画预设)', () => {
  describe('animations 预设', () => {
    it('animations.fade.name 应等于 fade', () => {
      expect(animations.fade.name).toBe('fade')
    })

    it('animations.fade.duration 应等于 250', () => {
      expect(animations.fade.duration).toBe(250)
    })

    it('animations.fadeSlide.name 应等于 fade-slide', () => {
      expect(animations.fadeSlide.name).toBe('fade-slide')
    })

    it('animations.scale.name 应等于 scale', () => {
      expect(animations.scale.name).toBe('scale')
    })

    it('animations.slideUp.name 应等于 slide-up', () => {
      expect(animations.slideUp.name).toBe('slide-up')
    })
  })

  describe('transitionPresets (Vue transition 组件预设)', () => {
    it('transitionPresets.fade 应存在且包含 enterActiveClass/leaveActiveClass', () => {
      expect(transitionPresets.fade).toBeDefined()
      expect(transitionPresets.fade.enterActiveClass).toBeDefined()
      expect(typeof transitionPresets.fade.enterActiveClass).toBe('string')
      expect(transitionPresets.fade.leaveActiveClass).toBeDefined()
      expect(typeof transitionPresets.fade.leaveActiveClass).toBe('string')
    })

    it('transitionPresets.fadeSlide 应存在', () => {
      expect(transitionPresets.fadeSlide).toBeDefined()
      expect(transitionPresets.fadeSlide.enterActiveClass).toBeDefined()
      expect(transitionPresets.fadeSlide.leaveActiveClass).toBeDefined()
    })
  })

  describe('只读对象 (as const)', () => {
    it('animations 应是 as const 对象（结构完整）', () => {
      // as const 是编译时保证，运行时验证对象结构完整
      expect(animations).toBeDefined()
      expect(typeof animations).toBe('object')
      expect(animations.fade).toBeDefined()
      expect(animations.fadeSlide).toBeDefined()
      expect(animations.scale).toBeDefined()
      expect(animations.slideUp).toBeDefined()
    })
  })
})

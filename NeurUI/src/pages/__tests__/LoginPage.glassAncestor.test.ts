import { describe, it, expect } from 'vitest'
// 经 vite ?raw 管道读取页面源文本，断言 CSS 契约
import src from '../LoginPage.vue?raw'

/**
 * 玻璃卡祖先 transform 残留契约测试。
 *
 * 根因（2026-09-15 A/B 实拍定案）：GlassSurface 的折射靠
 * `backdrop-filter: url(#filter)` 采样元素背后的内容。祖先元素一旦带
 * 有（哪怕恒等矩阵的）transform，Chromium 会把该祖先变成 backdrop 采样
 * 边界，玻璃卡只能采到祖先内部（空的），折射整体消失。
 * `animation-fill-mode: both/forwards` 会在动画播完后把最后一帧的
 * `transform: translateY(0) scale(1)` 永久保留在 .nr-auth-container 上，
 * 即触发此故障。因此入场动画的 fill 模式禁止 forwards/both。
 */

describe('LoginPage 玻璃卡祖先 transform 约束', () => {
  it('.nr-auth-container 入场动画不得使用 forwards/both 填充（残留 transform 会破坏 backdrop-filter 采样）', () => {
    const rule = /\.nr-auth-container\s*\{[^}]*\}/.exec(src)?.[0]
    expect(rule, '.nr-auth-container 规则缺失').toBeTruthy()
    const animation = /animation:\s*([^;]+);/.exec(rule!)?.[1]
    expect(animation, '.nr-auth-container 应声明 animation').toBeTruthy()
    expect(animation).not.toMatch(/\bboth\b/)
    expect(animation).not.toMatch(/\bforwards\b/)
  })

  it('auth-enter 关键帧结束后不得把 transform 保留到常态（to 帧只允许 opacity 或 transform:none）', () => {
    const keyframes = /@keyframes\s+auth-enter\s*\{[\s\S]*?\n\}/.exec(src)?.[0]
    expect(keyframes, 'auth-enter 关键帧缺失').toBeTruthy()
    const toBlock = /to\s*\{([^}]*)\}/.exec(keyframes!)?.[1] ?? ''
    const transformDecl = /transform:\s*([^;]+);/.exec(toBlock)?.[1]
    // 允许 transform 缺席或为 none；translateY(0)/scale(1) 等恒等值同样被禁止
    expect(transformDecl === undefined || transformDecl.trim() === 'none').toBe(true)
  })
})

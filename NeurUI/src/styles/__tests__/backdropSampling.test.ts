import { describe, it, expect } from 'vitest'

/**
 * 全局契约：backdrop-filter 采样链路防回归（liquid-glass-web 根因 1）。
 *
 * Chromium 中祖先元素残留 transform（哪怕恒等矩阵）会把该祖先变成 backdrop
 * 采样边界，玻璃组件（GlassPanel ios 折射分支 / GlassSurface）采不到页面背景，
 * 液态玻璃折射整体消失。`animation-fill-mode: both/forwards` 会在动画播完后
 * 把最后一帧的 transform 永久保留——2026-09-15 登录页 auth-enter、
 * 2026-09-16 主界面 dash-enter 两起事故同根。
 *
 * 规则：凡 animation 简写含 both/forwards 的，其 @keyframes 的 to 帧不得声明
 * transform（opacity-only 动画安全）。入场动画请写 `backwards` 填充 +
 * to 帧省略 transform（插值终点取基线 none）。
 */
const modules = import.meta.glob<string>('../../**/*.vue', {
  query: '?raw',
  import: 'default',
  eager: true,
})

describe('backdrop 采样链路全局契约', () => {
  it('所有 both/forwards 填充动画的 to 帧不得含 transform（防 backdrop 采样边界残留）', () => {
    const violations: string[] = []
    for (const [path, src] of Object.entries(modules)) {
      const animRe = /animation:\s*([^;]+);/g
      let m: RegExpExecArray | null
      while ((m = animRe.exec(src))) {
        const decl = m[1]
        if (!/\b(both|forwards)\b/.test(decl)) continue
        // 项目约定 animation-name 为简写第一个 token
        const name = decl.trim().split(/\s+/)[0]
        const kf = new RegExp(`@keyframes\\s+${name}\\s*\\{([\\s\\S]*?)\\n\\}`).exec(src)
        if (!kf) continue
        const toBlock = /\bto\s*\{([^}]*)\}/.exec(kf[1])?.[1] ?? ''
        if (/transform:/.test(toBlock)) {
          violations.push(`${path} → @keyframes ${name}（to 帧含 transform 且 fill=${/\bforwards\b/.test(decl) ? 'forwards/both' : 'both'}）`)
        }
      }
    }
    expect(violations, `以下动画会在播完后残留 transform，破坏 backdrop-filter 采样：\n${violations.join('\n')}`).toEqual([])
  })
})

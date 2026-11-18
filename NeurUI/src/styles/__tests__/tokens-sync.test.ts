/**
 * tokens.ts ↔ variables.css 同步守卫（fullrepo 审计 2026-11-18：tokens.ts 人肉镜像漂移）
 *
 * tokens.ts 自述「必须与 variables.css 保持同步」但无任何机器校验——本守卫
 * 把同步映射（见 tokens.ts 头注释）逐值断言：JS 侧每个令牌都必须与对应
 * css 变量逐字符一致（空白/引号差异归一化），css 侧缺失即红。
 *
 * 级联语义：colors/shadows 每个明暗块各自定义；radius/font/transitions 是
 * 皮肤级令牌（定义在皮肤 dark 块，light 继承）——按继承语义取皮肤 dark 块。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { skinTokens } from '../tokens'

const css = readFileSync(resolve(process.cwd(), 'src/styles/variables.css'), 'utf-8')
const norm = (s: string): string => s.replace(/\s+/g, '').replace(/'/g, '"')

function block(selector: string): Record<string, string> {
  const body =
    css.match(new RegExp(selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*\\{([^}]*)\\}'))?.[1] ?? ''
  const out: Record<string, string> = {}
  for (const m of body.matchAll(/(--nr-[a-z0-9-]+)\s*:\s*([^;]+);/g)) out[m[1]] = norm(m[2])
  return out
}

const COLOR_MAP: Array<[string, string]> = [
  ['primary', '--nr-primary'],
  ['accent', '--nr-accent'],
  ['bgDeep', '--nr-bg-deep'],
  ['bgBase', '--nr-bg-base'],
  ['bgSurface', '--nr-bg-surface'],
  ['bgElevated', '--nr-bg-elevated'],
  ['bgOverlay', '--nr-bg-overlay'],
  ['glassBg', '--nr-glass-bg'],
  ['glassBorder', '--nr-glass-border'],
  ['glassSpecularTop', '--nr-glass-specular-top'],
  ['glassHighlight', '--nr-glass-highlight'],
  ['textPrimary', '--nr-text-primary'],
  ['textSecondary', '--nr-text-secondary'],
  ['textTertiary', '--nr-text-tertiary'],
  ['textMuted', '--nr-text-muted'],
  ['success', '--nr-success'],
  ['warning', '--nr-warning'],
  ['error', '--nr-error'],
  ['info', '--nr-info'],
]
const SPACE_MAP: Array<[string, string]> = [
  ['xs', '--nr-space-xs'],
  ['sm', '--nr-space-sm'],
  ['md', '--nr-space-md'],
  ['lg', '--nr-space-lg'],
  ['xl', '--nr-space-xl'],
  ['xxl', '--nr-space-2xl'],
]
const RADIUS_MAP: Array<[string, string]> = [
  ['sm', '--nr-radius-sm'],
  ['md', '--nr-radius-md'],
  ['lg', '--nr-radius-lg'],
  ['xl', '--nr-radius-xl'],
  ['full', '--nr-radius-full'],
]
const FONT_MAP: Array<[string, string]> = [
  ['display', '--nr-font-display'],
  ['body', '--nr-font-body'],
  ['mono', '--nr-font-mono'],
]
const TRANSITION_MAP: Array<[string, string]> = [
  ['fast', '--nr-transition-fast'],
  ['normal', '--nr-transition'],
  ['slow', '--nr-transition-slow'],
]
const SHADOW_MAP: Array<[string, string]> = [
  ['sm', '--nr-shadow-sm'],
  ['md', '--nr-shadow-md'],
  ['lg', '--nr-shadow-lg'],
]

const SELECTORS: Record<string, Record<string, string>> = {
  cosmic: {
    dark: ":root[data-skin='cosmic']",
    light: ":root[data-skin='cosmic'][data-theme='light']",
  },
  ios: {
    dark: ":root[data-skin='ios']",
    light: ":root[data-skin='ios'][data-theme='light']",
  },
}

/** :root 共享块（spacing 等双皮肤一致的面） */
const rootCss = block(':root')

describe('tokens.ts ↔ variables.css 同步守卫', () => {
  for (const skin of ['cosmic', 'ios'] as const) {
    // 皮肤级令牌（light 继承 dark）：radius/font/transitions
    const skinCss = block(SELECTORS[skin].dark)
    for (const mode of ['dark', 'light'] as const) {
      const modeCss = block(SELECTORS[skin][mode])
      const jsTokens = skinTokens[skin][mode]

      it(`${skin}.${mode}: colors 与 css 变量一致`, () => {
        for (const [jsKey, cssKey] of COLOR_MAP) {
          expect(modeCss[cssKey], `${cssKey} 应在 ${SELECTORS[skin][mode]} 中存在`).toBeTruthy()
          expect(norm((jsTokens.colors as Record<string, string>)[jsKey])).toBe(modeCss[cssKey])
        }
      })

      it(`${skin}.${mode}: spacing/radius 与 css 变量一致`, () => {
        for (const [jsKey, cssKey] of SPACE_MAP) {
          expect(rootCss[cssKey], `${cssKey} 应存在于 :root 共享块`).toBeTruthy()
          expect(norm((jsTokens.spacing as Record<string, string>)[jsKey])).toBe(rootCss[cssKey])
        }
        for (const [jsKey, cssKey] of RADIUS_MAP) {
          expect(skinCss[cssKey], `${cssKey} 应在皮肤块存在`).toBeTruthy()
          expect(norm((jsTokens.radius as Record<string, string>)[jsKey])).toBe(skinCss[cssKey])
        }
      })

      it(`${skin}.${mode}: font/transitions/shadows 与 css 变量一致`, () => {
        for (const [jsKey, cssKey] of FONT_MAP) {
          expect(skinCss[cssKey], `${cssKey} 应在皮肤块存在`).toBeTruthy()
          expect(norm((jsTokens.font as Record<string, string>)[jsKey])).toBe(skinCss[cssKey])
        }
        for (const [jsKey, cssKey] of TRANSITION_MAP) {
          expect(skinCss[cssKey], `${cssKey} 应在皮肤块存在`).toBeTruthy()
          expect(norm((jsTokens.transitions as Record<string, string>)[jsKey])).toBe(skinCss[cssKey])
        }
        for (const [jsKey, cssKey] of SHADOW_MAP) {
          expect(modeCss[cssKey], `${cssKey} 应存在`).toBeTruthy()
          expect(norm((jsTokens.shadows as Record<string, string>)[jsKey])).toBe(modeCss[cssKey])
        }
      })
    }
  }
})

/**
 * 设计令牌（JS 侧）— 双皮肤 × 双明暗
 *
 * 从 variables.css 提取的设计令牌，供 JS/TS 代码使用。
 * 注意: 这些值必须与 variables.css 中的 CSS 变量保持同步。
 *
 * 结构（2026-09-05 双皮肤共存）:
 *   skinTokens.cosmic.{dark,light} — 原版星空玻璃拟态 / DeepSeek 浅色
 *   skinTokens.ios.{dark,light}    — Apple iOS 20 Liquid Glass
 *
 * 同步映射:
 *   colors.primary      ↔ --nr-primary
 *   colors.accent       ↔ --nr-accent
 *   colors.bgDeep       ↔ --nr-bg-deep
 *   colors.bgBase       ↔ --nr-bg-base
 *   colors.bgSurface    ↔ --nr-bg-surface
 *   colors.bgElevated   ↔ --nr-bg-elevated
 *   colors.bgOverlay    ↔ --nr-bg-overlay
 *   colors.glassBg      ↔ --nr-glass-bg
 *   colors.glassBorder  ↔ --nr-glass-border
 *   colors.textPrimary  ↔ --nr-text-primary
 *   colors.textSecondary↔ --nr-text-secondary
 *   colors.textTertiary ↔ --nr-text-tertiary
 *   colors.textMuted    ↔ --nr-text-muted
 *   colors.success      ↔ --nr-success
 *   colors.warning      ↔ --nr-warning
 *   colors.error        ↔ --nr-error
 *   colors.info         ↔ --nr-info
 *   spacing.*           ↔ --nr-space-*
 *   radius.*            ↔ --nr-radius-*
 *   font.*              ↔ --nr-font-*
 *   transitions.*       ↔ --nr-transition*
 *   shadows.*           ↔ --nr-shadow-*
 */
const sharedSpacing = {
  xs: '4px',
  sm: '8px',
  md: '16px',
  lg: '24px',
  xl: '32px',
  xxl: '48px',
} as const

export const skinTokens = {
  cosmic: {
    dark: {
      colors: {
        primary: '#6366f1',
        accent: '#22d3ee',
        bgDeep: '#06080f',
        bgBase: '#0a0e1a',
        bgSurface: '#111827',
        bgElevated: '#1a2236',
        bgOverlay: 'rgba(10, 14, 26, 0.85)',
        glassBg: 'rgba(255, 255, 255, 0.035)',
        glassBorder: 'rgba(255, 255, 255, 0.08)',
        glassSpecularTop: 'rgba(255, 255, 255, 0.25)',
        glassHighlight: 'rgba(255, 255, 255, 0.05)',
        textPrimary: 'rgba(255, 255, 255, 0.95)',
        textSecondary: 'rgba(255, 255, 255, 0.7)',
        textTertiary: 'rgba(255, 255, 255, 0.45)',
        textMuted: 'rgba(255, 255, 255, 0.25)',
        success: '#10b981',
        warning: '#f59e0b',
        error: '#ef4444',
        info: '#3b82f6',
      },
      spacing: sharedSpacing,
      radius: { sm: '6px', md: '10px', lg: '16px', xl: '24px', full: '9999px' },
      font: {
        display: "'DM Sans', system-ui, sans-serif",
        body: "'DM Sans', system-ui, sans-serif",
        mono: "'Space Mono', 'Fira Code', monospace",
      },
      transitions: {
        fast: '0.15s cubic-bezier(0.4, 0, 0.2, 1)',
        normal: '0.25s cubic-bezier(0.4, 0, 0.2, 1)',
        slow: '0.4s cubic-bezier(0.4, 0, 0.2, 1)',
      },
      shadows: {
        sm: '0 2px 8px rgba(0, 0, 0, 0.3)',
        md: '0 4px 16px rgba(0, 0, 0, 0.4)',
        lg: '0 8px 32px rgba(0, 0, 0, 0.5)',
      },
    },
    light: {
      colors: {
        primary: '#4d6bfe',
        accent: '#0891b2',
        bgDeep: '#f5f6f7',
        bgBase: '#fafbfc',
        bgSurface: '#ffffff',
        bgElevated: '#f0f2f5',
        bgOverlay: 'rgba(255, 255, 255, 0.9)',
        glassBg: 'rgba(31, 35, 41, 0.035)',
        glassBorder: 'rgba(31, 35, 41, 0.1)',
        textPrimary: 'rgba(31, 35, 41, 0.95)',
        textSecondary: 'rgba(31, 35, 41, 0.65)',
        textTertiary: 'rgba(31, 35, 41, 0.45)',
        textMuted: 'rgba(31, 35, 41, 0.28)',
        success: '#059669',
        warning: '#d97706',
        error: '#dc2626',
        info: '#2563eb',
      },
      spacing: sharedSpacing,
      radius: { sm: '6px', md: '10px', lg: '16px', xl: '24px', full: '9999px' },
      font: {
        display: "'DM Sans', system-ui, sans-serif",
        body: "'DM Sans', system-ui, sans-serif",
        mono: "'Space Mono', 'Fira Code', monospace",
      },
      transitions: {
        fast: '0.15s cubic-bezier(0.4, 0, 0.2, 1)',
        normal: '0.25s cubic-bezier(0.4, 0, 0.2, 1)',
        slow: '0.4s cubic-bezier(0.4, 0, 0.2, 1)',
      },
      shadows: {
        sm: '0 1px 3px rgba(31, 35, 41, 0.05), 0 2px 8px rgba(31, 35, 41, 0.05)',
        md: '0 4px 16px rgba(31, 35, 41, 0.08)',
        lg: '0 8px 32px rgba(31, 35, 41, 0.12)',
      },
    },
  },
  ios: {
    dark: {
      colors: {
        primary: '#0a84ff',
        accent: '#64d2ff',
        bgDeep: '#000000',
        bgBase: '#000000',
        bgSurface: '#1c1c1e',
        bgElevated: '#2c2c2e',
        bgOverlay: 'rgba(0, 0, 0, 0.72)',
        glassBg: 'rgba(255, 255, 255, 0.07)',
        glassBorder: 'rgba(255, 255, 255, 0.12)',
        textPrimary: 'rgba(255, 255, 255, 0.96)',
        textSecondary: 'rgba(255, 255, 255, 0.64)',
        textTertiary: 'rgba(255, 255, 255, 0.44)',
        textMuted: 'rgba(255, 255, 255, 0.3)',
        success: '#30d158',
        warning: '#ff9f0a',
        error: '#ff453a',
        info: '#0a84ff',
      },
      spacing: sharedSpacing,
      radius: { sm: '10px', md: '14px', lg: '18px', xl: '28px', full: '9999px' },
      font: {
        display: "-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'SF Pro Text', 'PingFang SC', sans-serif",
        body: "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'SF Pro', 'PingFang SC', sans-serif",
        mono: "'SF Mono', ui-monospace, 'Cascadia Code', Consolas, monospace",
      },
      transitions: {
        fast: '0.2s cubic-bezier(0.32, 0.72, 0, 1)',
        normal: '0.35s cubic-bezier(0.32, 0.72, 0, 1)',
        slow: '0.55s cubic-bezier(0.32, 0.72, 0, 1)',
      },
      shadows: {
        sm: '0 1px 2px rgba(0, 0, 0, 0.3)',
        md: '0 2px 12px rgba(0, 0, 0, 0.35)',
        lg: '0 12px 32px rgba(0, 0, 0, 0.55)',
      },
    },
    light: {
      colors: {
        primary: '#007aff',
        accent: '#5ac8fa',
        bgDeep: '#f2f2f7',
        bgBase: '#f2f2f7',
        bgSurface: '#ffffff',
        bgElevated: '#e5e5ea',
        bgOverlay: 'rgba(255, 255, 255, 0.72)',
        glassBg: 'rgba(120, 120, 128, 0.1)',
        glassBorder: 'rgba(60, 60, 67, 0.16)',
        glassSpecularTop: 'rgba(255, 255, 255, 0.9)',
        glassHighlight: 'rgba(255, 255, 255, 0.5)',
        textPrimary: 'rgba(0, 0, 0, 0.94)',
        textSecondary: 'rgba(0, 0, 0, 0.62)',
        textTertiary: 'rgba(0, 0, 0, 0.44)',
        textMuted: 'rgba(0, 0, 0, 0.3)',
        success: '#34c759',
        warning: '#ff9500',
        error: '#ff3b30',
        info: '#007aff',
      },
      spacing: sharedSpacing,
      radius: { sm: '10px', md: '14px', lg: '18px', xl: '28px', full: '9999px' },
      font: {
        display: "-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'SF Pro Text', 'PingFang SC', sans-serif",
        body: "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'SF Pro', 'PingFang SC', sans-serif",
        mono: "'SF Mono', ui-monospace, 'Cascadia Code', Consolas, monospace",
      },
      transitions: {
        fast: '0.2s cubic-bezier(0.32, 0.72, 0, 1)',
        normal: '0.35s cubic-bezier(0.32, 0.72, 0, 1)',
        slow: '0.55s cubic-bezier(0.32, 0.72, 0, 1)',
      },
      shadows: {
        sm: '0 1px 2px rgba(0, 0, 0, 0.04)',
        md: '0 2px 10px rgba(0, 0, 0, 0.06)',
        lg: '0 12px 32px rgba(0, 0, 0, 0.12)',
      },
    },
  },
} as const

export type Skin = keyof typeof skinTokens
export type SkinMode = keyof (typeof skinTokens)[Skin]

/** 兼容旧消费方：默认导出为 iOS 深色令牌（原 iOS 单皮肤时期的主色）。 */
export const tokens = skinTokens.ios.dark

export default tokens
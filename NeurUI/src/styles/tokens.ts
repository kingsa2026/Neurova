/**
 * 设计令牌（JS 侧）
 *
 * 从 variables.css 提取的设计令牌，供 JS/TS 代码使用。
 * 注意: 这些值必须与 variables.css 中的 CSS 变量保持同步。
 *
 * 2026-09-05 起主题为 Apple iOS Liquid Glass 风格（深色/浅色两套）。
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
 *   transitions.*       ↔ --nr-transition*
 *   shadows.*           ↔ --nr-shadow-*
 */
export const tokens = {
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
  spacing: {
    xs: '4px',
    sm: '8px',
    md: '16px',
    lg: '24px',
    xl: '32px',
    xxl: '48px',
  },
  radius: {
    sm: '10px',
    md: '14px',
    lg: '18px',
    xl: '28px',
    full: '9999px',
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
} as const

export default tokens
/**
 * 设计令牌（JS 侧）
 *
 * 从 variables.css 提取的设计令牌，供 JS/TS 代码使用。
 * 注意: 这些值必须与 variables.css 中的 CSS 变量保持同步。
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
    primary: '#6366f1',
    accent: '#22d3ee',
    bgDeep: '#06080f',
    bgBase: '#0a0e1a',
    bgSurface: '#111827',
    bgElevated: '#1a2236',
    bgOverlay: 'rgba(10, 14, 26, 0.85)',
    glassBg: 'rgba(255, 255, 255, 0.035)',
    glassBorder: 'rgba(255, 255, 255, 0.08)',
    textPrimary: 'rgba(255, 255, 255, 0.95)',
    textSecondary: 'rgba(255, 255, 255, 0.7)',
    textTertiary: 'rgba(255, 255, 255, 0.45)',
    textMuted: 'rgba(255, 255, 255, 0.25)',
    success: '#10b981',
    warning: '#f59e0b',
    error: '#ef4444',
    info: '#3b82f6',
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
    sm: '6px',
    md: '10px',
    lg: '16px',
    xl: '24px',
    full: '9999px',
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
} as const

export default tokens

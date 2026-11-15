/**
 * StyleManager - 统一样式库
 *
 * 职责：统一管理应用所有样式 token（颜色、间距、字号、圆角、阴影）
 * 设计：单例模式，支持亮/暗主题切换、自定义 token 注册
 *
 * 用法：
 *   const sm = StyleManager.getInstance();
 *   sm.setThemeMode(ThemeMode.DARK);
 *   const primary = sm.getColor('primary');
 *   const padding = sm.getSpacing('md');
 */

/** 主题模式 */
export enum ThemeMode {
  LIGHT = 'light',
  DARK = 'dark',
}

/** 颜色 token 名 */
export type ColorToken =
  | 'primary' | 'secondary' | 'success' | 'warning' | 'error' | 'info'
  | 'background' | 'surface' | 'text_primary' | 'text_secondary' | 'text_disabled'
  | 'text_on_primary' | 'overlay_mask' | 'border' | 'divider';

/** 间距 token 名 */
export type SpacingToken = 'xs' | 'sm' | 'md' | 'lg' | 'xl' | 'xxl';

/** 字号 token 名 */
export type FontSizeToken = 'caption' | 'body' | 'subtitle' | 'title' | 'headline' | 'display';

/** 圆角 token 名 */
export type RadiusToken = 'none' | 'xs' | 'sm' | 'md' | 'lg' | 'xl' | 'full';

/** 亮色主题颜色表 */
const LIGHT_COLORS: Record<string, string> = {
  primary: '#1890ff',
  secondary: '#52c41a',
  success: '#52c41a',
  warning: '#faad14',
  error: '#ff4d4f',
  info: '#1890ff',
  background: '#ffffff',
  surface: '#f5f5f5',
  text_primary: '#262626',
  text_secondary: '#8c8c8c',
  text_disabled: '#bfbfbf',
  text_on_primary: '#ffffff',
  overlay_mask: 'rgba(0,0,0,0.5)',
  border: '#d9d9d9',
  divider: '#f0f0f0',
};

/** 暗色主题颜色表 */
const DARK_COLORS: Record<string, string> = {
  primary: '#177ddc',
  secondary: '#49aa19',
  success: '#49aa19',
  warning: '#d89614',
  error: '#d32029',
  info: '#177ddc',
  background: '#141414',
  surface: '#1f1f1f',
  text_primary: '#f0f0f0',
  text_secondary: '#a6a6a6',
  text_disabled: '#595959',
  text_on_primary: '#ffffff',
  overlay_mask: 'rgba(0,0,0,0.7)',
  border: '#434343',
  divider: '#303030',
};

/** 间距表（fp） */
const SPACING: Record<string, number> = {
  xs: 4,
  sm: 8,
  md: 16,
  lg: 24,
  xl: 32,
  xxl: 48,
};

/** 字号表（fp） */
const FONT_SIZE: Record<string, number> = {
  caption: 12,
  body: 16,
  subtitle: 18,
  title: 20,
  headline: 24,
  display: 32,
};

/** 圆角表（vp） */
const RADIUS: Record<string, number> = {
  none: 0,
  xs: 2,
  sm: 4,
  md: 8,
  lg: 12,
  xl: 16,
  full: 9999,
};

export class StyleManager {
  private static instance: StyleManager;
  private themeMode: ThemeMode = ThemeMode.LIGHT;
  private colors: Record<string, string> = {};
  private spacing: Record<string, number> = {};
  private fontSize: Record<string, number> = {};
  private radius: Record<string, number> = {};

  private constructor() {
    this.resetToDefaults();
  }

  static getInstance(): StyleManager {
    if (!StyleManager.instance) {
      StyleManager.instance = new StyleManager();
    }
    return StyleManager.instance;
  }

  /** 重置为默认 token */
  resetToDefaults(): void {
    this.colors = this.themeMode === ThemeMode.DARK
      ? { ...DARK_COLORS }
      : { ...LIGHT_COLORS };
    this.spacing = { ...SPACING };
    this.fontSize = { ...FONT_SIZE };
    this.radius = { ...RADIUS };
  }

  /** 获取当前主题模式 */
  getThemeMode(): ThemeMode {
    return this.themeMode;
  }

  /** 设置主题模式（自动切换颜色表） */
  setThemeMode(mode: ThemeMode): void {
    if (this.themeMode === mode) return;
    this.themeMode = mode;
    // 重新加载默认颜色（保留自定义颜色会被覆盖，符合 reset 语义）
    const defaults = mode === ThemeMode.DARK ? DARK_COLORS : LIGHT_COLORS;
    for (const key of Object.keys(defaults)) {
      this.colors[key] = defaults[key];
    }
  }

  /** 获取颜色 token */
  getColor(token: string): string {
    return this.colors[token] ?? '#000000';
  }

  /** 设置/覆盖颜色 token */
  setColor(token: string, value: string): void {
    this.colors[token] = value;
  }

  /** 获取间距 token */
  getSpacing(token: string): number {
    return this.spacing[token] ?? 0;
  }

  /** 设置/新增间距 token */
  setSpacing(token: string, value: number): void {
    this.spacing[token] = value;
  }

  /** 获取字号 token */
  getFontSize(token: string): number {
    return this.fontSize[token] ?? 16;
  }

  /** 设置/覆盖字号 token */
  setFontSize(token: string, value: number): void {
    this.fontSize[token] = value;
  }

  /** 获取圆角 token */
  getRadius(token: string): number {
    return this.radius[token] ?? 0;
  }

  /** 设置/覆盖圆角 token */
  setRadius(token: string, value: number): void {
    this.radius[token] = value;
  }
}

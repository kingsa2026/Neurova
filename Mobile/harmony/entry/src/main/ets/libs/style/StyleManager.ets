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

/** 颜色 token 名（cosmic 星穹玻璃体系，对照界面布局规划原型 01 设计系统） */
export type ColorToken =
  | 'primary' | 'secondary' | 'success' | 'warning' | 'error' | 'info'
  | 'background' | 'surface' | 'text_primary' | 'text_secondary' | 'text_disabled'
  | 'text_on_primary' | 'overlay_mask' | 'border' | 'divider'
  | 'accent' | 'surface_strong' | 'text_tertiary' | 'primary_soft'
  | 'status_success' | 'status_error' | 'status_warning';

/** 间距 token 名 */
export type SpacingToken = 'xs' | 'sm' | 'md' | 'lg' | 'xl' | 'xxl';

/** 字号 token 名 */
export type FontSizeToken = 'caption' | 'body' | 'subtitle' | 'title' | 'headline' | 'display';

/** 圆角 token 名 */
export type RadiusToken = 'none' | 'xs' | 'sm' | 'md' | 'lg' | 'xl' | 'full';

/** 亮色主题颜色表（ArkTS 禁非空字面量标注 Record，改为空表逐键赋值） */
const LIGHT_COLORS: Record<string, string> = {};
LIGHT_COLORS['primary'] = '#4d6bfe';
LIGHT_COLORS['secondary'] = '#7c3aed';
LIGHT_COLORS['success'] = '#0c8f5e';
LIGHT_COLORS['warning'] = '#b45309';
LIGHT_COLORS['error'] = '#dc2626';
LIGHT_COLORS['info'] = '#0e7490';
LIGHT_COLORS['accent'] = '#0e7490';
LIGHT_COLORS['background'] = '#f5f6fb';
LIGHT_COLORS['surface'] = '#ffffff';
LIGHT_COLORS['surface_strong'] = 'rgba(21,28,58,0.08)';
LIGHT_COLORS['text_primary'] = 'rgba(16,21,44,0.94)';
LIGHT_COLORS['text_secondary'] = 'rgba(16,21,44,0.62)';
LIGHT_COLORS['text_tertiary'] = 'rgba(16,21,44,0.42)';
LIGHT_COLORS['text_disabled'] = 'rgba(16,21,44,0.42)';
LIGHT_COLORS['text_on_primary'] = '#ffffff';
LIGHT_COLORS['primary_soft'] = 'rgba(77,107,254,0.12)';
LIGHT_COLORS['overlay_mask'] = 'rgba(16,21,44,0.42)';
LIGHT_COLORS['border'] = 'rgba(21,28,58,0.11)';
LIGHT_COLORS['divider'] = 'rgba(21,28,58,0.07)';
// 状态三 token（ChannelIntegration/SessionSync/Monitor/Stats 四页的状态色名）：
// 值一律由上方基 token 派生，此处只挂名，不另设第二份色值（单一事实源）
LIGHT_COLORS['status_success'] = LIGHT_COLORS['success'];
LIGHT_COLORS['status_error'] = LIGHT_COLORS['error'];
LIGHT_COLORS['status_warning'] = LIGHT_COLORS['warning'];

/** 暗色主题颜色表（同上，空表逐键赋值） */
const DARK_COLORS: Record<string, string> = {};
DARK_COLORS['primary'] = '#6366f1';
DARK_COLORS['secondary'] = '#8b5cf6';
DARK_COLORS['success'] = '#34d399';
DARK_COLORS['warning'] = '#fbbf24';
DARK_COLORS['error'] = '#f87171';
DARK_COLORS['info'] = '#22d3ee';
DARK_COLORS['accent'] = '#22d3ee';
DARK_COLORS['background'] = '#0a0e1d';
DARK_COLORS['surface'] = '#141a2e';
DARK_COLORS['surface_strong'] = 'rgba(255,255,255,0.09)';
DARK_COLORS['text_primary'] = 'rgba(255,255,255,0.95)';
DARK_COLORS['text_secondary'] = 'rgba(255,255,255,0.64)';
DARK_COLORS['text_tertiary'] = 'rgba(255,255,255,0.40)';
DARK_COLORS['text_disabled'] = 'rgba(255,255,255,0.40)';
DARK_COLORS['text_on_primary'] = '#ffffff';
DARK_COLORS['primary_soft'] = 'rgba(99,102,241,0.16)';
DARK_COLORS['overlay_mask'] = 'rgba(4,6,14,0.62)';
DARK_COLORS['border'] = 'rgba(255,255,255,0.11)';
DARK_COLORS['divider'] = 'rgba(255,255,255,0.07)';
// 状态三 token：同亮色表，值由基 token 派生（单一事实源）
DARK_COLORS['status_success'] = DARK_COLORS['success'];
DARK_COLORS['status_error'] = DARK_COLORS['error'];
DARK_COLORS['status_warning'] = DARK_COLORS['warning'];

/** 间距表（fp，空表逐键赋值） */
const SPACING: Record<string, number> = {};
SPACING['xs'] = 4;
SPACING['sm'] = 8;
SPACING['md'] = 16;
SPACING['lg'] = 24;
SPACING['xl'] = 32;
SPACING['xxl'] = 48;

/** 字号表（fp，空表逐键赋值） */
const FONT_SIZE: Record<string, number> = {};
FONT_SIZE['caption'] = 12;
FONT_SIZE['body'] = 16;
FONT_SIZE['subtitle'] = 18;
FONT_SIZE['title'] = 20;
FONT_SIZE['headline'] = 24;
FONT_SIZE['display'] = 32;

/** 圆角表（vp，空表逐键赋值） */
const RADIUS: Record<string, number> = {};
RADIUS['none'] = 0;
RADIUS['xs'] = 2;
RADIUS['sm'] = 4;
RADIUS['md'] = 8;
RADIUS['lg'] = 12;
RADIUS['xl'] = 16;
RADIUS['full'] = 9999;

export class StyleManager {
  private static instance: StyleManager;
  private themeMode: ThemeMode = ThemeMode.DARK;
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

  /** 复制字符串 token 表（ArkTS 禁对象 spread，逐键显式拷贝） */
  private static copyStringTokens(src: Record<string, string>): Record<string, string> {
    const out: Record<string, string> = {};
    for (const k of Object.keys(src)) {
      out[k] = src[k];
    }
    return out;
  }

  /** 复制数值 token 表（同上） */
  private static copyNumberTokens(src: Record<string, number>): Record<string, number> {
    const out: Record<string, number> = {};
    for (const k of Object.keys(src)) {
      out[k] = src[k];
    }
    return out;
  }

  /** 重置为默认 token */
  resetToDefaults(): void {
    this.colors = this.themeMode === ThemeMode.DARK
      ? StyleManager.copyStringTokens(DARK_COLORS)
      : StyleManager.copyStringTokens(LIGHT_COLORS);
    this.spacing = StyleManager.copyNumberTokens(SPACING);
    this.fontSize = StyleManager.copyNumberTokens(FONT_SIZE);
    this.radius = StyleManager.copyNumberTokens(RADIUS);
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

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

/** 亮色主题颜色表（ArkTS 禁非空字面量标注 Record，改为空表逐键赋值） */
const LIGHT_COLORS: Record<string, string> = {};
LIGHT_COLORS['primary'] = '#1890ff';
LIGHT_COLORS['secondary'] = '#52c41a';
LIGHT_COLORS['success'] = '#52c41a';
LIGHT_COLORS['warning'] = '#faad14';
LIGHT_COLORS['error'] = '#ff4d4f';
LIGHT_COLORS['info'] = '#1890ff';
LIGHT_COLORS['background'] = '#ffffff';
LIGHT_COLORS['surface'] = '#f5f5f5';
LIGHT_COLORS['text_primary'] = '#262626';
LIGHT_COLORS['text_secondary'] = '#8c8c8c';
LIGHT_COLORS['text_disabled'] = '#bfbfbf';
LIGHT_COLORS['text_on_primary'] = '#ffffff';
LIGHT_COLORS['overlay_mask'] = 'rgba(0,0,0,0.5)';
LIGHT_COLORS['border'] = '#d9d9d9';
LIGHT_COLORS['divider'] = '#f0f0f0';

/** 暗色主题颜色表（同上，空表逐键赋值） */
const DARK_COLORS: Record<string, string> = {};
DARK_COLORS['primary'] = '#177ddc';
DARK_COLORS['secondary'] = '#49aa19';
DARK_COLORS['success'] = '#49aa19';
DARK_COLORS['warning'] = '#d89614';
DARK_COLORS['error'] = '#d32029';
DARK_COLORS['info'] = '#177ddc';
DARK_COLORS['background'] = '#141414';
DARK_COLORS['surface'] = '#1f1f1f';
DARK_COLORS['text_primary'] = '#f0f0f0';
DARK_COLORS['text_secondary'] = '#a6a6a6';
DARK_COLORS['text_disabled'] = '#595959';
DARK_COLORS['text_on_primary'] = '#ffffff';
DARK_COLORS['overlay_mask'] = 'rgba(0,0,0,0.7)';
DARK_COLORS['border'] = '#434343';
DARK_COLORS['divider'] = '#303030';

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

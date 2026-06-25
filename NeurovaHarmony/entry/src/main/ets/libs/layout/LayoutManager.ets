/**
 * LayoutManager - 统一布局库
 *
 * 职责：统一管理应用布局相关能力（响应式断点、间距辅助、安全区）
 * 设计：单例模式；间距数值委托 StyleManager 提供
 *
 * 用法：
 *   const lm = LayoutManager.getInstance();
 *   const bp = lm.getBreakpoint(width);
 *   const pad = lm.padding('md');
 */

import { StyleManager } from '../style/StyleManager';

/** 响应式断点（数值为最小宽度阈值，单位 vp） */
export enum Breakpoint {
  SM = 320,
  MD = 600,
  LG = 840,
}

/** 四向间距值（单位 vp） */
export interface SpacingValue {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

/** 安全区内边距 */
export interface SafeAreaInsets {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

export class LayoutManager {
  private static instance: LayoutManager;

  // 默认安全区内边距全 0
  private safeAreaInsets: SafeAreaInsets = { top: 0, bottom: 0, left: 0, right: 0 };

  private constructor() {}

  static getInstance(): LayoutManager {
    if (!LayoutManager.instance) {
      LayoutManager.instance = new LayoutManager();
    }
    return LayoutManager.instance;
  }

  /** 按宽度返回所处断点（单位 vp） */
  getBreakpoint(width: number): Breakpoint {
    if (width < Breakpoint.MD) {
      return Breakpoint.SM;
    }
    if (width < Breakpoint.LG) {
      return Breakpoint.MD;
    }
    return Breakpoint.LG;
  }

  /** 是否为手机宽度（width < 600） */
  isMobile(width: number): boolean {
    return width < Breakpoint.MD;
  }

  /** 是否为平板宽度（600 <= width < 840） */
  isTablet(width: number): boolean {
    return width >= Breakpoint.MD && width < Breakpoint.LG;
  }

  /** 是否为桌面宽度（width >= 840） */
  isDesktop(width: number): boolean {
    return width >= Breakpoint.LG;
  }

  /** 四向相等的 padding（数值来自 StyleManager 间距 token） */
  padding(token: string): SpacingValue {
    const v = StyleManager.getInstance().getSpacing(token);
    return { top: v, right: v, bottom: v, left: v };
  }

  /** 仅水平方向的 padding（垂直为 0） */
  paddingH(token: string): SpacingValue {
    const v = StyleManager.getInstance().getSpacing(token);
    return { top: 0, right: v, bottom: 0, left: v };
  }

  /** 仅垂直方向的 padding（水平为 0） */
  paddingV(token: string): SpacingValue {
    const v = StyleManager.getInstance().getSpacing(token);
    return { top: v, right: 0, bottom: v, left: 0 };
  }

  /** 四向相等的 margin（语义与 padding 区分，数值同源） */
  margin(token: string): SpacingValue {
    return this.padding(token);
  }

  /** 设置安全区内边距（通常由窗口/Ability 注入） */
  setSafeAreaInsets(insets: SafeAreaInsets): void {
    this.safeAreaInsets = {
      top: insets.top,
      bottom: insets.bottom,
      left: insets.left,
      right: insets.right,
    };
  }

  /** 获取安全区内边距 */
  getSafeAreaInsets(): SafeAreaInsets {
    return {
      top: this.safeAreaInsets.top,
      bottom: this.safeAreaInsets.bottom,
      left: this.safeAreaInsets.left,
      right: this.safeAreaInsets.right,
    };
  }
}

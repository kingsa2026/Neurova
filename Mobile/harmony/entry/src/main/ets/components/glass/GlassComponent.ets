/**
 * GlassComponent - 玻璃效果基础容器
 *
 * 职责：为 glass 组件家族提供统一的玻璃质感容器（半透明底色 + 背景模糊 + 圆角 + 交互态）
 * 设计：Stack 承载内容，底色按配色方案与质感样式取半透明色，backdropBlur 模糊组件背后内容；
 *       圆角/宽度/高度/背景覆盖/透明度/禁用态/点击回调均以属性入参表达——
 *       自定义组件不支持链式通用属性（.borderRadius() 等），调用方须经组件配置对象传入
 * 主题：玻璃底色跟随应用当前主题（StyleManager）——暗色主题用黑玻璃（原型 cosmic 暗玻璃），
 *       浅色主题用白玻璃；历史调用方全部硬编码 LIGHT，导致暗色主题下输入框/按钮
 *       渲染成浅色磨砂块（与设计稿不符），故改为主题驱动，显式传 DARK 仍强制深色
 *
 * 用法：
 *   GlassComponent({ glassStyle: GlassStyle.BLUR_THIN, blurRadius: 20 }) {
 *     Text('内容')
 *   }
 */

import { StyleManager, ThemeMode } from '../../libs/style/StyleManager';

// 玻璃质感样式：轻模糊 / 重模糊
export enum GlassStyle {
  BLUR_THIN = 0,
  BLUR_THICK = 1
}

// 玻璃配色方案：浅色 / 深色
export enum GlassColorScheme {
  LIGHT = 0,
  DARK = 1
}

@Component
export struct GlassComponent {
  // 玻璃质感样式（GlassStyle 取值；以数值承载，兼容枚举与数字入参）
  @Prop glassStyle: number = GlassStyle.BLUR_THIN;
  // 背景模糊半径（vp）
  @Prop blurRadius: number = 20;
  // 配色方案（GlassColorScheme 取值；以数值承载；显式传 DARK 强制深色）
  @Prop colorScheme: number = GlassColorScheme.LIGHT;
  // 圆角半径（vp）
  @Prop cornerRadius: number = 0;
  // 背景覆盖色：透明时呈现玻璃底色，非透明时覆盖玻璃底色
  @Prop bgColor: ResourceColor = Color.Transparent;
  // 不透明度
  @Prop alpha: number = 1;
  // 是否可交互（禁用时不响应点击）
  @Prop pressable: boolean = true;
  // 容器宽度（缺省 auto 自适应内容）
  boxWidth: Length | undefined = undefined;
  // 容器高度（缺省 auto 自适应内容）
  boxHeight: Length | undefined = undefined;
  // 点击回调
  onTap: () => void = () => {};
  // 容器内容（唯一 BuilderParam，支持尾随闭包）
  @BuilderParam content: () => void;

  // 生效配色方案：默认跟随应用主题；仅当调用方显式传 DARK 时强制深色
  private getEffectiveScheme(): GlassColorScheme {
    if (this.colorScheme === GlassColorScheme.DARK) {
      return GlassColorScheme.DARK;
    }
    return StyleManager.getInstance().getThemeMode() === ThemeMode.DARK
      ? GlassColorScheme.DARK
      : GlassColorScheme.LIGHT;
  }

  // 玻璃底色：按配色方案与质感样式取半透明底色
  private getGlassTint(): ResourceColor {
    if (this.getEffectiveScheme() === GlassColorScheme.DARK) {
      return this.glassStyle === GlassStyle.BLUR_THICK ? '#99000000' : '#66000000';
    }
    return this.glassStyle === GlassStyle.BLUR_THICK ? '#99FFFFFF' : '#66FFFFFF';
  }

  build() {
    Stack() {
      this.content()
    }
    .width(this.boxWidth !== undefined ? this.boxWidth : 'auto')
    .height(this.boxHeight !== undefined ? this.boxHeight : 'auto')
    .borderRadius(this.cornerRadius)
    .clip(true)
    .backgroundColor(this.bgColor !== Color.Transparent ? this.bgColor : this.getGlassTint())
    .backdropBlur(this.blurRadius)
    .opacity(this.alpha)
    .enabled(this.pressable)
    .onClick(() => {
      this.onTap();
    })
  }
}

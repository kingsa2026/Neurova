/**
 * GlassNavItem - 玻璃导航项
 *
 * 职责：基于 GlassComponent 体系提供单个导航项，支持图标 + 文字、active 高亮、hover 反馈
 * 设计：Row 布局 [icon] + label；active 时 primary 半透明背景 + primary 文字；
 *       hover 时 primary 8% 半透明背景；collapsed 时仅显示图标列
 *
 * 用法：
 *   GlassNavItem({ label: '首页', icon: $r('app.media.home'), active: true, onClick: () => {} })
 *   GlassNavItem({ label: '设置', icon: $r('app.media.setting'), collapsed: true })
 */

import { StyleManager } from '../../libs/style/StyleManager';

// 样式单例
const sm = StyleManager.getInstance();

@Component
export struct GlassNavItem {
  // 文本标签
  @Prop label: string = '';
  // 图标资源（可选）
  icon: Resource | undefined = undefined;
  // 是否激活（激活时 primary 高亮）
  @Prop active: boolean = false;
  // 是否折叠（折叠时仅显示图标，不渲染 label）
  @Prop collapsed: boolean = false;
  // 点击事件回调
  onClick: () => void = () => {};
  // hover 状态（用于鼠标悬停反馈）
  @State isHovered: boolean = false;

  // 给 hex 颜色（#RRGGBB）叠加 alpha，返回 ArkUI 的 ARGB 格式 #AARRGGBB
  private withAlpha(hex: string, alpha: number): string {
    const a = Math.round(alpha * 255).toString(16).padStart(2, '0').toUpperCase();
    const rgb = hex.startsWith('#') ? hex.slice(1) : hex;
    return `#${a}${rgb}`;
  }

  // 当前背景色：active → primary 0.15 alpha；hover → primary 0.08 alpha；其余透明
  private getBgColor(): ResourceColor {
    if (this.active) {
      return this.withAlpha(sm.getColor('primary'), 0.15);
    }
    if (this.isHovered) {
      return this.withAlpha(sm.getColor('primary'), 0.08);
    }
    return Color.Transparent;
  }

  // 当前文字色：active → primary；其余 text_primary
  private getTextColor(): string {
    return this.active ? sm.getColor('primary') : sm.getColor('text_primary');
  }

  build() {
    Row() {
      // 图标（存在时渲染，折叠与展开态均显示）
      if (this.icon) {
        Image(this.icon)
          .width(20)
          .height(20)
          .fill(this.getTextColor())
          .margin({ right: this.collapsed ? 0 : sm.getSpacing('sm') })
      }
      // 折叠时不显示 label
      if (!this.collapsed) {
        Text(this.label)
          .fontSize(14)
          .fontColor(this.getTextColor())
          .layoutWeight(1)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
      }
    }
    .width('100%')
    .height(40)
    .padding({ left: sm.getSpacing('sm'), right: sm.getSpacing('sm') })
    .justifyContent(this.collapsed ? FlexAlign.Center : FlexAlign.Start)
    .alignItems(VerticalAlign.Center)
    .borderRadius(sm.getRadius('md'))
    .backgroundColor(this.getBgColor())
    .onHover((isHover: boolean) => {
      // 鼠标悬停状态切换，触发背景色重渲染
      this.isHovered = isHover;
    })
    .onClick(() => {
      this.onClick();
    })
  }
}

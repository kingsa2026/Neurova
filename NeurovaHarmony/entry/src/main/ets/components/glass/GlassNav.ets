/**
 * GlassNav - 玻璃侧边导航
 *
 * 职责：基于 GlassComponent 提供侧边导航容器，支持标题、折叠态、列表项渲染
 * 设计：Column 布局 [title] + 滚动列表(items)；collapsed 时宽度减半（width/2），仅显示图标列
 *       容器外层使用 HarmonyOS 6.1 原生 GlassComponent 呈现玻璃质感
 *
 * 用法：
 *   GlassNav({ title: '导航', collapsed: false, width: 240 }) {
 *     GlassNavItem({ label: '首页', icon: $r('app.media.home'), active: true })
 *     GlassNavItem({ label: '设置', icon: $r('app.media.setting') })
 *   }
 */

import { StyleManager } from '../../libs/style/StyleManager';

// 样式单例
const sm = StyleManager.getInstance();

@Component
export struct GlassNav {
  // 顶部标题（折叠时不渲染）
  @Prop title: string = '';
  // 是否折叠（折叠时宽度减半，仅显示图标列）
  @Prop collapsed: boolean = false;
  // 展开宽度；折叠时实际宽度为 width / 2
  @Prop width: number = 240;
  // 导航项列表构建器（内部应使用 GlassNavItem）
  @BuilderParam items: () => void;

  build() {
    GlassComponent({
      glassStyle: GlassStyle.BLUR_THIN,
      blurRadius: 20,
      colorScheme: GlassColorScheme.LIGHT
    }) {
      Column() {
        // 标题区：折叠时不显示，展开且有 title 时渲染
        if (!this.collapsed && this.title) {
          Text(this.title)
            .fontSize(18)
            .fontColor(sm.getColor('text_primary'))
            .padding(sm.getSpacing('md'))
            .width('100%')
        }
        // 导航项滚动列表：纵向可滚动，避免项目过多溢出
        Scroll() {
          Column() {
            this.items();
          }
          .width('100%')
          .alignItems(HorizontalAlign.Start)
        }
        .scrollable(ScrollDirection.Vertical)
        .scrollBar(BarState.Auto)
        .layoutWeight(1)
        .width('100%')
      }
      // 折叠态宽度减半
      .width(this.collapsed ? this.width / 2 : this.width)
      .height('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .borderRadius(sm.getRadius('lg'))
  }
}

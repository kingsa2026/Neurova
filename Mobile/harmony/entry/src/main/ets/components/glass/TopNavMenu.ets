/**
 * TopNavMenu - 顶部导航菜单
 *
 * 职责：基于 GlassComponent 提供顶部导航栏，支持返回按钮、标题、右侧自定义内容、菜单按钮
 * 设计：Row 布局 [back?] + title(layoutWeight:1 居中) + [right?] + [menu?]；
 *       容器外层使用 HarmonyOS 6.1 原生 GlassComponent 呈现玻璃质感；
 *       高度 56vp，宽度 100%
 *
 * 用法：
 *   TopNavMenu({ title: '首页', showBack: true, onBack: () => router.back() }) {
 *     Text('自定义右侧')
 *   }
 */

import { StyleManager } from '../../libs/style/StyleManager';

// 样式单例
const sm = StyleManager.getInstance();

@Component
export struct TopNavMenu {
  // 标题文本
  @Prop title: string = '';
  // 是否显示返回按钮
  @Prop showBack: boolean = false;
  // 是否显示菜单按钮
  @Prop showMenu: boolean = true;
  // 返回按钮点击回调
  onBack: () => void = () => {};
  // 菜单按钮点击回调
  onMenu: () => void = () => {};
  // 右侧自定义内容构建器（未传入时使用空实现占位）
  @BuilderParam right: () => void = this.defaultRight;

  // 默认右侧内容：空实现，供未传入 right 时占位
  @Builder defaultRight() {}

  build() {
    GlassComponent({
      glassStyle: GlassStyle.BLUR_THIN,
      blurRadius: 20,
      colorScheme: GlassColorScheme.LIGHT
    }) {
      Row() {
        // 返回按钮：左箭头
        if (this.showBack) {
          Text('<')
            .fontSize(24)
            .fontColor(sm.getColor('text_primary'))
            .padding({ left: 8, right: 8, top: 4, bottom: 4 })
            .onClick(() => this.onBack());
        }

        // 标题：居中，layoutWeight 撑满剩余空间，单行省略
        Text(this.title)
          .fontSize(18)
          .fontColor(sm.getColor('text_primary'))
          .layoutWeight(1)
          .textAlign(TextAlign.Center)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis });

        // 右侧自定义内容（由外部通过 BuilderParam 注入）
        this.right();

        // 菜单按钮：三个点
        if (this.showMenu) {
          Text('⋯')
            .fontSize(24)
            .fontColor(sm.getColor('text_primary'))
            .padding({ left: 8, right: 8, top: 4, bottom: 4 })
            .onClick(() => this.onMenu());
        }
      }
      .width('100%')
      .height(56)
      .padding({ left: 12, right: 12 })
      .alignItems(VerticalAlign.Center)
    }
    .width('100%')
    .height(56)
  }
}

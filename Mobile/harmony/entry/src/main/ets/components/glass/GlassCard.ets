/**
 * GlassCard - 玻璃卡片
 *
 * 职责：提供带标题、内容的玻璃卡片容器（玻璃质感由 backgroundBlurStyle 实现）
 * 设计：Column 布局 [title/subtitle 头部] + content，头部可选；
 *       仅保留唯一的 @BuilderParam content，以支持尾随闭包用法
 *
 * 用法：
 *   GlassCard({ title: '标题', subtitle: '副标题' }) {
 *     Text('卡片内容')
 *   }
 */

import { StyleManager } from '../../libs/style/StyleManager';

// 样式单例
const sm = StyleManager.getInstance();

@Component
export struct GlassCard {
  // 标题（可选，展示在内容区上方）
  @Prop title: string = '';
  // 副标题
  @Prop subtitle: string = '';
  // 内边距
  @Prop innerPadding: number = 16;
  // 圆角
  @Prop radius: number = 16;
  // 卡片内容（唯一 @BuilderParam，支持尾随闭包）
  @BuilderParam content: () => void;

  build() {
    Column() {
      // 头部：渲染 title/subtitle（可选）
      if (this.title) {
        Column() {
          Text(this.title)
            .fontSize(18)
            .fontColor(sm.getColor('text_primary'))

          if (this.subtitle) {
            Text(this.subtitle)
              .fontSize(14)
              .fontColor(sm.getColor('text_secondary'))
              .margin({ top: 4 })
          }
        }
        .alignItems(HorizontalAlign.Start)
        .width('100%')
      }

      // 内容区（头部存在时顶部留 12 间距，否则不留）
      Column() {
        this.content();
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
      .margin({ top: this.title ? 12 : 0 })
    }
    .padding(this.innerPadding)
    .width('100%')
    .alignItems(HorizontalAlign.Start)
    .borderRadius(this.radius)
    // 原型卡片面：--glass 半透明填充 + --glass-border 描边（不用系统模糊材质——
    // 其色泽跟随窗口色彩模式，暗色主题下会渲染成浅色磨砂，与设计稿的暗玻璃不符）
    .backgroundColor(sm.getColor('glass'))
    .border({ width: 1, color: sm.getColor('border') })
  }
}

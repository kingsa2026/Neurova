/**
 * GlassCard - 玻璃卡片
 *
 * 职责：基于 GlassComponent 提供带标题、内容、底部操作的卡片容器
 * 设计：Column 布局 [header] + content + [footer]，header/footer 可选
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
  // 标题（当未提供 header 时使用）
  @Prop title: string = '';
  // 副标题
  @Prop subtitle: string = '';
  // 内边距
  @Prop padding: number = 16;
  // 圆角
  @Prop radius: number = 16;
  // 自定义头部（覆盖 title/subtitle）
  @BuilderParam header?: () => void;
  // 卡片内容（必填）
  @BuilderParam content: () => void;
  // 卡片底部操作区
  @BuilderParam footer?: () => void;

  build() {
    GlassComponent({
      glassStyle: GlassStyle.BLUR_THIN,
      blurRadius: 20,
      colorScheme: GlassColorScheme.LIGHT
    }) {
      Column() {
        // 头部：优先使用自定义 header，否则渲染 title/subtitle
        if (this.header) {
          Column() {
            this.header();
          }
          .width('100%')
        } else if (this.title) {
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
        .margin({ top: (this.header || this.title) ? 12 : 0 })

        // 底部操作区
        if (this.footer) {
          Column() {
            this.footer();
          }
          .width('100%')
          .margin({ top: 12 })
        }
      }
      .padding(this.padding)
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .borderRadius(this.radius)
  }
}

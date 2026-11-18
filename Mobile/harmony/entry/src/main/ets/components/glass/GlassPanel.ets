/**
 * GlassPanel - 通用玻璃面板容器
 *
 * 职责：提供原型 --glass 卡面容器（半透明填充 + 描边，不用系统模糊材质——
 *       其色泽跟随窗口色彩模式，暗色主题下会渲染成浅色磨砂，与设计稿不符）
 * 设计：通过 variant 区分用途（elevated/subtle 仅保留语义，视觉统一走设计令牌）；
 *       支持自定义圆角、内边距
 *
 * 用法：
 *   GlassPanel({ variant: 'elevated', innerPadding: 20 }) {
 *     Text('内容')
 *   }
 */

import { StyleManager } from '../../libs/style/StyleManager';

// 样式单例
const sm = StyleManager.getInstance();

@Component
export struct GlassPanel {
  // 玻璃面板变体：default | elevated | subtle | prominent（语义保留，视觉统一走令牌）
  @Prop variant: string = 'default';
  // 内边距
  @Prop innerPadding: number = 16;
  // 圆角
  @Prop radius: number = 12;
  // 默认插槽内容
  @BuilderParam content: () => void;

  build() {
    Column() {
      this.content();
    }
    .padding(this.innerPadding)
    .width('100%')
    .borderRadius(this.radius)
    // 原型卡面：--glass 填充 + --glass-border 描边
    .backgroundColor(sm.getColor('glass'))
    .border({ width: 1, color: sm.getColor('border') })
  }
}

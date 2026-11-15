/**
 * GlassPanel - 通用玻璃面板容器
 *
 * 职责：提供通用玻璃效果容器（玻璃质感由 backgroundBlurStyle 实现）
 * 设计：通过 variant 切换模糊材质实现不同质感；支持自定义圆角、内边距、模糊半径
 *
 * 用法：
 *   GlassPanel({ variant: 'elevated', innerPadding: 20 }) {
 *     Text('内容')
 *   }
 */

@Component
export struct GlassPanel {
  // 玻璃面板变体：default | elevated | subtle | prominent
  @Prop variant: string = 'default';
  // 内边距
  @Prop innerPadding: number = 16;
  // 圆角
  @Prop radius: number = 12;
  // 模糊半径
  @Prop blurRadius: number = 20;
  // 默认插槽内容
  @BuilderParam content: () => void;

  // 根据 variant 获取对应的模糊材质
  // elevated / prominent 使用 Thick 呈现更强模糊；其余使用 Thin
  private getGlassStyle(): BlurStyle {
    switch (this.variant) {
      case 'elevated':
      case 'prominent':
        return BlurStyle.Thick;
      case 'subtle':
      case 'default':
      default:
        return BlurStyle.Thin;
    }
  }

  build() {
    Column() {
      this.content();
    }
    .padding(this.innerPadding)
    .width('100%')
    .borderRadius(this.radius)
    .backgroundBlurStyle(this.getGlassStyle())
  }
}

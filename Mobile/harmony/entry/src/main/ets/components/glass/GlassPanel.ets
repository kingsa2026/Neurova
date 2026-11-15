/**
 * GlassPanel - 通用玻璃面板容器
 *
 * 职责：基于 HarmonyOS 6.1 原生 GlassComponent 提供通用玻璃效果容器
 * 设计：通过 variant 切换 GlassStyle 实现不同模糊质感；支持自定义圆角、内边距、模糊半径
 *
 * 用法：
 *   GlassPanel({ variant: 'elevated', padding: 20 }) {
 *     Text('内容')
 *   }
 */

// 注：GlassComponent / GlassStyle / GlassColorScheme 为 HarmonyOS 6.1 原生组件，无需 import

@Component
export struct GlassPanel {
  // 玻璃面板变体：default | elevated | subtle | prominent
  @Prop variant: string = 'default';
  // 内边距
  @Prop padding: number = 16;
  // 圆角
  @Prop radius: number = 12;
  // 模糊半径
  @Prop blurRadius: number = 20;
  // 默认插槽内容
  @BuilderParam content: () => void;

  // 根据 variant 获取对应的 GlassStyle
  // elevated / prominent 使用 BLUR_THICK 呈现更强模糊；其余使用 BLUR_THIN
  private getGlassStyle(): number {
    switch (this.variant) {
      case 'elevated':
      case 'prominent':
        return GlassStyle.BLUR_THICK;
      case 'subtle':
      case 'default':
      default:
        return GlassStyle.BLUR_THIN;
    }
  }

  build() {
    GlassComponent({
      glassStyle: this.getGlassStyle(),
      blurRadius: this.blurRadius,
      colorScheme: GlassColorScheme.LIGHT
    }) {
      Column() {
        this.content();
      }
      .padding(this.padding)
      .width('100%')
    }
    .borderRadius(this.radius)
  }
}

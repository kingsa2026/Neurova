/**
 * TabIcon - 底部导航 / 左侧导航栏的单线图标
 *
 * 职责：以几何原语（Path/Circle/Rect，1.7vp 单线）绘制五枚 Tab 图标，
 *      对照界面布局规划原型的图标体系；零资源依赖（系统符号库无对应名，Path 自绘）
 * 图标：chat（对话）/ home（工作台）/ agent（智能体）/ book（知识）/ user（我的）
 */

@Component
export struct TabIcon {
  /** 图标类别：chat | home | agent | book | user */
  @Prop kind: string = 'chat';
  /** 线条颜色（调用方传 token 色）——@Prop 随激活态刷新 */
  @Prop color: string = '#FFFFFF';
  /** 画布边长（vp），坐标与线宽按比例缩放 */
  @Prop iconSize: number = 24;

  build() {
    // 单 Path 多子路径（24 网格坐标按 iconSize 等比缩放，C 曲线替代 A 弧——渲染确定性最高）
    Path()
      .commands(this.scaledCommands())
      .fillOpacity(0)
      .stroke(this.color)
      .strokeWidth(1.7 * this.iconSize / 24)
      .strokeLineCap(LineCapStyle.Round)
      .strokeLineJoin(LineJoinStyle.Round)
      .width(this.iconSize)
      .height(this.iconSize)
  }

  /**
   * 24 网格绝对坐标整体缩放到目标画布（同 AppIcon）。
   * Path commands 坐标单位是 px（非 vp）：按 iconSize/24 缩放只画出 iconSize px，
   * 视觉约为期望的 1/密度——按 vp2px(iconSize)/24 缩放才铺满 iconSize vp 画布。
   */
  private scaledCommands(): string {
    const raw = this.commands();
    const s = vp2px(this.iconSize) / 24;
    const parts = raw.split(' ');
    const out: string[] = [];
    for (const p of parts) {
      const n = parseFloat(p);
      if (!isNaN(n)) {
        out.push((n * s).toFixed(3));
      } else {
        out.push(p);
      }
    }
    return out.join(' ');
  }

  private commands(): string {
    switch (this.kind) {
      case 'chat':
        return 'M7.5 4 L16.5 4 C18.71 4 20.5 5.79 20.5 7.5 L20.5 14.5 C20.5 16.43 18.71 18 16.5 18 L9 18 L4.6 21.4 C4.1 21.8 3.4 21.4 3.4 20.7 L3.4 7.5 C3.4 5.57 5.57 4 7.5 4 Z M8.5 9 L15.5 9 M8.5 12.5 L13 12.5';
      case 'home':
        return 'M3.4 10.2 L12 3 L20.6 10.2 L20.6 20 L14.2 20 L14.2 14.6 L9.8 14.6 L9.8 20 L3.4 20 Z';
      case 'agent':
        return 'M9.5 7 L14.5 7 C16.71 7 18.5 8.79 18.5 11 L18.5 14.5 C18.5 16.71 16.71 18.5 14.5 18.5 L9.5 18.5 C7.29 18.5 5.5 16.71 5.5 14.5 L5.5 11 C5.5 8.79 7.29 7 9.5 7 Z M12 7 L12 4 M9.7 12.6 L10 12.6 M14 12.6 L14.3 12.6 M9.8 15.4 L14.2 15.4';
      case 'book':
        return 'M5 5.5 C5 4.12 6.12 3 7.5 3 L19 3 L19 18.5 L7.5 18.5 C6.12 18.5 5 19.4 5 20.5 L5 5.5 Z M5 18.5 C5 17.12 6.12 16 7.5 16 L19 16';
      default:
        return 'M12 5.2 C13.88 5.2 15.4 6.72 15.4 8.6 C15.4 10.48 13.88 12 12 12 C10.12 12 8.6 10.48 8.6 8.6 C8.6 6.72 10.12 5.2 12 5.2 Z M4.6 20 C5.4 16.6 8.1 14.6 12 14.6 C15.9 14.6 18.6 16.6 19.4 20';
    }
  }
}

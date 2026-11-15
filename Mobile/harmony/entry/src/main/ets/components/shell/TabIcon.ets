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
  kind: string = 'chat';
  /** 线条颜色（调用方传 token 色） */
  color: string = '#FFFFFF';
  /** 图标边长（vp）——命名避开通用属性 size */
  iconSize: number = 22;

  private stroke(): number {
    return this.iconSize / 24 * 1.7;
  }

  build() {
    Stack() {
      if (this.kind === 'chat') {
        // 气泡外框（圆角矩形轮廓）
        Path()
          .commands('M7.5 4 L16.5 4 C18.433 4 20 5.567 20 7.5 L20 14.5 C20 16.433 18.433 18 16.5 18 L9 18 L4.6 21.4 C4.1 21.8 3.4 21.4 3.4 20.7 L3.4 7.5 C3.4 5.567 5.567 4 7.5 4 Z')
          .fillOpacity(0)
          .stroke(this.color)
          .strokeWidth(this.stroke())
          .strokeLineCap(LineCapStyle.Round)
          .strokeLineJoin(LineJoinStyle.Round)
          .width(this.iconSize)
          .height(this.iconSize)
        // 两行文本线
        Path()
          .commands('M8.5 9 L15.5 9 M8.5 12.5 L13 12.5')
          .fillOpacity(0)
          .stroke(this.color)
          .strokeWidth(this.stroke())
          .strokeLineCap(LineCapStyle.Round)
          .width(this.iconSize)
          .height(this.iconSize)
      } else if (this.kind === 'home') {
        // 屋顶 + 墙体
        Path()
          .commands('M3.4 10.2 L12 3 L20.6 10.2 L20.6 20 L14.2 20 L14.2 14.6 L9.8 14.6 L9.8 20 L3.4 20 Z')
          .fillOpacity(0)
          .stroke(this.color)
          .strokeWidth(this.stroke())
          .strokeLineCap(LineCapStyle.Round)
          .strokeLineJoin(LineJoinStyle.Round)
          .width(this.iconSize)
          .height(this.iconSize)
      } else if (this.kind === 'agent') {
        // 机身
        Rect()
          .width(this.iconSize * 14 / 24)
          .height(this.iconSize * 11 / 24)
          .radiusWidth(this.iconSize * 3.5 / 24)
          .radiusHeight(this.iconSize * 3.5 / 24)
          .fillOpacity(0)
          .stroke(this.color)
          .strokeWidth(this.stroke())
          .translate({ x: this.iconSize * 5 / 24, y: this.iconSize * 7 / 24 })
        // 天线
        Path()
          .commands(`M${this.iconSize / 2} ${this.iconSize * 7 / 24} L${this.iconSize / 2} ${this.iconSize * 4 / 24}`)
          .fillOpacity(0)
          .stroke(this.color)
          .strokeWidth(this.stroke())
          .strokeLineCap(LineCapStyle.Round)
          .width(this.iconSize)
          .height(this.iconSize)
        // 双眼 + 嘴
        Circle()
          .width(this.iconSize * 1.6 / 24)
          .height(this.iconSize * 1.6 / 24)
          .fill(this.color)
          .translate({ x: this.iconSize * 8.6 / 24, y: this.iconSize * 11.8 / 24 })
        Circle()
          .width(this.iconSize * 1.6 / 24)
          .height(this.iconSize * 1.6 / 24)
          .fill(this.color)
          .translate({ x: this.iconSize * 13.8 / 24, y: this.iconSize * 11.8 / 24 })
        Path()
          .commands(`M${this.iconSize * 9.5 / 24} ${this.iconSize * 15.4 / 24} L${this.iconSize * 14.5 / 24} ${this.iconSize * 15.4 / 24}`)
          .fillOpacity(0)
          .stroke(this.color)
          .strokeWidth(this.stroke())
          .strokeLineCap(LineCapStyle.Round)
          .width(this.iconSize)
          .height(this.iconSize)
      } else if (this.kind === 'book') {
        // 书页轮廓
        Path()
          .commands('M5 5.5 C5 4.12 6.12 3 7.5 3 L19 3 L19 18.5 L7.5 18.5 C6.12 18.5 5 19.4 5 20.5 L5 5.5 Z')
          .fillOpacity(0)
          .stroke(this.color)
          .strokeWidth(this.stroke())
          .strokeLineCap(LineCapStyle.Round)
          .strokeLineJoin(LineJoinStyle.Round)
          .width(this.iconSize)
          .height(this.iconSize)
        // 书底
        Path()
          .commands('M5 18.5 C5 17.12 6.12 16 7.5 16 L19 16')
          .fillOpacity(0)
          .stroke(this.color)
          .strokeWidth(this.stroke())
          .strokeLineCap(LineCapStyle.Round)
          .width(this.iconSize)
          .height(this.iconSize)
      } else {
        // user：头 + 肩
        Circle()
          .width(this.iconSize * 7.2 / 24)
          .height(this.iconSize * 7.2 / 24)
          .fillOpacity(0)
          .stroke(this.color)
          .strokeWidth(this.stroke())
          .translate({ x: this.iconSize * 8.4 / 24, y: this.iconSize * 4.6 / 24 })
        Path()
          .commands('M4 20 C4.8 16.6 7.5 14.4 12 14.4 C16.5 14.4 19.2 16.6 20 20')
          .fillOpacity(0)
          .stroke(this.color)
          .strokeWidth(this.stroke())
          .strokeLineCap(LineCapStyle.Round)
          .width(this.iconSize)
          .height(this.iconSize)
      }
    }
    .width(this.iconSize)
    .height(this.iconSize)
  }
}

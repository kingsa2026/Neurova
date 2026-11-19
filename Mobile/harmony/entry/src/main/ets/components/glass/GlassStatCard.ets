/**
 * GlassStatCard - 玻璃统计卡片
 *
 * 职责：提供带标签、数值、单位、趋势的玻璃统计卡片（玻璃质感由 backgroundBlurStyle 实现）
 * 设计：Column 布局
 *         Row [icon] + Column(label + Row(value + unit))
 *         trend（颜色：trendUp → success；false → error）
 *       value 字号 24，label 字号 14；padding 16，radius 12
 *
 * 用法：
 *   GlassStatCard({ label: '会话数', value: '128', unit: '个', trend: '+12%', trendUp: true })
 *   GlassStatCard({ label: '错误率', value: '2.3', unit: '%', trend: '-5%', trendUp: false, icon: $r('app.media.warn') })
 */

import { StyleManager } from '../../libs/style/StyleManager';

// 样式单例
const sm = StyleManager.getInstance();

@Component
export struct GlassStatCard {
  // 标签（描述性文字）
  @Prop label: string = '';
  // 数值
  @Prop value: string = '';
  // 单位（可选）
  @Prop unit: string = '';
  // 趋势文本（如 "+12%"），为空则不渲染趋势行
  @Prop trend: string = '';
  // 是否上升趋势：true → success 色；false → error 色
  @Prop trendUp: boolean = false;
  // 中性趋势（如「共 N 个」）：用第三级文字色，不红不绿
  @Prop trendNeutral: boolean = false;
  // 图标资源（可选，渲染在左侧）
  icon: Resource | undefined = undefined;

  // 趋势文字色：neutral → text_tertiary；trendUp → success；否则 error
  private getTrendColor(): string {
    if (this.trendNeutral) {
      return sm.getColor('text_tertiary');
    }
    return this.trendUp ? sm.getColor('success') : sm.getColor('error');
  }

  build() {
    Column() {
      // 顶部行：图标 + 标签/数值列
      Row() {
        // 左侧图标
        if (this.icon) {
          Image(this.icon)
            .width(24)
            .height(24)
            .fillColor(sm.getColor('primary'))
            .margin({ right: sm.getSpacing('sm') })
        }
        // 右侧标签 + 数值
        Column() {
          Text(this.label)
            .fontSize(14)
            .fontColor(sm.getColor('text_secondary'))
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })

          Row() {
            Text(this.value)
              .fontSize(26)
              .fontWeight(FontWeight.Bold)
              .fontColor(sm.getColor('text_primary'))
            if (this.unit) {
              Text(this.unit)
                .fontSize(14)
                .fontColor(sm.getColor('text_secondary'))
                .margin({ left: 4 })
                .alignSelf(ItemAlign.End)
            }
          }
          .alignItems(VerticalAlign.Bottom)
          .margin({ top: 4 })
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)
      }
      .width('100%')
      .alignItems(VerticalAlign.Top)

      // 趋势行：恒渲染占位（无趋势时透明空格），保证并排卡片等高对齐——
      // 工作台 2×2 里仅右下卡有「共 N 个」，此前有值才渲染导致两列底边不齐
      Text(this.trend.length > 0 ? this.trend : ' ')
        .fontSize(12)
        .fontColor(this.trend.length > 0 ? this.getTrendColor() : 'rgba(0,0,0,0)')
        .margin({ top: sm.getSpacing('sm') })
    }
    .padding(sm.getSpacing('md'))
    .width('100%')
    .alignItems(HorizontalAlign.Start)
    .borderRadius(sm.getRadius('xl'))
    .backgroundColor(sm.getColor('glass'))
    .border({ width: 1, color: sm.getColor('border') })
  }
}

/**
 * StatusPill - 状态胶囊（对照设计文档组件形态：run/queue/done/err 四态）
 *
 * 职责：11/600 徽标字号、全圆角、态色底（10% 透明）+ 同色描边（30%）+ 可选呼吸圆点
 * 用法：StatusPill({ variant: 'run', text: '运行中' })
 */

import { StyleManager, ThemeMode } from '../../libs/style/StyleManager';

const sm = StyleManager.getInstance();

@Component
export struct StatusPill {
  /** 状态变体：run 运行中(绿) | queue 排队(黄) | done 已完成(灰) | err 已中断(红) */
  @Prop variant: string = 'done';
  /** 文案 */
  @Prop text: string = '';
  /** 是否带前置圆点（默认 run 态带） */
  @Prop showDot: boolean = false;

  /** 态主色（文字/圆点/描边） */
  private tone(): string {
    switch (this.variant) {
      case 'run': return sm.getColor('success');
      case 'queue': return sm.getColor('warning');
      case 'err': return sm.getColor('error');
      default: return sm.getColor('text_secondary');
    }
  }

  /** 态底色：主题相关的 10% 透明同色（done 态用中性底） */
  private bg(): string {
    const dark = sm.getThemeMode() === ThemeMode.DARK;
    switch (this.variant) {
      case 'run': return dark ? 'rgba(52,211,153,0.10)' : 'rgba(12,143,94,0.10)';
      case 'queue': return dark ? 'rgba(251,191,36,0.10)' : 'rgba(180,83,9,0.10)';
      case 'err': return dark ? 'rgba(248,113,113,0.10)' : 'rgba(220,38,38,0.10)';
      default: return dark ? 'rgba(255,255,255,0.06)' : 'rgba(21,28,58,0.06)';
    }
  }

  /** 态描边：30% 透明同色 */
  private border(): string {
    const dark = sm.getThemeMode() === ThemeMode.DARK;
    switch (this.variant) {
      case 'run': return dark ? 'rgba(52,211,153,0.30)' : 'rgba(12,143,94,0.30)';
      case 'queue': return dark ? 'rgba(251,191,36,0.30)' : 'rgba(180,83,9,0.30)';
      case 'err': return dark ? 'rgba(248,113,113,0.30)' : 'rgba(220,38,38,0.30)';
      default: return dark ? 'rgba(255,255,255,0.14)' : 'rgba(21,28,58,0.14)';
    }
  }

  build() {
    Row() {
      if (this.showDot || this.variant === 'run') {
        Circle({ width: 5, height: 5 })
          .fill(this.tone())
          .margin({ right: 5 })
      }
      Text(this.text)
        .fontSize(sm.getFontSize('badge'))
        .fontWeight(FontWeight.Medium)
        .fontColor(this.variant === 'done' ? sm.getColor('text_secondary') : this.tone())
    }
    .padding({ left: 10, right: 10, top: 3, bottom: 3 })
    .borderRadius(sm.getRadius('full'))
    .backgroundColor(this.bg())
    .border({ width: 1, color: this.border() })
    .alignItems(VerticalAlign.Center)
  }
}

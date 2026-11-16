/**
 * RailBar - 左侧导航栏（md 断点 ≥600vp，对照原型 04 断点自适应 C/D/E/F）
 *
 * 五入口竖排；承载在 Navigation 导航区形态时即系统 Rail——本组件为
 * ShellPage 的窄内容伴随栏，同用液态玻璃描边语言。
 */

import { StyleManager } from '../../libs/style/StyleManager';
import { TabIcon } from './TabIcon';

@Component
export struct RailBar {
  /** 当前激活 Tab（0-4，同 LiquidTabBar 序）——@Prop 随父刷新 */
  @Prop active: number = 0;
  /** 选择回调 */
  onPick: (index: number) => void = () => {};
  private sm: StyleManager = StyleManager.getInstance();
  private kinds: string[] = ['chat', 'home', 'agent', 'book', 'user'];

  build() {
    Column() {
      ForEach(this.kinds, (kind: string, idx: number) => {
        Column() {
          TabIcon({
            kind: kind,
            color: this.active === idx ? this.sm.getColor('primary') : this.sm.getColor('text_tertiary'),
          })
        }
        .width(34)
        .height(34)
        .borderRadius(11)
        .justifyContent(FlexAlign.Center)
        .backgroundColor(this.active === idx ? this.sm.getColor('primary_soft') : 'rgba(0,0,0,0)')
        .onClick(() => {
          if (this.active !== idx) {
            this.onPick(idx);
          }
        })
      }, (kind: string) => kind)
    }
    .width(56)
    .height('100%')
    .padding({ top: 16 })
    .border({ width: { right: 1 }, color: this.sm.getColor('divider') })
  }
}

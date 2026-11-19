/**
 * TabIcon - 底部导航 / 左侧导航栏的图标
 *
 * 职责：AppIcon 的页签薄壳（kind 即 AppIcon 图标名）。几何/符号统一由 AppIcon
 *      提供（官方 sys.symbol 符号库优先，单一事实源——勿在本组件再画一份）。
 * 图标：chat（对话）/ home（工作台）/ agent（智能体）/ book（知识）/ user（我的）
 */

import { AppIcon } from '../common/AppIcon';

@Component
export struct TabIcon {
  /** 图标类别：chat | home | agent | book | user */
  @Prop kind: string = 'chat';
  /** 颜色（调用方传 token 色）——@Prop 随激活态刷新 */
  @Prop color: string = '#FFFFFF';
  /** 画布边长（vp） */
  @Prop iconSize: number = 24;

  build() {
    AppIcon({ name: this.kind, iconSize: this.iconSize, color: this.color })
  }
}

/**
 * IconBtn - 玻璃图标方钮（对照设计文档 .ibtn：36px、圆角 12、玻璃底+边框）
 *
 * 职责：AppIcon 单线图标 + 玻璃底容器；acc 变体为品牌紫底（.ibtn.acc）
 * 用法：IconBtn({ name: 'search', onTap: () => {} })；IconBtn({ name: 'plus', accent: true })
 */

import { StyleManager } from '../../libs/style/StyleManager';
import { AppIcon } from './AppIcon';

const sm = StyleManager.getInstance();

@Component
export struct IconBtn {
  /** 图标名（AppIcon 全集） */
  @Prop name: string = 'info';
  /** acc 变体：品牌紫玻璃底 */
  @Prop accent: boolean = false;
  /** 图标大小（vp），默认 17 */
  @Prop iconSize: number = 17;
  /** 点击回调 */
  onTap: () => void = () => {};

  build() {
    Column() {
      AppIcon({
        name: this.name,
        iconSize: this.iconSize,
        color: this.accent ? sm.getColor('primary') : sm.getColor('text_primary')
      })
    }
    .width(36)
    .height(36)
    .borderRadius(12)
    .backgroundColor(this.accent ? sm.getColor('primary_soft') : sm.getColor('glass'))
    .border({ width: 1, color: this.accent ? sm.getColor('primary') : sm.getColor('border') })
    .justifyContent(FlexAlign.Center)
    .alignItems(HorizontalAlign.Center)
    .onClick(() => {
      this.onTap();
    })
  }
}

/**
 * LiquidTabBar - 底部五 Tab 悬浮液态玻璃胶囊（sm 断点，对照原型 F3/F4）
 *
 * 材质：backgroundBlurStyle(COMPONENT_REGULAR) 实时模糊 + 顶部镜面高光描边。
 *       SDK 另有系统材质模板路线（EffectComponent 容器 + 子项 useEffect(true,
 *       EffectType.WINDOW_EFFECT)），其容器声明在本机 SDK 仅存于组件注册表
 *       （component_config.json / effect_component.json，无公开 d.ts 签名），
 *       编译期无法核实构建子签名——本组件先用 blurStyle 路线，切系统材质
 *       待 EffectComponent 签名实证后替换（原型注解已注明两路线）。
 */

import { StyleManager, ThemeMode } from '../../libs/style/StyleManager';
import { TabIcon } from './TabIcon';

@Component
export struct LiquidTabBar {
  /** 当前激活 Tab（0 对话 / 1 工作台 / 2 智能体 / 3 知识 / 4 我的）——@Prop 随父刷新 */
  @Prop active: number = 0;
  /** 选择回调（命名避开通用属性 onSelect） */
  onPick: (index: number) => void = () => {};
  private sm: StyleManager = StyleManager.getInstance();
  private labels: string[] = ['对话', '工作台', '智能体', '知识', '我的'];
  private kinds: string[] = ['chat', 'home', 'agent', 'book', 'user'];

  build() {
    Row() {
      ForEach(this.labels, (label: string, idx: number) => {
        Column() {
          Stack() {
            // 激活态：紫晕光斑 + 顶部指示条
            if (this.active === idx) {
              Column()
                .width(38)
                .height(34)
                .borderRadius(16)
                .backgroundColor(this.sm.getColor('primary_soft'))
            }
            TabIcon({ kind: this.kinds[idx], color: this.active === idx ? this.sm.getColor('primary') : this.sm.getColor('text_tertiary'), iconSize: 21 })
          }
          .height(38)

          Text(label)
            .fontSize(10)
            .fontColor(this.active === idx ? this.sm.getColor('primary') : this.sm.getColor('text_tertiary'))
        }
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .onClick(() => {
          if (this.active !== idx) {
            this.onPick(idx);
          }
        })
      }, (label: string) => label)
    }
    .width('100%')
    .height(64)
    .padding({ left: 6, right: 6 })
    .borderRadius(32)
    .backgroundBlurStyle(BlurStyle.COMPONENT_REGULAR)
    .backgroundColor(this.sm.getThemeMode() === ThemeMode.DARK ? 'rgba(14,18,34,0.50)' : 'rgba(255,255,255,0.62)')
    .border({ width: 1, color: this.sm.getColor('border') })
    .shadow({ radius: 24, color: 'rgba(0,0,0,0.35)', offsetY: 8 })
  }
}

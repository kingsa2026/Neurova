/**
 * GlassInput - 玻璃输入框
 *
 * 职责：基于 GlassComponent 包装 TextInput，提供玻璃质感输入框
 * 设计：支持 text/password/number 三种类型、前缀图标、禁用态、最大长度限制
 *
 * 用法：
 *   GlassInput({
 *     placeholder: '请输入',
 *     value: this.text,
 *     type: 'text',
 *     onChange: (v) => { this.text = v; }
 *   })
 */

import { StyleManager } from '../../libs/style/StyleManager';

// 样式单例
const sm = StyleManager.getInstance();

@Component
export struct GlassInput {
  // 占位提示文本
  @Prop placeholder: string = '';
  // 当前输入值（受控）
  @Prop value: string = '';
  // 输入类型：text | password | number
  @Prop type: string = 'text';
  // 最大输入长度
  @Prop maxLength: number = 200;
  // 是否禁用
  @Prop disabled: boolean = false;
  // 前缀图标资源（可选）
  prefixIcon: Resource | undefined = undefined;
  // 输入变化回调
  onChange: (value: string) => void = () => {};
  // 提交回调
  onSubmit: (value: string) => void = () => {};

  // 映射输入类型到 TextInputType
  private getInputType(): TextInputType {
    switch (this.type) {
      case 'password':
        return TextInputType.Password;
      case 'number':
        return TextInputType.Number;
      default:
        return TextInputType.Normal;
    }
  }

  build() {
    GlassComponent({
      glassStyle: GlassStyle.BLUR_THIN,
      blurRadius: 20,
      colorScheme: GlassColorScheme.LIGHT
    }) {
      Row() {
        // 前缀图标
        if (this.prefixIcon) {
          Image(this.prefixIcon)
            .width(20)
            .height(20)
            .margin({ right: 8 })
        }
        // 输入框：背景透明以透出玻璃效果
        TextInput({ placeholder: this.placeholder, text: this.value })
          .type(this.getInputType())
          .maxLength(this.maxLength)
          .fontSize(16)
          .fontColor(sm.getColor('text_primary'))
          .placeholderColor(sm.getColor('text_disabled'))
          .backgroundColor(Color.Transparent)
          .layoutWeight(1)
          .enabled(!this.disabled)
          .onChange((v: string) => {
            this.onChange(v);
          })
          .onSubmit((v: string) => {
            this.onSubmit(v);
          })
      }
      .width('100%')
      .padding({ left: 12, right: 12, top: 8, bottom: 8 })
      .alignItems(VerticalAlign.Center)
    }
    .borderRadius(sm.getRadius('lg'))
  }
}

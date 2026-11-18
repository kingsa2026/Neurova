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
import { GlassComponent, GlassStyle, GlassColorScheme } from './GlassComponent';
import { AppIcon } from '../common/AppIcon';

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
  // 前缀图标名（AppIcon 单线图标，优先于 prefixIcon 资源）
  iconName: string = '';
  // 密码可见性切换（type=password 时渲染眼睛钮，设计 F1 .field .eye）
  passwordToggle: boolean = false;
  // 容器圆角（默认 12；胶囊输入框传 999，设计 F5 .inputbar .fld）
  @Prop cornerRadius: number = 12;
  @State private showPassword: boolean = false;
  // 输入变化回调
  onChange: (value: string) => void = () => {};
  // 提交回调
  onSubmit: (value: string) => void = () => {};

  // 映射输入类型到 ArkUI 全局 InputType 枚举（TextInput.type 的形参类型）；
  // password 且已切换可见时用 Normal 透出明文
  private getInputType(): InputType {
    if (this.type === 'password' && !this.showPassword) {
      return InputType.Password;
    }
    if (this.type === 'number') {
      return InputType.Number;
    }
    return InputType.Normal;
  }

  build() {
    GlassComponent({
      glassStyle: GlassStyle.BLUR_THIN,
      blurRadius: 20,
      colorScheme: GlassColorScheme.LIGHT,
      cornerRadius: this.cornerRadius
    }) {
      Row() {
        // 前缀图标（单线图标优先）
        if (this.iconName !== '') {
          AppIcon({ name: this.iconName, iconSize: 16, color: sm.getColor('text_tertiary') })
            .margin({ right: 8 })
        } else if (this.prefixIcon) {
          Image(this.prefixIcon)
            .width(20)
            .height(20)
            .margin({ right: 8 })
        }
        // 输入框：背景透明以透出玻璃效果；密码切换时隐藏系统默认眼睛（避免双眼睛图标）
        TextInput({ placeholder: this.placeholder, text: this.value })
          .type(this.getInputType())
          .maxLength(this.maxLength)
          .fontSize(sm.getFontSize('body_sm'))
          .fontColor(sm.getColor('text_primary'))
          .placeholderColor(sm.getColor('text_disabled'))
          .backgroundColor(Color.Transparent)
          .showPasswordIcon(this.type === 'password' && !this.passwordToggle)
          .layoutWeight(1)
          .enabled(!this.disabled)
          .onChange((v: string) => {
            // 属性同步回声不外抛：父层重渲染把 text 属性重设为受控值时 TextInput
            // 也会触发 onChange——照抛就把「渲染」变成「写状态」（设置页曾因此在
            // 进页瞬间把服务端主题值回写并应用，整窗翻白）。只放行真实编辑。
            if (v === this.value) {
              return;
            }
            this.onChange(v);
          })
          .onSubmit((_enterKey: EnterKeyType, event: SubmitEvent) => {
            // 适配 SDK 的 OnSubmitCallback 签名（(enterKey, event) => void）；
            // 对外契约保持 (value: string) => void，回传提交时输入框内的文本
            this.onSubmit(event.text);
          })

        // 密码可见性切换（眼睛钮）
        if (this.type === 'password' && this.passwordToggle) {
          Column() {
            AppIcon({ name: 'eye', iconSize: 16, color: sm.getColor('text_tertiary') })
          }
          .width(32)
          .height(32)
          .justifyContent(FlexAlign.Center)
          .onClick(() => {
            this.showPassword = !this.showPassword;
          })
        }
      }
      .width('100%')
      .padding({ left: 12, right: 12, top: 8, bottom: 8 })
      .alignItems(VerticalAlign.Center)
    }
  }
}

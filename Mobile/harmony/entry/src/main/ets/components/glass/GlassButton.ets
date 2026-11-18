/**
 * GlassButton - 玻璃按钮
 *
 * 职责：基于 GlassComponent 提供玻璃质感按钮，支持 4 种类型与 3 种尺寸
 * 设计：type 控制配色（primary/default/danger/ghost），size 控制内边距，disabled 控制交互与透明度
 *
 * 用法：
 *   GlassButton({ text: '确定', type: 'primary', block: true, onTap: () => {} })
 *   GlassButton({ type: 'default', onTap: () => {} }) {
 *     Text('自定义内容')
 *   }
 */

import { StyleManager } from '../../libs/style/StyleManager';
import { GlassComponent, GlassStyle, GlassColorScheme } from './GlassComponent';

// 样式单例
const sm = StyleManager.getInstance();

@Component
export struct GlassButton {
  // 按钮文本（当未提供 content 时使用）
  @Prop text: string = '';
  // 按钮类型：primary | default | danger | ghost | gradient（品牌渐变，设计 .btn-pri）
  @Prop type: string = 'default';
  // 按钮尺寸：small | medium | large
  @Prop btnSize: string = 'medium';
  // 是否禁用
  @Prop disabled: boolean = false;
  // 是否撑满父容器宽度
  @Prop block: boolean = false;
  // 自定义按钮内容（覆盖 text）
  @BuilderParam content?: () => void;
  // 点击事件回调
  onTap: () => void = () => {};

  // 根据 size 获取内边距：small(8,16) medium(12,24) large(16,32)
  private getSizePadding(): Padding {
    switch (this.btnSize) {
      case 'small':
        return { top: 8, bottom: 8, left: 16, right: 16 };
      case 'large':
        return { top: 16, bottom: 16, left: 32, right: 32 };
      case 'medium':
      default:
        return { top: 12, bottom: 12, left: 24, right: 24 };
    }
  }

  // 根据 type 获取文字颜色：primary/danger/gradient 白字，其余 text_primary
  private getTextColor(): string {
    switch (this.type) {
      case 'primary':
      case 'danger':
      case 'gradient':
        return '#ffffff';
      default:
        return sm.getColor('text_primary');
    }
  }

  // 根据 type 获取背景色：primary→主色，danger→错误色，gradient→透明（渐变在渐变层叠加），
  // 其余透明（交由 GlassComponent 呈现玻璃）
  private getBackgroundColor(): ResourceColor {
    switch (this.type) {
      case 'primary':
        return sm.getColor('primary');
      case 'danger':
        return sm.getColor('error');
      default:
        return Color.Transparent;
    }
  }

  // 是否为品牌渐变型（.btn-pri：135° 三停渐变 + 品牌投影）
  private isGradient(): boolean {
    return this.type === 'gradient';
  }

  // 是否为 ghost 类型（仅边框无背景）
  private isGhost(): boolean {
    return this.type === 'ghost';
  }

  // 按钮文案/自定义内容（两分支共用）
  @Builder
  btnContent() {
    if (this.content) {
      this.content();
    } else {
      Text(this.text)
        .fontSize(16)
        .fontColor(this.getTextColor())
    }
  }

  // 按钮内部内容（抽取为 Builder 以在 block/非 block 两个分支复用）；
  // gradient 型的渐变层须撑满按钮（.btn-pri 整面渐变）——内容宽渐变在玻璃容器里
  // 会缩成中央小块（登录页主按钮曾如此）；其余走纯色/玻璃
  @Builder
  buildInner() {
    if (this.isGradient()) {
      Row() {
        this.btnContent()
      }
      .width(this.block ? '100%' : 'auto')
      .padding(this.getSizePadding())
      .justifyContent(FlexAlign.Center)
      .borderRadius(sm.getRadius('lg'))
      .linearGradient({
        angle: 135,
        colors: sm.getBrandGradient()
      })
      .shadow({ radius: 24, color: 'rgba(99,102,241,0.40)', offsetY: 8 })
    } else {
      Row() {
        this.btnContent()
      }
      .padding(this.getSizePadding())
      .justifyContent(FlexAlign.Center)
      .backgroundColor(this.getBackgroundColor())
      .border(this.isGhost() ? { width: 1, color: sm.getColor('border') } : { width: 0, color: Color.Transparent })
    }
  }

  build() {
    if (this.block) {
      // 撑满父容器宽度
      GlassComponent({
        glassStyle: GlassStyle.BLUR_THIN,
        blurRadius: 20,
        colorScheme: GlassColorScheme.LIGHT,
        boxWidth: '100%',
        cornerRadius: sm.getRadius('lg'),
        alpha: this.disabled ? 0.5 : 1,
        pressable: !this.disabled,
        onTap: () => {
          this.onTap();
        }
      }) {
        this.buildInner()
      }
    } else {
      // 内容宽度
      GlassComponent({
        glassStyle: GlassStyle.BLUR_THIN,
        blurRadius: 20,
        colorScheme: GlassColorScheme.LIGHT,
        cornerRadius: sm.getRadius('lg'),
        alpha: this.disabled ? 0.5 : 1,
        pressable: !this.disabled,
        onTap: () => {
          this.onTap();
        }
      }) {
        this.buildInner()
      }
    }
  }
}

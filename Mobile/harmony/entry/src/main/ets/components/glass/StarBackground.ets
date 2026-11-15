/**
 * StarBackground - 星空背景
 *
 * 职责：提供深蓝紫渐变背景 + 随机分布的白色星点装饰，支持闪烁动画
 * 设计：Stack 容器叠加 [渐变背景层] + [ForEach 星点层]；
 *       星点位置、大小、延迟在 aboutToAppear 中随机生成（位置用 0-1 比例，自适应容器尺寸）；
 *       闪烁通过 @State phase 周期切换 + .animation() 属性动画实现平滑过渡；
 *       星点按 delay 分两组错峰闪烁，避免整齐划一
 *
 * 用法：
 *   StarBackground({ starCount: 80, twinkle: true })
 */

/** 单颗星的数据结构 */
interface Star {
  /** 横向比例位置 0-1 */
  x: number;
  /** 纵向比例位置 0-1 */
  y: number;
  /** 星点大小（vp），范围 1-3 */
  size: number;
  /** 闪烁延迟（毫秒），用于将星点分为两组实现错峰效果 */
  delay: number;
}

@Component
export struct StarBackground {
  // 星星数量
  @Prop starCount: number = 50;
  // 是否启用闪烁动画
  @Prop twinkle: boolean = true;
  // 星点数据（aboutToAppear 中生成）
  @State stars: Star[] = [];
  // 闪烁相位（0/1 之间周期切换，驱动透明度变化）
  @State phase: number = 0;
  // 闪烁定时器句柄（-1 表示未启动）
  private timer: number = -1;

  aboutToAppear() {
    this.generateStars();
    if (this.twinkle) {
      this.startTwinkle();
    }
  }

  aboutToDisappear() {
    this.stopTwinkle();
  }

  // 随机生成星点：位置 0-1、大小 1-3vp、延迟 0-3000ms
  private generateStars(): void {
    const list: Star[] = [];
    for (let i = 0; i < this.starCount; i++) {
      list.push({
        x: Math.random(),
        y: Math.random(),
        size: 1 + Math.random() * 2,
        delay: Math.random() * 3000,
      });
    }
    this.stars = list;
  }

  // 启动闪烁：每 2 秒切换一次相位，.animation() 修饰符会平滑过渡透明度
  private startTwinkle(): void {
    this.timer = setInterval(() => {
      this.phase = (this.phase + 1) % 2;
    }, 2000);
  }

  // 停止闪烁并清理定时器，避免组件销毁后内存泄漏
  private stopTwinkle(): void {
    if (this.timer !== -1) {
      clearInterval(this.timer);
      this.timer = -1;
    }
  }

  // 计算单颗星的当前透明度：
  // - 不闪烁：固定 0.8
  // - 闪烁：按 delay 分组（< 1500ms 与 >= 1500ms），两组反相闪烁形成错峰效果
  private getStarOpacity(star: Star): number {
    if (!this.twinkle) {
      return 0.8;
    }
    const groupOffset = star.delay < 1500 ? 0 : 1;
    const isHigh = (this.phase + groupOffset) % 2 === 0;
    return isHigh ? 1.0 : 0.3;
  }

  build() {
    Stack() {
      // 渐变背景层：深蓝紫自上而下渐变
      Column()
        .width('100%')
        .height('100%')
        .linearGradient({
          angle: 180,
          colors: [['#0a0e27', 0], ['#1a1a3e', 1]]
        });

      // 星点层：ForEach 渲染所有星点，使用 position 绝对定位
      ForEach(this.stars, (star: Star, idx: number) => {
        Circle({ width: star.size, height: star.size })
          .fill('#ffffff')
          .opacity(this.getStarOpacity(star))
          .animation({ duration: 2000, curve: Curve.EaseInOut })
          .position({ x: `${star.x * 100}%`, y: `${star.y * 100}%` })
      }, (star: Star, idx: number) => idx.toString());
    }
    .width('100%')
    .height('100%')
  }
}

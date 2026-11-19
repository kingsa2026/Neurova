/**
 * AppIcon - 全量图标库
 *
 * 职责：优先走官方系统符号库 SymbolGlyph（sys.symbol.*，华为设计系统标准单色
 *      符号，自动跟随深浅色与字重，形状/尺寸由系统保证）；少数系统库没有的
 *      名字（spark/fork/graph/globe）回退 Path 手绘（24 网格 1.7 线宽 monoline，
 *      A 弧以 C 三次曲线近似）。
 * 填充型回退图标（spark/stop/more）走 fill，其余回退走 stroke。
 *
 * 用法：AppIcon({ name: 'search', iconSize: 17, color: sm.getColor('text_primary') })
 */

@Component
export struct AppIcon {
  /** 图标名（见 symbolRes()/pathFor() 的 case 清单） */
  @Prop name: string = 'info';
  /** 画布边长（vp），线条粗细按比例缩放（命名避开通用属性 size） */
  @Prop iconSize: number = 24;
  /** 线条/填充颜色（调用方传 token 色） */
  @Prop color: string = '#FFFFFF';

  /**
   * sys.symbol 映射表：命中走官方符号库，未命中（返回 undefined）走 Path 回退。
   * 资源名必须是字面量 $r()（编译期解析），故用 switch 而非查表字符串拼接。
   */
  private symbolRes(): Resource | undefined {
    switch (this.name) {
      case 'chat': return $r('sys.symbol.message');
      case 'home': return $r('sys.symbol.house');
      case 'agent': return $r('sys.symbol.robot');
      case 'book': return $r('sys.symbol.book');
      case 'user': return $r('sys.symbol.person');
      case 'search': return $r('sys.symbol.magnifyingglass');
      case 'plus': return $r('sys.symbol.plus');
      case 'bell': return $r('sys.symbol.bell');
      case 'mic': return $r('sys.symbol.mic');
      case 'clip': return $r('sys.symbol.paperclip');
      case 'send': return $r('sys.symbol.paperplane');
      case 'stop': return $r('sys.symbol.stop_circle');
      case 'back': return $r('sys.symbol.chevron_left');
      case 'chev': return $r('sys.symbol.chevron_right');
      case 'more': return $r('sys.symbol.more');
      case 'pin': return $r('sys.symbol.pin');
      case 'archive': return $r('sys.symbol.archivebox');
      case 'edit': return $r('sys.symbol.square_and_pencil');
      case 'scan': return $r('sys.symbol.qrcode');
      case 'check': return $r('sys.symbol.checkmark');
      case 'gear': return $r('sys.symbol.gearshape');
      case 'server': return $r('sys.symbol.externaldrive');
      case 'shield': return $r('sys.symbol.checkmark_shield');
      case 'folder': return $r('sys.symbol.folder');
      case 'task': return $r('sys.symbol.doc_text');
      case 'moon': return $r('sys.symbol.moon');
      case 'palette': return $r('sys.symbol.paintpalette');
      case 'logout': return $r('sys.symbol.arrow_right_to_line');
      case 'info': return $r('sys.symbol.info_circle');
      case 'lock': return $r('sys.symbol.lock');
      case 'mail': return $r('sys.symbol.envelope');
      case 'model': return $r('sys.symbol.square_grid_2x2');
      case 'history': return $r('sys.symbol.clock');
      case 'signal': return $r('sys.symbol.signal');
      case 'batt': return $r('sys.symbol.battery');
      case 'wifi': return $r('sys.symbol.wifi');
      case 'link': return $r('sys.symbol.link');
      case 'pause': return $r('sys.symbol.pause');
      case 'eye': return $r('sys.symbol.eye');
      case 'sun': return $r('sys.symbol.sun_min');
      default: return undefined;
    }
  }

  /** 填充型图标：spark 四芒星 / stop 停止块 / more 三点（仅 Path 回退分支使用） */
  private isFilled(): boolean {
    return this.name === 'spark' || this.name === 'stop' || this.name === 'more';
  }

  build() {
    if (this.symbolRes() !== undefined) {
      SymbolGlyph(this.symbolRes())
        .fontSize(this.iconSize)
        .fontColor([this.color])
    } else {
      Path()
        .commands(this.scaledCommands())
        .fillOpacity(this.isFilled() ? 1 : 0)
        .fill(this.color)
        .stroke(this.color)
        .strokeWidth(1.7 * this.iconSize / 24)
        .strokeLineCap(LineCapStyle.Round)
        .strokeLineJoin(LineJoinStyle.Round)
        .width(this.iconSize)
        .height(this.iconSize)
    }
  }

  /**
   * 24 网格绝对坐标整体缩放到目标画布。
   * Path commands 的坐标单位是 px（非 vp）：按 iconSize/24 缩放只会画出
   * iconSize 个 px（约为期望的 1/密度）——真机反馈「图标还是小」的根因。
   * 必须换算成 px：按 vp2px(iconSize)/24 等比缩放，图形才铺满 iconSize vp 画布。
   */
  private scaledCommands(): string {
    const raw = this.commands();
    const s = vp2px(this.iconSize) / 24;
    const parts = raw.split(' ');
    const out: string[] = [];
    for (const p of parts) {
      const n = parseFloat(p);
      if (!isNaN(n)) {
        out.push((n * s).toFixed(3));
      } else {
        out.push(p);
      }
    }
    return out.join(' ');
  }

  private commands(): string {
    return AppIcon.pathFor(this.name);
  }

  /**
   * 图标几何单一事实源（TabIcon 同名页签图标亦从此取，勿在两处各画一份）。
   * 24 网格绝对坐标 + 1.7 线宽 + 圆头；放大到 28vp 后原手绘几何的形状缺陷
   * 会暴露（真机反馈「图标大小不适配/不像」），重画时按标准 monoline 结构：
   * 气泡=圆角矩形+短尾、房屋=屋顶/墙体/门三段、机器人=圆角方+天线+双眼、
   * 书=左右对开页、人像=小头+低肩弧（头肩留隙）。
   */
  static pathFor(name: string): string {
    switch (name) {
      case 'spark':
        return 'M12 2.5 L14 9.5 L21 12 L14 14.5 L12 21.5 L10 14.5 L3 12 L10 9.5 Z';
      case 'chat':
        return 'M6.5 4 L17.5 4 C19 4 20 5 20 6.5 L20 13.5 C20 15 19 16 17.5 16 L9 16 L5.2 19 C4.7 19.4 4 19.1 4 18.4 L4 6.5 C4 5 5 4 6.5 4 Z M8 8.8 L16 8.8 M8 12 L13 12';
      case 'agent':
        return 'M8 8.5 L16 8.5 C18.2 8.5 19.5 9.8 19.5 12 L19.5 14.5 C19.5 16.7 18.2 18 16 18 L8 18 C5.8 18 4.5 16.7 4.5 14.5 L4.5 12 C4.5 9.8 5.8 8.5 8 8.5 Z M12 8.5 L12 5.5 M10.6 4.6 L13.4 4.6 M9 12.6 L9.01 12.6 M15 12.6 L15.01 12.6 M9.5 15.2 L14.5 15.2';
      case 'home':
        return 'M3.5 10.5 L12 3.5 L20.5 10.5 M5.5 8.8 L5.5 20.5 L18.5 20.5 L18.5 8.8 M10 20.5 L10 14.5 L14 14.5 L14 20.5';
      case 'book':
        return 'M12 6 C10.5 4.8 8.5 4.2 5.5 4.2 L5.5 17.5 C8.5 17.5 10.5 18.1 12 19.3 M12 6 C13.5 4.8 15.5 4.2 18.5 4.2 L18.5 17.5 C15.5 17.5 13.5 18.1 12 19.3';
      case 'user':
        return 'M12 4.6 C14 4.6 15.6 6.2 15.6 8.2 C15.6 10.2 14 11.8 12 11.8 C10 11.8 8.4 10.2 8.4 8.2 C8.4 6.2 10 4.6 12 4.6 Z M4.8 20 C4.8 16.2 8 13.8 12 13.8 C16 13.8 19.2 16.2 19.2 20';
      case 'search':
        return 'M4.8 11 C4.8 7.58 7.58 4.8 11 4.8 C14.42 4.8 17.2 7.58 17.2 11 C17.2 14.42 14.42 17.2 11 17.2 C7.58 17.2 4.8 14.42 4.8 11 Z M15.6 15.6 L19.6 19.6';
      case 'plus':
        return 'M12 5 L12 19 M5 12 L19 12';
      case 'bell':
        return 'M6 10 C6 6.69 8.69 4 12 4 C15.31 4 18 6.69 18 10 C18 14 19.5 15.5 19.5 15.5 L4.5 15.5 C4.5 15.5 6 14 6 10 Z M10 19 C10 20.2 11 21 12 21 C13 21 14 20.2 14 19';
      case 'mic':
        return 'M12 3.5 C13.66 3.5 15 4.84 15 6.5 L15 11.5 C15 13.16 13.66 14.5 12 14.5 C10.34 14.5 9 13.16 9 11.5 L9 6.5 C9 4.84 10.34 3.5 12 3.5 Z M5.5 11.5 C5.5 15.08 8.42 18 12 18 C15.58 18 18.5 15.08 18.5 11.5 M12 18 L12 20.5';
      case 'clip':
        return 'M8.5 12.5 L14.7 6.3 C15.9 5.1 17.9 5.1 19.1 6.3 C20.3 7.5 20.3 9.5 19.1 10.7 L11.6 18.2 C9.8 20 6.9 20 5.1 18.2 C3.3 16.4 3.3 13.5 5.1 11.7 L12.6 4.2';
      case 'send':
        return 'M5 12 L20 4.5 L15.5 20 L12 14 L5 12 Z M12 14 L20 4.5';
      case 'stop':
        return 'M9.5 7 L14.5 7 C16.43 7 17 7.57 17 9.5 L17 14.5 C17 16.43 16.43 17 14.5 17 L9.5 17 C7.57 17 7 16.43 7 14.5 L7 9.5 C7 7.57 7.57 7 9.5 7 Z';
      case 'back':
        return 'M14.5 5.5 L7.5 12 L14.5 18.5';
      case 'chev':
        return 'M9.5 5.5 L16.5 12 L9.5 18.5';
      case 'more':
        return 'M4.1 12 C4.1 11.23 4.73 10.6 5.5 10.6 C6.27 10.6 6.9 11.23 6.9 12 C6.9 12.77 6.27 13.4 5.5 13.4 C4.73 13.4 4.1 12.77 4.1 12 Z M10.6 12 C10.6 11.23 11.23 10.6 12 10.6 C12.77 10.6 13.4 11.23 13.4 12 C13.4 12.77 12.77 13.4 12 13.4 C11.23 13.4 10.6 12.77 10.6 12 Z M17.1 12 C17.1 11.23 17.73 10.6 18.5 10.6 C19.27 10.6 19.9 11.23 19.9 12 C19.9 12.77 19.27 13.4 18.5 13.4 C17.73 13.4 17.1 12.77 17.1 12 Z';
      case 'pin':
        return 'M9 3.5 L15 3.5 M12 3.5 L12 9.5 M7.5 9.5 L16.5 9.5 L18 13.5 L6 13.5 L7.5 9.5 Z M12 13.5 L12 20.5';
      case 'archive':
        return 'M5.2 4.5 L18.8 4.5 C19.46 4.5 20 5.04 20 5.7 L20 7.3 C20 7.96 19.46 8.5 18.8 8.5 L5.2 8.5 C4.54 8.5 4 7.96 4 7.3 L4 5.7 C4 5.04 4.54 4.5 5.2 4.5 Z M5.5 8.5 L5.5 18 C5.5 18.83 6.17 19.5 7 19.5 L17 19.5 C17.83 19.5 18.5 18.83 18.5 18 L18.5 8.5 M10 12.5 L14 12.5';
      case 'fork':
        return 'M4.7 5.5 C4.7 4.23 5.73 3.2 7 3.2 C8.27 3.2 9.3 4.23 9.3 5.5 C9.3 6.77 8.27 7.8 7 7.8 C5.73 7.8 4.7 6.77 4.7 5.5 Z M4.7 18.5 C4.7 17.23 5.73 16.2 7 16.2 C8.27 16.2 9.3 17.23 9.3 18.5 C9.3 19.77 8.27 20.8 7 20.8 C5.73 20.8 4.7 19.77 4.7 18.5 Z M14.7 9.5 C14.7 8.23 15.73 7.2 17 7.2 C18.27 7.2 19.3 8.23 19.3 9.5 C19.3 10.77 18.27 11.8 17 11.8 C15.73 11.8 14.7 10.77 14.7 9.5 Z M7 7.8 L7 16.2 M17 11.8 C17 14.8 13.5 15.2 9.5 16.2';
      case 'edit':
        return 'M14.5 5 L19 9.5 L8.5 20 L4 20 L4 15.5 L14.5 5 Z';
      case 'scan':
        return 'M4 8 L4 6 C4 4.9 4.9 4 6 4 L8 4 M16 4 L18 4 C19.1 4 20 4.9 20 6 L20 8 M20 16 L20 18 C20 19.1 19.1 20 18 20 L16 20 M8 20 L6 20 C4.9 20 4 19.1 4 18 L4 16 M4 12 L20 12';
      case 'check':
        return 'M5 12.5 L9.5 17 L19 7.5';
      case 'gear':
        return 'M9 12 C9 10.34 10.34 9 12 9 C13.66 9 15 10.34 15 12 C15 13.66 13.66 15 12 15 C10.34 15 9 13.66 9 12 Z M12 3.5 L12 5.8 M12 18.2 L12 20.5 M3.5 12 L5.8 12 M18.2 12 L20.5 12 M6 6 L7.6 7.6 M16.4 16.4 L18 18 M18 6 L16.4 7.6 M7.6 16.4 L6 18';
      case 'server':
        return 'M6 4 L18 4 C19.1 4 20 4.9 20 6 L20 9 C20 10.1 19.1 11 18 11 L6 11 C4.9 11 4 10.1 4 9 L4 6 C4 4.9 4.9 4 6 4 Z M6 13 L18 13 C19.1 13 20 13.9 20 15 L20 18 C20 19.1 19.1 20 18 20 L6 20 C4.9 20 4 19.1 4 18 L4 15 C4 13.9 4.9 13 6 13 Z M7.5 7.5 L7.51 7.5 M7.5 16.5 L7.51 16.5';
      case 'shield':
        return 'M12 3.5 L19 6 L19 12 C19 16.5 16 19.5 12 21 C8 19.5 5 16.5 5 12 L5 6 Z';
      case 'folder':
        return 'M4 7 C4 5.9 4.9 5 6 5 L10 5 L12 7.5 L18 7.5 C19.1 7.5 20 8.4 20 9.5 L20 17 C20 18.1 19.1 19 18 19 L6 19 C4.9 19 4 18.1 4 17 Z';
      case 'task':
        return 'M8 4.5 L16 4.5 C17.93 4.5 19.5 6.07 19.5 8 L19.5 16 C19.5 17.93 17.93 19.5 16 19.5 L8 19.5 C6.07 19.5 4.5 17.93 4.5 16 L4.5 8 C4.5 6.07 6.07 4.5 8 4.5 Z M8.5 12 L11 14.5 L15.5 9.5';
      case 'moon':
        return 'M19.5 14 C18 17.5 14.5 19.5 11 19.5 C6.3 19.5 2.5 15.7 2.5 11 C2.5 7.5 4.6 4.5 7.6 3 C6.6 4.4 6 6.1 6 8 C6 12.4 9.6 16 14 16 C16 16 17.9 15.2 19.5 14 Z';
      case 'palette':
        return 'M12 3.5 C16.7 3.5 20.5 8 20.5 13 C20.5 14.93 18.93 16.5 17 16.5 L14.7 16.5 C13.2 16.5 12.9 17.5 13.4 18.5 C13.9 19.5 13.4 20.5 11.9 20.5 C7.4 20.5 3.5 16.5 3.5 12 C3.5 7.3 7.3 3.5 12 3.5 Z M8 10 C8.66 10 9.2 9.55 9.2 9 C9.2 8.45 8.66 8 8 8 C7.34 8 6.8 8.45 6.8 9 C6.8 9.55 7.34 10 8 10 Z M12 7.5 C12.66 7.5 13.2 7.05 13.2 6.5 C13.2 5.95 12.66 5.5 12 5.5 C11.34 5.5 10.8 5.95 10.8 6.5 C10.8 7.05 11.34 7.5 12 7.5 Z M16 10 C16.66 10 17.2 9.55 17.2 9 C17.2 8.45 16.66 8 16 8 C15.34 8 14.8 8.45 14.8 9 C14.8 9.55 15.34 10 16 10 Z';
      case 'logout':
        return 'M14 4.5 L7 4.5 C6.17 4.5 5.5 5.17 5.5 6 L5.5 18 C5.5 18.83 6.17 19.5 7 19.5 L14 19.5 M10.5 12 L20 12 M17 8.5 L20.5 12 L17 15.5';
      case 'info':
        return 'M12 3.5 C16.14 3.5 20.5 7.36 20.5 12 C20.5 16.64 16.14 20.5 12 20.5 C7.86 20.5 3.5 16.64 3.5 12 C3.5 7.36 7.86 3.5 12 3.5 Z M12 11 L12 16 M12 8 L12.01 8';
      case 'lock':
        return 'M8 10.5 L16 10.5 C17.1 10.5 18 11.4 18 12.5 L18 17 C18 18.1 17.1 19 16 19 L8 19 C6.9 19 6 18.1 6 17 L6 12.5 C6 11.4 6.9 10.5 8 10.5 Z M8.5 10.5 L8.5 8 C8.5 6.07 10.07 4.5 12 4.5 C13.93 4.5 15.5 6.07 15.5 8 L15.5 10.5';
      case 'mail':
        return 'M6.5 6 L17.5 6 C18.88 6 20 7.12 20 8.5 L20 15.5 C20 16.88 18.88 18 17.5 18 L6.5 18 C5.12 18 4 16.88 4 15.5 L4 8.5 C4 7.12 5.12 6 6.5 6 Z M5 8.5 L12 13.5 L19 8.5';
      case 'model':
        return 'M7.5 4.5 L16.5 4.5 C18.16 4.5 19.5 5.84 19.5 7.5 L19.5 16.5 C19.5 18.16 18.16 19.5 16.5 19.5 L7.5 19.5 C5.84 19.5 4.5 18.16 4.5 16.5 L4.5 7.5 C4.5 5.84 5.84 4.5 7.5 4.5 Z M9 4.5 L9 19.5 M4.5 12 L10.5 12 M13.9 12 C13.9 11.11 14.61 10.4 15.5 10.4 C16.39 10.4 17.1 11.11 17.1 12 C17.1 12.89 16.39 13.6 15.5 13.6 C14.61 13.6 13.9 12.89 13.9 12 Z';
      case 'history':
        return 'M4.5 12 C4.5 7.86 7.86 4.5 12 4.5 C16.14 4.5 19.5 7.86 19.5 12 C19.5 16.14 16.14 19.5 12 19.5 C9.5 19.5 7.3 18.2 6 16.2 M2.5 12 L4.5 12 M2.5 12 L3.8 14.2 M12 8 L12 12.5 L15 14.3';
      case 'signal':
        return 'M5 15.5 L5 18.5 M9.5 12.5 L9.5 18.5 M14 9.5 L14 18.5 M18.5 6.5 L18.5 18.5';
      case 'batt':
        return 'M5 10 C5 8.9 5.9 8 7 8 L17 8 C18.1 8 19 8.9 19 10 L19 14 C19 15.1 18.1 16 17 16 L7 16 C5.9 16 5 15.1 5 14 Z M21 10.5 L21 13.5 M7 10.5 L13 10.5 L13 13.5 L7 13.5 Z';
      case 'wifi':
        return 'M4 9.5 C8.6 5.5 15.4 5.5 20 9.5 M7 13 C9.9 10.5 14.1 10.5 17 13 M10 16.5 C11.1 15.5 12.9 15.5 14 16.5 M10.8 19 C10.8 18.45 11.35 18 12 18 C12.65 18 13.2 18.45 13.2 19 C13.2 19.55 12.65 20 12 20 C11.35 20 10.8 19.55 10.8 19 Z';
      case 'link':
        return 'M9.5 14.5 L14.5 9.5 M8 12 L5.5 14.5 C4 16 4 18.5 5.5 20 C7 21.5 9.5 21.5 11 20 L13 17.5 M16 12 L18.5 9.5 C20 8 20 5.5 18.5 4 C17 2.5 14.5 2.5 13 4 L11 6.5';
      case 'pause':
        return 'M9 6.5 L9 17.5 M15 6.5 L15 17.5';
      case 'globe':
        return 'M12 3.5 C16.14 3.5 20.5 7.36 20.5 12 C20.5 16.64 16.14 20.5 12 20.5 C7.86 20.5 3.5 16.64 3.5 12 C3.5 7.36 7.86 3.5 12 3.5 Z M3.5 12 L20.5 12 M12 3.5 C14.5 5.8 15.8 8.7 15.8 12 C15.8 15.3 14.5 18.2 12 20.5 C9.5 18.2 8.2 15.3 8.2 12 C8.2 8.7 9.5 5.8 12 3.5 Z';
      case 'eye':
        return 'M2.8 12 C2.8 12 6 5.8 12 5.8 C18 5.8 21.2 12 21.2 12 C21.2 12 18 18.2 12 18.2 C6 18.2 2.8 12 2.8 12 Z M9.4 12 C9.4 10.56 10.56 9.4 12 9.4 C13.44 9.4 14.6 10.56 14.6 12 C14.6 13.44 13.44 14.6 12 14.6 C10.56 14.6 9.4 13.44 9.4 12 Z';
      case 'graph':
        return 'M3.7 6 C3.7 4.73 4.73 3.7 6 3.7 C7.27 3.7 8.3 4.73 8.3 6 C8.3 7.27 7.27 8.3 6 8.3 C4.73 8.3 3.7 7.27 3.7 6 Z M15.7 8 C15.7 6.73 16.73 5.7 18 5.7 C19.27 5.7 20.3 6.73 20.3 8 C20.3 9.27 19.27 10.3 18 10.3 C16.73 10.3 15.7 9.27 15.7 8 Z M9.7 18 C9.7 16.73 10.73 15.7 12 15.7 C13.27 15.7 14.3 16.73 14.3 18 C14.3 19.27 13.27 20.3 12 20.3 C10.73 20.3 9.7 19.27 9.7 18 Z M8.3 6.8 L15.7 7.6 M7 8.1 L11 16 M16.9 10.1 L13 16';
      case 'sun':
        return 'M8 12 C8 9.79 9.79 8 12 8 C14.21 8 16 9.79 16 12 C16 14.21 14.21 16 12 16 C9.79 16 8 14.21 8 12 Z M12 3 L12 5 M12 19 L12 21 M3 12 L5 12 M19 12 L21 12 M5.6 5.6 L7 7 M17 17 L18.4 18.4 M18.4 5.6 L17 7 M7 17 L5.6 18.4';
      default:
        return 'M12 3.5 C16.14 3.5 20.5 7.36 20.5 12 C20.5 16.64 16.14 20.5 12 20.5 C7.86 20.5 3.5 16.64 3.5 12 C3.5 7.36 7.86 3.5 12 3.5 Z M12 11 L12 16 M12 8 L12.01 8';
    }
  }
}

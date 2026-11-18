/**
 * ToastHost - 全局消息提示挂载点
 *
 * 断点背景：MessageManager 所有 toast 调用经 EventBus 'message:show' 分发，
 * 但此前全仓无任何 UI 订阅——登录失败/配对成功等提示从未可见（toast 全盲）。
 * 本组件挂在 Index 根 Stack 顶层，订阅后渲染胶囊 toast，计时自动移除；
 * 容器 hitTestBehavior=None 不拦截下层交互。
 */

import { EventBus } from '../../libs/bus/EventBus';
import { MessageRecord, MessageType } from '../../libs/message/MessageManager';
import { StyleManager } from '../../libs/style/StyleManager';

@Component
export struct ToastHost {
  @State private toasts: MessageRecord[] = [];
  private bus: EventBus = EventBus.getInstance();
  private sm: StyleManager = StyleManager.getInstance();
  /** 稳定引用（aboutToDisappear 反订阅用） */
  private cb: (data: Object) => void = (data: Object) => {
    const rec = data as MessageRecord;
    if (!rec || !rec.id) {
      return;
    }
    // 同 id 去重
    if (this.toasts.findIndex((t: MessageRecord) => t.id === rec.id) >= 0) {
      return;
    }
    const next: MessageRecord[] = this.toasts.slice();
    next.push(rec);
    this.toasts = next;
    const duration = rec.duration > 0 ? rec.duration : 2000;
    setTimeout(() => {
      const remain: MessageRecord[] = this.toasts.filter((t: MessageRecord) => t.id !== rec.id);
      this.toasts = remain;
    }, duration);
  };

  aboutToAppear(): void {
    this.bus.on('message:show', this.cb);
  }

  aboutToDisappear(): void {
    this.bus.off('message:show', this.cb);
  }

  private dotColor(type: MessageType): string {
    if (type === MessageType.SUCCESS) {
      return this.sm.getColor('success');
    }
    if (type === MessageType.WARNING) {
      return this.sm.getColor('warning');
    }
    if (type === MessageType.ERROR) {
      return this.sm.getColor('error');
    }
    return this.sm.getColor('info');
  }

  build() {
    Column() {
      ForEach(this.toasts, (rec: MessageRecord) => {
        Row() {
          Circle()
            .width(7)
            .height(7)
            .fill(this.dotColor(rec.type))
          Text(rec.text)
            .fontSize(13)
            .fontColor(this.sm.getColor('text_primary'))
            .maxLines(2)
            .margin({ left: 8 })
        }
        .padding({ left: 14, right: 16, top: 10, bottom: 10 })
        .borderRadius(16)
        .backgroundColor(this.sm.getColor('surface'))
        .border({ width: 1, color: this.sm.getColor('border') })
        .margin({ bottom: 8 })
      }, (rec: MessageRecord) => rec.id)
    }
    .width('100%')
    .alignItems(HorizontalAlign.Center)
    .margin({ top: 110 })
    .hitTestBehavior(HitTestMode.None)
  }
}

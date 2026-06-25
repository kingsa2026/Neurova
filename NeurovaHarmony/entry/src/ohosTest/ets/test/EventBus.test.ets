// EventBus 单元测试 - TDD 垂直切片
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { EventBus } from '../../../../main/ets/libs/bus/EventBus';

export default function eventBusTest() {
  describe('EventBus', () => {
    let bus: EventBus;

    beforeEach(() => {
      bus = EventBus.getInstance();
      bus.clearAll();
    });

    // ========== Tracer Bullet: 单例 ==========

    it('getInstance_returns_singleton', 0, () => {
      expect(EventBus.getInstance()).assertEqual(EventBus.getInstance());
    });

    // ========== 行为 1: on + emit 基本订阅 ==========

    it('on_emit_invokes_handler_with_data', 0, () => {
      let received: Object | null = null;
      bus.on('test:event', (data) => { received = data; });
      bus.emit('test:event', { value: 42 });
      expect(received).assertEqual({ value: 42 });
    });

    it('on_multiple_handlers_all_invoked', 0, () => {
      let count = 0;
      bus.on('test:event', () => { count++; });
      bus.on('test:event', () => { count++; });
      bus.emit('test:event', null);
      expect(count).assertEqual(2);
    });

    // ========== 行为 2: off 取消订阅 ==========

    it('off_removes_specific_handler', 0, () => {
      let called = false;
      const handler = () => { called = true; };
      bus.on('test:event', handler);
      bus.off('test:event', handler);
      bus.emit('test:event', null);
      expect(called).assertFalse();
    });

    it('off_does_not_affect_other_handlers', 0, () => {
      let called1 = false;
      let called2 = false;
      const h1 = () => { called1 = true; };
      const h2 = () => { called2 = true; };
      bus.on('test:event', h1);
      bus.on('test:event', h2);
      bus.off('test:event', h1);
      bus.emit('test:event', null);
      expect(called1).assertFalse();
      expect(called2).assertTrue();
    });

    // ========== 行为 3: once 一次性订阅 ==========

    it('once_invokes_handler_only_once', 0, () => {
      let count = 0;
      bus.once('test:event', () => { count++; });
      bus.emit('test:event', null);
      bus.emit('test:event', null);
      expect(count).assertEqual(1);
    });

    // ========== 行为 4: emit 无订阅者时不报错 ==========

    it('emit_no_subscribers_does_not_throw', 0, () => {
      // 无订阅者时 emit 应安全返回
      bus.emit('unsubscribed:event', { data: 'test' });
      expect(true).assertTrue();
    });

    // ========== 行为 5: clear 清除指定事件的所有订阅 ==========

    it('clear_removes_all_handlers_for_event', 0, () => {
      let count = 0;
      bus.on('test:event', () => { count++; });
      bus.on('test:event', () => { count++; });
      bus.clear('test:event');
      bus.emit('test:event', null);
      expect(count).assertEqual(0);
    });

    // ========== 行为 6: clearAll 清除所有订阅 ==========

    it('clearAll_removes_all_handlers', 0, () => {
      let count = 0;
      bus.on('event:a', () => { count++; });
      bus.on('event:b', () => { count++; });
      bus.clearAll();
      bus.emit('event:a', null);
      bus.emit('event:b', null);
      expect(count).assertEqual(0);
    });

    // ========== 行为 7: handler 异常不影响其他 handler ==========

    it('handler_error_does_not_block_other_handlers', 0, () => {
      let called = false;
      bus.on('test:event', () => { throw new Error('handler error'); });
      bus.on('test:event', () => { called = true; });
      bus.emit('test:event', null);
      expect(called).assertTrue();
    });

    // ========== 行为 8: listenerCount 统计 ==========

    it('listenerCount_returns_number_of_handlers', 0, () => {
      bus.on('test:event', () => {});
      bus.on('test:event', () => {});
      expect(bus.listenerCount('test:event')).assertEqual(2);
    });

    it('listenerCount_returns_zero_for_unsubscribed_event', 0, () => {
      expect(bus.listenerCount('no:event')).assertEqual(0);
    });
  });
}

// StateManager 单元测试 - TDD 垂直切片
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { StateManager } from '../../../../main/ets/libs/state/StateManager';

export default function stateManagerTest() {
  describe('StateManager', () => {
    let sm: StateManager;

    beforeEach(() => {
      sm = StateManager.getInstance();
      sm.clearAll();
    });

    // ========== Tracer Bullet: 单例 ==========

    it('getInstance_returns_singleton', 0, () => {
      expect(StateManager.getInstance()).assertEqual(StateManager.getInstance());
    });

    // ========== 行为 1: get / set 基本存取 ==========

    it('set_then_get_returns_value', 0, () => {
      sm.set('count', 42);
      expect(sm.get<number>('count')).assertEqual(42);
    });

    it('get_unknown_key_returns_undefined', 0, () => {
      expect(sm.get('nope')).assertUndefined();
    });

    it('get_with_default_returns_default_when_missing', 0, () => {
      expect(sm.get<number>('missing', 99)).assertEqual(99);
    });

    it('set_overrides_existing_value', 0, () => {
      sm.set('name', 'a');
      sm.set('name', 'b');
      expect(sm.get<string>('name')).assertEqual('b');
    });

    // ========== 行为 2: subscribe 订阅 ==========

    it('subscribe_invokes_callback_on_set', 0, () => {
      let received: Object | null = null;
      sm.subscribe('count', (v) => { received = v; });
      sm.set('count', 7);
      expect(received).assertEqual(7);
    });

    it('subscribe_unsubscribe_via_returned_fn', 0, () => {
      let called = false;
      const unsub = sm.subscribe('count', () => { called = true; });
      unsub();
      sm.set('count', 1);
      expect(called).assertFalse();
    });

    it('multiple_subscribers_all_invoked', 0, () => {
      let count = 0;
      sm.subscribe('x', () => { count++; });
      sm.subscribe('x', () => { count++; });
      sm.set('x', 1);
      expect(count).assertEqual(2);
    });

    // ========== 行为 3: has / remove ==========

    it('has_returns_true_for_existing_key', 0, () => {
      sm.set('flag', true);
      expect(sm.has('flag')).assertTrue();
    });

    it('has_returns_false_for_missing_key', 0, () => {
      expect(sm.has('nope')).assertFalse();
    });

    it('remove_deletes_key', 0, () => {
      sm.set('temp', 'x');
      sm.remove('temp');
      expect(sm.has('temp')).assertFalse();
    });

    it('remove_does_not_notify_subscribers', 0, () => {
      let called = false;
      sm.subscribe('temp', () => { called = true; });
      sm.set('temp', 'a');   // 触发一次
      called = false;
      sm.remove('temp');
      expect(called).assertFalse();
    });

    // ========== 行为 4: clearAll ==========

    it('clearAll_removes_all_keys', 0, () => {
      sm.set('a', 1);
      sm.set('b', 2);
      sm.clearAll();
      expect(sm.has('a')).assertFalse();
      expect(sm.has('b')).assertFalse();
    });

    it('clearAll_clears_subscribers', 0, () => {
      let called = false;
      sm.subscribe('a', () => { called = true; });
      sm.clearAll();
      sm.set('a', 1);
      expect(called).assertFalse();
    });

    // ========== 行为 5: keys 列举 ==========

    it('keys_returns_all_keys', 0, () => {
      sm.set('a', 1);
      sm.set('b', 2);
      const keys = sm.keys();
      expect(keys.length).assertEqual(2);
      expect(keys.indexOf('a') >= 0).assertTrue();
      expect(keys.indexOf('b') >= 0).assertTrue();
    });
  });
}

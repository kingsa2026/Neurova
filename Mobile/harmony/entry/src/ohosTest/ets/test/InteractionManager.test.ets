// InteractionManager 单元测试 - TDD 垂直切片
// 通过公共接口验证交互行为：防抖、节流、长按判定、滑动方向判定
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { InteractionManager } from '../../../../main/ets/libs/interaction/InteractionManager';

export default function interactionManagerTest() {
  describe('InteractionManager', () => {
    let im: InteractionManager;

    beforeEach(() => {
      im = InteractionManager.getInstance();
      // 每个测试前重置长按阈值为默认值，保证测试隔离
      im.setLongPressThreshold(500);
    });

    // ========== Tracer Bullet: 单例 ==========

    it('getInstance_returns_singleton', 0, () => {
      expect(InteractionManager.getInstance()).assertEqual(InteractionManager.getInstance());
    });

    // ========== 行为 1: isLongPress 长按判定（默认阈值 500ms）==========

    it('isLongPress_600_returns_true_when_threshold_500', 0, () => {
      expect(im.isLongPress(600)).assertTrue();
    });

    it('isLongPress_400_returns_false_when_threshold_500', 0, () => {
      expect(im.isLongPress(400)).assertFalse();
    });

    // ========== 行为 2: setLongPressThreshold 配置阈值 ==========

    it('setLongPressThreshold_1000_then_isLongPress_800_false', 0, () => {
      im.setLongPressThreshold(1000);
      expect(im.isLongPress(800)).assertFalse();
    });

    it('setLongPressThreshold_1000_then_isLongPress_1200_true', 0, () => {
      im.setLongPressThreshold(1000);
      expect(im.isLongPress(1200)).assertTrue();
    });

    // ========== 行为 3: getLongPressThreshold 默认值 ==========

    it('getLongPressThreshold_default_returns_500', 0, () => {
      expect(im.getLongPressThreshold()).assertEqual(500);
    });

    // ========== 行为 4: detectSwipe 滑动方向判定 ==========

    it('detectSwipe_negative_dx_returns_left', 0, () => {
      expect(im.detectSwipe(-100, 0)).assertEqual('left');
    });

    it('detectSwipe_positive_dx_returns_right', 0, () => {
      expect(im.detectSwipe(100, 0)).assertEqual('right');
    });

    it('detectSwipe_negative_dy_returns_up', 0, () => {
      expect(im.detectSwipe(0, -100)).assertEqual('up');
    });

    it('detectSwipe_positive_dy_returns_down', 0, () => {
      expect(im.detectSwipe(0, 100)).assertEqual('down');
    });

    it('detectSwipe_small_distance_returns_null', 0, () => {
      // 位移均小于阈值 30，应返回 null
      expect(im.detectSwipe(5, 5)).assertEqual(null);
    });

    // ========== 行为 5: debounce 防抖（多次快速调用只执行最后一次）==========

    it('debounce_only_last_call_executed', 0, () => {
      let callCount = 0;
      let lastArg = '';
      const debounced = im.debounce((msg: string) => {
        callCount++;
        lastArg = msg;
      }, 50);

      // 连续三次快速调用
      debounced('first');
      debounced('second');
      debounced('third');

      // 等待防抖窗口结束（wait + 缓冲）
      setTimeout(() => {
        expect(callCount).assertEqual(1);
        expect(lastArg).assertEqual('third');
      }, 80);
    });

    // ========== 行为 6: throttle 节流（多次快速调用只执行第一次）==========

    it('throttle_only_first_call_executed', 0, () => {
      let callCount = 0;
      let firstArg = '';
      const throttled = im.throttle((msg: string) => {
        callCount++;
        if (callCount === 1) {
          firstArg = msg;
        }
      }, 50);

      // 连续三次快速调用
      throttled('first');
      throttled('second');
      throttled('third');

      // 节流：同步立即执行第一次，后续在窗口内被跳过
      expect(callCount).assertEqual(1);
      expect(firstArg).assertEqual('first');

      // 等待窗口结束后验证仍为 1（窗口内未再触发）
      setTimeout(() => {
        expect(callCount).assertEqual(1);
      }, 80);
    });
  });
}

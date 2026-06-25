// AnimationManager 单元测试 - TDD 垂直切片
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { AnimationManager, AnimationDuration, EasingType, AnimationPreset } from '../../../../main/ets/libs/animation/AnimationManager';
import { registerBuiltInPresets } from '../../../../main/ets/libs/animation/presets';

export default function animationManagerTest() {
  describe('AnimationManager', () => {
    let am: AnimationManager;

    beforeEach(() => {
      am = AnimationManager.getInstance();
      // 注意：预设注册到单例，测试间不重置（符合单例语义）
    });

    // ========== Tracer Bullet: 单例 ==========

    it('getInstance_returns_singleton', 0, () => {
      expect(AnimationManager.getInstance()).assertEqual(AnimationManager.getInstance());
    });

    // ========== 行为 1: getDuration 动画时长 ==========

    it('getDuration_FAST_returns_150', 0, () => {
      expect(am.getDuration(AnimationDuration.FAST)).assertEqual(150);
    });

    it('getDuration_NORMAL_returns_300', 0, () => {
      expect(am.getDuration(AnimationDuration.NORMAL)).assertEqual(300);
    });

    it('getDuration_SLOW_returns_500', 0, () => {
      expect(am.getDuration(AnimationDuration.SLOW)).assertEqual(500);
    });

    // ========== 行为 2: getEasingCurve 缓动曲线 ==========

    it('getEasingCurve_EASE_IN_returns_non_empty_string', 0, () => {
      const curve = am.getEasingCurve(EasingType.EASE_IN);
      expect(curve).assertNotEqual('');
      expect(curve.length > 0).assertTrue();
    });

    // ========== 行为 3: registerPreset + getPreset 预设注册与查询 ==========

    it('registerPreset_then_getPreset_returns_it', 0, () => {
      const preset: AnimationPreset = {
        name: 'test-custom',
        duration: 250,
        easing: EasingType.EASE_IN,
        from: { opacity: 0 },
        to: { opacity: 1 },
      };
      am.registerPreset(preset);
      const got = am.getPreset('test-custom');
      expect(got).assertNotEqual(undefined);
      expect(got!.name).assertEqual('test-custom');
      expect(got!.duration).assertEqual(250);
    });

    it('getPreset_unknown_name_returns_undefined', 0, () => {
      const got = am.getPreset('non-existent-preset-name');
      expect(got).assertEqual(undefined);
    });

    // ========== 行为 4: listPresets 列出所有预设名 ==========

    it('listPresets_returns_all_registered_names', 0, () => {
      am.registerPreset({
        name: 'list-test-a', duration: 100, easing: EasingType.EASE_IN,
        from: {}, to: {},
      });
      am.registerPreset({
        name: 'list-test-b', duration: 200, easing: EasingType.EASE_IN,
        from: {}, to: {},
      });
      const names = am.listPresets();
      expect(names.indexOf('list-test-a') >= 0).assertTrue();
      expect(names.indexOf('list-test-b') >= 0).assertTrue();
    });

    // ========== 行为 5: presets.ets 内置预设注册 ==========

    it('presets_registers_fade_in', 0, () => {
      registerBuiltInPresets();
      const got = am.getPreset('fade-in');
      expect(got).assertNotEqual(undefined);
      expect(got!.name).assertEqual('fade-in');
      expect(got!.duration).assertEqual(300);
    });

    it('presets_registers_glass_blur', 0, () => {
      registerBuiltInPresets();
      const got = am.getPreset('glass-blur');
      expect(got).assertNotEqual(undefined);
      expect(got!.name).assertEqual('glass-blur');
      expect(got!.duration).assertEqual(500);
    });
  });
}

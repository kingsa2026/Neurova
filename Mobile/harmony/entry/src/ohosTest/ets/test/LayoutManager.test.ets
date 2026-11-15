// LayoutManager 单元测试 - TDD 垂直切片
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { LayoutManager, Breakpoint } from '../../../../main/ets/libs/layout/LayoutManager';

export default function layoutManagerTest() {
  describe('LayoutManager', () => {
    let lm: LayoutManager;

    beforeEach(() => {
      lm = LayoutManager.getInstance();
    });

    // ========== Tracer Bullet: 单例 ==========

    it('getInstance_returns_singleton', 0, () => {
      expect(LayoutManager.getInstance()).assertEqual(LayoutManager.getInstance());
    });

    // ========== 行为 1: 响应式断点 ==========

    it('getBreakpoint_300_returns_SM', 0, () => {
      expect(lm.getBreakpoint(300)).assertEqual(Breakpoint.SM);
    });

    it('getBreakpoint_700_returns_MD', 0, () => {
      expect(lm.getBreakpoint(700)).assertEqual(Breakpoint.MD);
    });

    it('getBreakpoint_1000_returns_LG', 0, () => {
      expect(lm.getBreakpoint(1000)).assertEqual(Breakpoint.LG);
    });

    // ========== 行为 2: 设备类型判定 ==========

    it('isMobile_500_returns_true', 0, () => {
      expect(lm.isMobile(500)).assertTrue();
    });

    it('isMobile_700_returns_false', 0, () => {
      expect(lm.isMobile(700)).assertFalse();
    });

    it('isTablet_700_returns_true', 0, () => {
      expect(lm.isTablet(700)).assertTrue();
    });

    it('isTablet_300_returns_false', 0, () => {
      expect(lm.isTablet(300)).assertFalse();
    });

    it('isDesktop_1000_returns_true', 0, () => {
      expect(lm.isDesktop(1000)).assertTrue();
    });

    it('isDesktop_700_returns_false', 0, () => {
      expect(lm.isDesktop(700)).assertFalse();
    });

    // ========== 行为 3: 间距辅助 ==========

    it('padding_md_returns_all_16', 0, () => {
      const p = lm.padding('md');
      expect(p.top).assertEqual(16);
      expect(p.right).assertEqual(16);
      expect(p.bottom).assertEqual(16);
      expect(p.left).assertEqual(16);
    });

    it('paddingH_md_returns_horizontal_only', 0, () => {
      const p = lm.paddingH('md');
      expect(p.top).assertEqual(0);
      expect(p.right).assertEqual(16);
      expect(p.bottom).assertEqual(0);
      expect(p.left).assertEqual(16);
    });

    it('paddingV_md_returns_vertical_only', 0, () => {
      const p = lm.paddingV('md');
      expect(p.top).assertEqual(16);
      expect(p.right).assertEqual(0);
      expect(p.bottom).assertEqual(16);
      expect(p.left).assertEqual(0);
    });

    // ========== 行为 4: 安全区内边距 ==========

    it('setSafeAreaInsets_then_get_returns_same', 0, () => {
      const insets = { top: 44, bottom: 34, left: 0, right: 0 };
      lm.setSafeAreaInsets(insets);
      const got = lm.getSafeAreaInsets();
      expect(got.top).assertEqual(44);
      expect(got.bottom).assertEqual(34);
      expect(got.left).assertEqual(0);
      expect(got.right).assertEqual(0);
    });
  });
}

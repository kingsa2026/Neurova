// StyleManager 单元测试 - TDD 垂直切片
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { StyleManager, ThemeMode } from '../../../../main/ets/libs/style/StyleManager';

export default function styleManagerTest() {
  describe('StyleManager', () => {
    let sm: StyleManager;

    beforeEach(() => {
      sm = StyleManager.getInstance();
      sm.setThemeMode(ThemeMode.LIGHT);
      sm.resetToDefaults();
    });

    // ========== Tracer Bullet: 单例 ==========

    it('getInstance_returns_singleton', 0, () => {
      expect(StyleManager.getInstance()).assertEqual(StyleManager.getInstance());
    });

    // ========== 行为 1: 颜色 token ==========

    it('getColor_returns_default_primary', 0, () => {
      const primary = sm.getColor('primary');
      expect(primary).assertEqual('#1890ff');
    });

    it('getColor_returns_default_error', 0, () => {
      const error = sm.getColor('error');
      expect(error).assertEqual('#ff4d4f');
    });

    it('getColor_returns_default_for_unknown', 0, () => {
      const c = sm.getColor('unknown_color');
      expect(c).assertEqual('#000000');
    });

    // ========== 行为 2: 间距 token ==========

    it('getSpacing_returns_default_xs', 0, () => {
      expect(sm.getSpacing('xs')).assertEqual(4);
    });

    it('getSpacing_returns_default_md', 0, () => {
      expect(sm.getSpacing('md')).assertEqual(16);
    });

    it('getSpacing_returns_default_for_unknown', 0, () => {
      expect(sm.getSpacing('unknown')).assertEqual(0);
    });

    // ========== 行为 3: 字号 token ==========

    it('getFontSize_returns_default_body', 0, () => {
      expect(sm.getFontSize('body')).assertEqual(16);
    });

    it('getFontSize_returns_default_title', 0, () => {
      expect(sm.getFontSize('title')).assertEqual(20);
    });

    // ========== 行为 4: 圆角 token ==========

    it('getRadius_returns_default_sm', 0, () => {
      expect(sm.getRadius('sm')).assertEqual(4);
    });

    it('getRadius_returns_default_lg', 0, () => {
      expect(sm.getRadius('lg')).assertEqual(12);
    });

    // ========== 行为 5: 主题切换 ==========

    it('setThemeMode_dark_changes_primary_color', 0, () => {
      sm.setThemeMode(ThemeMode.DARK);
      const primary = sm.getColor('primary');
      // 暗色主题 primary 应与亮色不同
      expect(primary).assertEqual('#177ddc');
    });

    it('getThemeMode_returns_current_mode', 0, () => {
      sm.setThemeMode(ThemeMode.DARK);
      expect(sm.getThemeMode()).assertEqual(ThemeMode.DARK);
    });

    // ========== 行为 6: 自定义 token 注册 ==========

    it('setColor_overrides_existing', 0, () => {
      sm.setColor('primary', '#ff0000');
      expect(sm.getColor('primary')).assertEqual('#ff0000');
    });

    it('setSpacing_adds_new_token', 0, () => {
      sm.setSpacing('xxl', 48);
      expect(sm.getSpacing('xxl')).assertEqual(48);
    });

    // ========== 行为 7: resetToDefaults 恢复默认 ==========

    it('resetToDefaults_restores_primary_color', 0, () => {
      sm.setColor('primary', '#ff0000');
      sm.resetToDefaults();
      expect(sm.getColor('primary')).assertEqual('#1890ff');
    });
  });
}

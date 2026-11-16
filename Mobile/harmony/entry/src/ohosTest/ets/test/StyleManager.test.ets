// StyleManager 单元测试 - TDD 垂直切片
// 色值断言对齐现行 cosmic 星穹玻璃 token 表（旧断言值来自更早的配色稿，
// 对现行表运行期必红——R2 对齐）；status_* 三 token 的存在性与派生关系
// 在此钉死（审计 3.8-2）。
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { StyleManager, ThemeMode } from '../../../main/ets/libs/style/StyleManager';

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

    // ========== 行为 1: 颜色 token（现行表值） ==========

    it('getColor_returns_default_primary', 0, () => {
      const primary = sm.getColor('primary');
      expect(primary).assertEqual('#4d6bfe');
    });

    it('getColor_returns_default_error', 0, () => {
      const error = sm.getColor('error');
      expect(error).assertEqual('#dc2626');
    });

    it('getColor_returns_default_for_unknown', 0, () => {
      const c = sm.getColor('unknown_color');
      expect(c).assertEqual('#000000');
    });

    // ========== 行为 1b: status_* 三 token 存在且与基 token 同值（3.8-2） ==========

    it('status_tokens_resolve_to_real_colors_not_fallback', 0, () => {
      // 修复前：三 token 不在表内，getColor 全部回退 '#000000'
      expect(sm.getColor('status_success')).assertEqual(sm.getColor('success'));
      expect(sm.getColor('status_error')).assertEqual(sm.getColor('error'));
      expect(sm.getColor('status_warning')).assertEqual(sm.getColor('warning'));
    });

    it('status_tokens_follow_theme_switch', 0, () => {
      sm.setThemeMode(ThemeMode.DARK);
      sm.resetToDefaults();
      expect(sm.getColor('status_success')).assertEqual('#34d399');
      expect(sm.getColor('status_error')).assertEqual('#f87171');
      expect(sm.getColor('status_warning')).assertEqual('#fbbf24');
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
      expect(primary).assertEqual('#6366f1');
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
      expect(sm.getColor('primary')).assertEqual('#4d6bfe');
    });
  });
}

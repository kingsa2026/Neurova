// SkillPoolPage 技能池页单元测试 - R6 契约切换
//
// 测试范围：SkillPoolViewHelper 视图模型行为（启用态颜色/图标/文案、操作按钮
//           文案、使用次数格式化、成功率格式化、描述截断）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 SkillPoolPage.ets 导出的 SkillPoolViewHelper 静态方法进行验证。
// 契约：R6 起页面消费后端 SkillInfo 契约（enabled 布尔，无 draft/published/deprecated
//       三态与 installs/rating 字段），helper 随契约切换。
import { describe, it, expect } from '@ohos/hypium';
import { SkillPoolViewHelper } from '../../../main/ets/pages/SkillPoolPage';

export default function skillPoolPageTest() {
  describe('SkillPoolPage', () => {
    // ========== 切片1: getStatusColor - enabled → success ==========

    it('status_color_enabled_returns_success', 0, () => {
      expect(SkillPoolViewHelper.getStatusColor(true)).assertEqual('success');
    });

    // ========== 切片2: getStatusColor - disabled → text_disabled ==========

    it('status_color_disabled_returns_text_disabled', 0, () => {
      expect(SkillPoolViewHelper.getStatusColor(false)).assertEqual('text_disabled');
    });

    // ========== 切片3: getStatusIcon ==========

    it('status_icon_enabled_returns_check', 0, () => {
      expect(SkillPoolViewHelper.getStatusIcon(true)).assertEqual('✅');
    });

    it('status_icon_disabled_returns_blocked', 0, () => {
      expect(SkillPoolViewHelper.getStatusIcon(false)).assertEqual('🚫');
    });

    // ========== 切片4: getStatusLabel ==========

    it('status_label_enabled', 0, () => {
      expect(SkillPoolViewHelper.getStatusLabel(true)).assertEqual('已启用');
    });

    it('status_label_disabled', 0, () => {
      expect(SkillPoolViewHelper.getStatusLabel(false)).assertEqual('已禁用');
    });

    // ========== 切片5: getToggleActionLabel - 对当前状态取反的动作文案 ==========

    it('toggle_action_label_enabled_shows_disable', 0, () => {
      expect(SkillPoolViewHelper.getToggleActionLabel(true)).assertEqual('禁用');
    });

    it('toggle_action_label_disabled_shows_enable', 0, () => {
      expect(SkillPoolViewHelper.getToggleActionLabel(false)).assertEqual('启用');
    });

    // ========== 切片6: formatUsageCount ==========

    it('format_usage_zero_returns_unused', 0, () => {
      expect(SkillPoolViewHelper.formatUsageCount(0)).assertEqual('未使用');
    });

    it('format_usage_thousands_returns_K', 0, () => {
      expect(SkillPoolViewHelper.formatUsageCount(1024)).assertEqual('1.0K 次');
    });

    it('format_usage_millions_returns_M', 0, () => {
      expect(SkillPoolViewHelper.formatUsageCount(1048576)).assertEqual('1.0M 次');
    });

    it('format_usage_small_returns_raw', 0, () => {
      expect(SkillPoolViewHelper.formatUsageCount(7)).assertEqual('7 次');
    });

    // ========== 切片7: formatSuccessRate ==========

    it('format_rate_zero_returns_no_stats', 0, () => {
      expect(SkillPoolViewHelper.formatSuccessRate(0)).assertEqual('无统计');
    });

    it('format_rate_half_returns_percent', 0, () => {
      expect(SkillPoolViewHelper.formatSuccessRate(0.5)).assertEqual('成功率 50%');
    });

    it('format_rate_full_returns_percent', 0, () => {
      expect(SkillPoolViewHelper.formatSuccessRate(1.0)).assertEqual('成功率 100%');
    });

    // ========== 切片8: truncateDescription ==========

    it('truncate_short_desc_returns_raw', 0, () => {
      expect(SkillPoolViewHelper.truncateDescription('短描述', 80)).assertEqual('短描述');
    });

    it('truncate_long_desc_appends_ellipsis', 0, () => {
      const longDesc = 'a'.repeat(90);
      expect(SkillPoolViewHelper.truncateDescription(longDesc, 80)).assertEqual('a'.repeat(80) + '...');
    });
  });
}

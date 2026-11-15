// CollaborationTemplatePage 协作模板页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：CollaborationTemplateViewHelper 视图模型行为（分类颜色/图标/文案、
//           步骤数格式化、使用次数格式化、描述截断）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 CollaborationTemplatePage.ets 导出的
//       CollaborationTemplateViewHelper 静态方法进行验证。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { CollaborationTemplateViewHelper } from '../../../../main/ets/pages/CollaborationTemplatePage';

export default function collaborationTemplatePageTest() {
  describe('CollaborationTemplatePage', () => {
    // ========== 切片1: getCategoryColor - project → primary ==========

    it('category_color_project_returns_primary', 0, () => {
      expect(CollaborationTemplateViewHelper.getCategoryColor('project')).assertEqual('primary');
    });

    // ========== 切片2: getCategoryColor - team → info ==========

    it('category_color_team_returns_info', 0, () => {
      expect(CollaborationTemplateViewHelper.getCategoryColor('team')).assertEqual('info');
    });

    // ========== 切片3: getCategoryColor - workflow → success ==========

    it('category_color_workflow_returns_success', 0, () => {
      expect(CollaborationTemplateViewHelper.getCategoryColor('workflow')).assertEqual('success');
    });

    // ========== 切片4: getCategoryIcon - project → 📋 ==========

    it('category_icon_project_returns_clipboard', 0, () => {
      expect(CollaborationTemplateViewHelper.getCategoryIcon('project')).assertEqual('📋');
    });

    // ========== 切片5: getCategoryIcon - team → 👥 ==========

    it('category_icon_team_returns_group', 0, () => {
      expect(CollaborationTemplateViewHelper.getCategoryIcon('team')).assertEqual('👥');
    });

    // ========== 切片6: getCategoryIcon - workflow → 🔄 ==========

    it('category_icon_workflow_returns_workflow', 0, () => {
      expect(CollaborationTemplateViewHelper.getCategoryIcon('workflow')).assertEqual('🔄');
    });

    // ========== 切片7: getCategoryLabel - project → 项目 ==========

    it('category_label_project_returns_project', 0, () => {
      expect(CollaborationTemplateViewHelper.getCategoryLabel('project')).assertEqual('项目');
    });

    // ========== 切片8: getCategoryLabel - team → 团队 ==========

    it('category_label_team_returns_team', 0, () => {
      expect(CollaborationTemplateViewHelper.getCategoryLabel('team')).assertEqual('团队');
    });

    // ========== 切片9: getCategoryLabel - workflow → 工作流 ==========

    it('category_label_workflow_returns_workflow', 0, () => {
      expect(CollaborationTemplateViewHelper.getCategoryLabel('workflow')).assertEqual('工作流');
    });

    // ========== 切片10: formatStepsCount - 空数组 → "0 步" ==========

    it('format_steps_count_empty_returns_zero', 0, () => {
      expect(CollaborationTemplateViewHelper.formatStepsCount([])).assertEqual('0 步');
    });

    // ========== 切片11: formatStepsCount - 3 步 → "3 步" ==========

    it('format_steps_count_three_returns_three', 0, () => {
      const steps = [
        { name: '步骤1' },
        { name: '步骤2' },
        { name: '步骤3' },
      ];
      expect(CollaborationTemplateViewHelper.formatStepsCount(steps)).assertEqual('3 步');
    });

    // ========== 切片12: formatUsageCount - 0 → "未使用" ==========

    it('format_usage_count_zero_returns_unused', 0, () => {
      expect(CollaborationTemplateViewHelper.formatUsageCount(0)).assertEqual('未使用');
    });

    // ========== 切片13: formatUsageCount - 50 → "50 次" ==========

    it('format_usage_count_normal_returns_count', 0, () => {
      expect(CollaborationTemplateViewHelper.formatUsageCount(50)).assertEqual('50 次');
    });

    // ========== 切片14: formatUsageCount - 1000 → "999+ 次" ==========

    it('format_usage_count_thousands_returns_999plus', 0, () => {
      expect(CollaborationTemplateViewHelper.formatUsageCount(1000)).assertEqual('999+ 次');
    });

    // ========== 切片15: truncateDescription - 未超长 → 原样返回 ==========

    it('truncate_description_short_returns_original', 0, () => {
      expect(CollaborationTemplateViewHelper.truncateDescription('短描述', 10)).assertEqual('短描述');
    });

    // ========== 切片16: truncateDescription - 超长 → 截断 + "..." ==========

    it('truncate_description_long_returns_truncated', 0, () => {
      const desc = '这是一个非常长的协作模板描述文本，用于测试截断功能是否正常工作';
      const result = CollaborationTemplateViewHelper.truncateDescription(desc, 10);
      expect(result).assertEqual('这是一个非常长的协作...');
    });
  });
}

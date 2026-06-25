// CollaborationInitiatePage 协作发起页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：CollaborationInitiateViewHelper 视图模型行为（类型颜色/图标/文案、
//           状态颜色、参与者数量格式化）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 CollaborationInitiatePage.ets 导出的
//       CollaborationInitiateViewHelper 静态方法进行验证。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { CollaborationInitiateViewHelper } from '../../../../main/ets/pages/CollaborationInitiatePage';

export default function collaborationInitiatePageTest() {
  describe('CollaborationInitiatePage', () => {
    // ========== 切片1: getTypeColor - project → primary ==========

    it('type_color_project_returns_primary', 0, () => {
      expect(CollaborationInitiateViewHelper.getTypeColor('project')).assertEqual('primary');
    });

    // ========== 切片2: getTypeColor - team → info ==========

    it('type_color_team_returns_info', 0, () => {
      expect(CollaborationInitiateViewHelper.getTypeColor('team')).assertEqual('info');
    });

    // ========== 切片3: getTypeColor - task → success ==========

    it('type_color_task_returns_success', 0, () => {
      expect(CollaborationInitiateViewHelper.getTypeColor('task')).assertEqual('success');
    });

    // ========== 切片4: getTypeColor - workflow → warning ==========

    it('type_color_workflow_returns_warning', 0, () => {
      expect(CollaborationInitiateViewHelper.getTypeColor('workflow')).assertEqual('warning');
    });

    // ========== 切片5: getTypeIcon - project → 📋 ==========

    it('type_icon_project_returns_clipboard', 0, () => {
      expect(CollaborationInitiateViewHelper.getTypeIcon('project')).assertEqual('📋');
    });

    // ========== 切片6: getTypeIcon - team → 👥 ==========

    it('type_icon_team_returns_group', 0, () => {
      expect(CollaborationInitiateViewHelper.getTypeIcon('team')).assertEqual('👥');
    });

    // ========== 切片7: getTypeIcon - task → ✅ ==========

    it('type_icon_task_returns_check', 0, () => {
      expect(CollaborationInitiateViewHelper.getTypeIcon('task')).assertEqual('✅');
    });

    // ========== 切片8: getTypeIcon - workflow → 🔄 ==========

    it('type_icon_workflow_returns_workflow', 0, () => {
      expect(CollaborationInitiateViewHelper.getTypeIcon('workflow')).assertEqual('🔄');
    });

    // ========== 切片9: getTypeLabel - project → 项目 ==========

    it('type_label_project_returns_project', 0, () => {
      expect(CollaborationInitiateViewHelper.getTypeLabel('project')).assertEqual('项目');
    });

    // ========== 切片10: getTypeLabel - team → 团队 ==========

    it('type_label_team_returns_team', 0, () => {
      expect(CollaborationInitiateViewHelper.getTypeLabel('team')).assertEqual('团队');
    });

    // ========== 切片11: getTypeLabel - task → 任务 ==========

    it('type_label_task_returns_task', 0, () => {
      expect(CollaborationInitiateViewHelper.getTypeLabel('task')).assertEqual('任务');
    });

    // ========== 切片12: getTypeLabel - workflow → 工作流 ==========

    it('type_label_workflow_returns_workflow', 0, () => {
      expect(CollaborationInitiateViewHelper.getTypeLabel('workflow')).assertEqual('工作流');
    });

    // ========== 切片13: getStatusColor - pending → warning ==========

    it('status_color_pending_returns_warning', 0, () => {
      expect(CollaborationInitiateViewHelper.getStatusColor('pending')).assertEqual('warning');
    });

    // ========== 切片14: getStatusColor - initiated → success ==========

    it('status_color_initiated_returns_success', 0, () => {
      expect(CollaborationInitiateViewHelper.getStatusColor('initiated')).assertEqual('success');
    });

    // ========== 切片15: getStatusColor - failed → error ==========

    it('status_color_failed_returns_error', 0, () => {
      expect(CollaborationInitiateViewHelper.getStatusColor('failed')).assertEqual('error');
    });

    // ========== 切片16: formatParticipantsCount - 0 → "无参与者" ==========

    it('format_participants_count_zero_returns_none', 0, () => {
      expect(CollaborationInitiateViewHelper.formatParticipantsCount(0)).assertEqual('无参与者');
    });

    // ========== 切片17: formatParticipantsCount - 1 → "1 人" ==========

    it('format_participants_count_one_returns_one_person', 0, () => {
      expect(CollaborationInitiateViewHelper.formatParticipantsCount(1)).assertEqual('1 人');
    });

    // ========== 切片18: formatParticipantsCount - 5 → "5 人" ==========

    it('format_participants_count_multi_returns_multi_persons', 0, () => {
      expect(CollaborationInitiateViewHelper.formatParticipantsCount(5)).assertEqual('5 人');
    });
  });
}

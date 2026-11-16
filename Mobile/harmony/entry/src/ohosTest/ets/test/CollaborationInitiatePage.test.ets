// CollaborationInitiatePage 协作发起页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：CollaborationInitiateViewHelper 视图模型行为（会话状态颜色/文案、
//           发起状态颜色、参与者数量格式化）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 CollaborationInitiatePage.ets 导出的
//       CollaborationInitiateViewHelper 静态方法进行验证。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { CollaborationInitiateViewHelper } from '../../../main/ets/pages/CollaborationInitiatePage';

export default function collaborationInitiatePageTest() {
  describe('CollaborationInitiatePage', () => {
    // ========== 切片1: getSessionStatusColor - active → success ==========

    it('session_status_color_active_returns_success', 0, () => {
      expect(CollaborationInitiateViewHelper.getSessionStatusColor('active')).assertEqual('success');
    });

    // ========== 切片2: getSessionStatusColor - archived → warning ==========

    it('session_status_color_archived_returns_warning', 0, () => {
      expect(CollaborationInitiateViewHelper.getSessionStatusColor('archived')).assertEqual('warning');
    });

    // ========== 切片3: getSessionStatusColor - suspended → error ==========

    it('session_status_color_suspended_returns_error', 0, () => {
      expect(CollaborationInitiateViewHelper.getSessionStatusColor('suspended')).assertEqual('error');
    });

    // ========== 切片4: getSessionStatusColor - 未知状态 → info 兜底 ==========

    it('session_status_color_unknown_returns_info', 0, () => {
      expect(CollaborationInitiateViewHelper.getSessionStatusColor('other')).assertEqual('info');
    });

    // ========== 切片5: getSessionStatusLabel - active → 进行中 ==========

    it('session_status_label_active_returns_in_progress', 0, () => {
      expect(CollaborationInitiateViewHelper.getSessionStatusLabel('active')).assertEqual('进行中');
    });

    // ========== 切片6: getSessionStatusLabel - archived → 已归档 ==========

    it('session_status_label_archived_returns_archived', 0, () => {
      expect(CollaborationInitiateViewHelper.getSessionStatusLabel('archived')).assertEqual('已归档');
    });

    // ========== 切片7: getSessionStatusLabel - suspended → 已暂停 ==========

    it('session_status_label_suspended_returns_suspended', 0, () => {
      expect(CollaborationInitiateViewHelper.getSessionStatusLabel('suspended')).assertEqual('已暂停');
    });

    // ========== 切片8: getSessionStatusLabel - 未知状态 → 未知 ==========

    it('session_status_label_unknown_returns_unknown', 0, () => {
      expect(CollaborationInitiateViewHelper.getSessionStatusLabel('other')).assertEqual('未知');
    });

    // ========== 切片9: getStatusColor - pending → warning ==========

    it('status_color_pending_returns_warning', 0, () => {
      expect(CollaborationInitiateViewHelper.getStatusColor('pending')).assertEqual('warning');
    });

    // ========== 切片10: getStatusColor - initiated → success ==========

    it('status_color_initiated_returns_success', 0, () => {
      expect(CollaborationInitiateViewHelper.getStatusColor('initiated')).assertEqual('success');
    });

    // ========== 切片11: getStatusColor - failed → error ==========

    it('status_color_failed_returns_error', 0, () => {
      expect(CollaborationInitiateViewHelper.getStatusColor('failed')).assertEqual('error');
    });

    // ========== 切片12: formatParticipantsCount - 0 → "无参与者" ==========

    it('format_participants_count_zero_returns_none', 0, () => {
      expect(CollaborationInitiateViewHelper.formatParticipantsCount(0)).assertEqual('无参与者');
    });

    // ========== 切片13: formatParticipantsCount - 1 → "1 人" ==========

    it('format_participants_count_one_returns_one_person', 0, () => {
      expect(CollaborationInitiateViewHelper.formatParticipantsCount(1)).assertEqual('1 人');
    });

    // ========== 切片14: formatParticipantsCount - 5 → "5 人" ==========

    it('format_participants_count_multi_returns_multi_persons', 0, () => {
      expect(CollaborationInitiateViewHelper.formatParticipantsCount(5)).assertEqual('5 人');
    });
  });
}

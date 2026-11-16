// CollaborationHistoryPage 协作历史页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：CollaborationHistoryViewHelper 视图模型行为（协作状态颜色/图标/文案、
//           时间戳格式化、备注截断）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 CollaborationHistoryPage.ets 导出的
//       CollaborationHistoryViewHelper 静态方法进行验证。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { CollaborationHistoryViewHelper } from '../../../main/ets/pages/CollaborationHistoryPage';

export default function collaborationHistoryPageTest() {
  describe('CollaborationHistoryPage', () => {
    // ========== 切片1: getStatusColor - active → success ==========

    it('status_color_active_returns_success', 0, () => {
      expect(CollaborationHistoryViewHelper.getStatusColor('active')).assertEqual('success');
    });

    // ========== 切片2: getStatusColor - archived → warning ==========

    it('status_color_archived_returns_warning', 0, () => {
      expect(CollaborationHistoryViewHelper.getStatusColor('archived')).assertEqual('warning');
    });

    // ========== 切片3: getStatusColor - suspended → error ==========

    it('status_color_suspended_returns_error', 0, () => {
      expect(CollaborationHistoryViewHelper.getStatusColor('suspended')).assertEqual('error');
    });

    // ========== 切片4: getStatusColor - 未知状态 → info 兜底 ==========

    it('status_color_unknown_returns_info', 0, () => {
      expect(CollaborationHistoryViewHelper.getStatusColor('other')).assertEqual('info');
    });

    // ========== 切片5: getStatusIcon - active → ✅ ==========

    it('status_icon_active_returns_check', 0, () => {
      expect(CollaborationHistoryViewHelper.getStatusIcon('active')).assertEqual('✅');
    });

    // ========== 切片6: getStatusIcon - archived → 📦 ==========

    it('status_icon_archived_returns_box', 0, () => {
      expect(CollaborationHistoryViewHelper.getStatusIcon('archived')).assertEqual('📦');
    });

    // ========== 切片7: getStatusIcon - suspended → ⏸️ ==========

    it('status_icon_suspended_returns_pause', 0, () => {
      expect(CollaborationHistoryViewHelper.getStatusIcon('suspended')).assertEqual('⏸️');
    });

    // ========== 切片8: getStatusIcon - 未知状态 → 🔄 兜底 ==========

    it('status_icon_unknown_returns_refresh', 0, () => {
      expect(CollaborationHistoryViewHelper.getStatusIcon('other')).assertEqual('🔄');
    });

    // ========== 切片9: getStatusLabel - active → 进行中 ==========

    it('status_label_active_returns_in_progress', 0, () => {
      expect(CollaborationHistoryViewHelper.getStatusLabel('active')).assertEqual('进行中');
    });

    // ========== 切片10: getStatusLabel - archived → 已归档 ==========

    it('status_label_archived_returns_archived', 0, () => {
      expect(CollaborationHistoryViewHelper.getStatusLabel('archived')).assertEqual('已归档');
    });

    // ========== 切片11: getStatusLabel - suspended → 已暂停 ==========

    it('status_label_suspended_returns_suspended', 0, () => {
      expect(CollaborationHistoryViewHelper.getStatusLabel('suspended')).assertEqual('已暂停');
    });

    // ========== 切片12: getStatusLabel - 未知状态 → 未知 ==========

    it('status_label_unknown_returns_unknown', 0, () => {
      expect(CollaborationHistoryViewHelper.getStatusLabel('other')).assertEqual('未知');
    });

    // ========== 切片13: formatTimestamp - 正常时间 → "YYYY-MM-DD HH:mm" ==========

    it('format_timestamp_normal_returns_formatted', 0, () => {
      // 使用固定时间戳避免时区差异问题；本测试验证格式符合 YYYY-MM-DD HH:mm
      const ts = '2025-03-15T10:30:00Z';
      const result = CollaborationHistoryViewHelper.formatTimestamp(ts);
      // 验证格式：4 位年-2 位月-2 位日 空格 2 位时:2 位分
      const regex = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/;
      expect(regex.test(result)).assertTrue();
    });

    // ========== 切片14: formatTimestamp - 无效时间 → "未知" ==========

    it('format_timestamp_invalid_returns_unknown', 0, () => {
      expect(CollaborationHistoryViewHelper.formatTimestamp('invalid-date')).assertEqual('未知');
    });

    // ========== 切片15: truncateNote - 未超长 → 原样返回 ==========

    it('truncate_note_short_returns_original', 0, () => {
      expect(CollaborationHistoryViewHelper.truncateNote('短备注', 10)).assertEqual('短备注');
    });

    // ========== 切片16: truncateNote - 超长 → 截断 + "..." ==========

    it('truncate_note_long_returns_truncated', 0, () => {
      const note = '这是一个非常长的协作历史备注文本，用于测试截断功能是否正常工作';
      const result = CollaborationHistoryViewHelper.truncateNote(note, 10);
      expect(result).assertEqual('这是一个非常长的协作...');
    });
  });
}

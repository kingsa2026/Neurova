// CollaborationHistoryPage 协作历史页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：CollaborationHistoryViewHelper 视图模型行为（动作颜色/图标/文案、
//           时间戳格式化、元数据格式化、备注截断）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 CollaborationHistoryPage.ets 导出的
//       CollaborationHistoryViewHelper 静态方法进行验证。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { CollaborationHistoryViewHelper } from '../../../../main/ets/pages/CollaborationHistoryPage';

export default function collaborationHistoryPageTest() {
  describe('CollaborationHistoryPage', () => {
    // ========== 切片1: getActionColor - create → success ==========

    it('action_color_create_returns_success', 0, () => {
      expect(CollaborationHistoryViewHelper.getActionColor('create')).assertEqual('success');
    });

    // ========== 切片2: getActionColor - update → info ==========

    it('action_color_update_returns_info', 0, () => {
      expect(CollaborationHistoryViewHelper.getActionColor('update')).assertEqual('info');
    });

    // ========== 切片3: getActionColor - complete → success ==========

    it('action_color_complete_returns_success', 0, () => {
      expect(CollaborationHistoryViewHelper.getActionColor('complete')).assertEqual('success');
    });

    // ========== 切片4: getActionColor - archive → warning ==========

    it('action_color_archive_returns_warning', 0, () => {
      expect(CollaborationHistoryViewHelper.getActionColor('archive')).assertEqual('warning');
    });

    // ========== 切片5: getActionIcon - create → ✨ ==========

    it('action_icon_create_returns_sparkles', 0, () => {
      expect(CollaborationHistoryViewHelper.getActionIcon('create')).assertEqual('✨');
    });

    // ========== 切片6: getActionIcon - update → ✏️ ==========

    it('action_icon_update_returns_pencil', 0, () => {
      expect(CollaborationHistoryViewHelper.getActionIcon('update')).assertEqual('✏️');
    });

    // ========== 切片7: getActionIcon - complete → ✅ ==========

    it('action_icon_complete_returns_check', 0, () => {
      expect(CollaborationHistoryViewHelper.getActionIcon('complete')).assertEqual('✅');
    });

    // ========== 切片8: getActionIcon - archive → 📦 ==========

    it('action_icon_archive_returns_box', 0, () => {
      expect(CollaborationHistoryViewHelper.getActionIcon('archive')).assertEqual('📦');
    });

    // ========== 切片9: getActionLabel - create → 创建 ==========

    it('action_label_create_returns_create', 0, () => {
      expect(CollaborationHistoryViewHelper.getActionLabel('create')).assertEqual('创建');
    });

    // ========== 切片10: getActionLabel - update → 更新 ==========

    it('action_label_update_returns_update', 0, () => {
      expect(CollaborationHistoryViewHelper.getActionLabel('update')).assertEqual('更新');
    });

    // ========== 切片11: getActionLabel - complete → 完成 ==========

    it('action_label_complete_returns_complete', 0, () => {
      expect(CollaborationHistoryViewHelper.getActionLabel('complete')).assertEqual('完成');
    });

    // ========== 切片12: getActionLabel - archive → 归档 ==========

    it('action_label_archive_returns_archive', 0, () => {
      expect(CollaborationHistoryViewHelper.getActionLabel('archive')).assertEqual('归档');
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

    // ========== 切片15: formatMetadata - undefined → "无变更" ==========

    it('format_metadata_undefined_returns_no_change', 0, () => {
      expect(CollaborationHistoryViewHelper.formatMetadata(undefined)).assertEqual('无变更');
    });

    // ========== 切片16: formatMetadata - 有数据 → JSON 字符串 ==========

    it('format_metadata_with_data_returns_json', 0, () => {
      const meta = { field1: 'value1', field2: 123 };
      const result = CollaborationHistoryViewHelper.formatMetadata(meta);
      expect(result).assertEqual(JSON.stringify(meta));
    });

    // ========== 切片17: truncateNote - 未超长 → 原样返回 ==========

    it('truncate_note_short_returns_original', 0, () => {
      expect(CollaborationHistoryViewHelper.truncateNote('短备注', 10)).assertEqual('短备注');
    });

    // ========== 切片18: truncateNote - 超长 → 截断 + "..." ==========

    it('truncate_note_long_returns_truncated', 0, () => {
      const note = '这是一个非常长的协作历史备注文本，用于测试截断功能是否正常工作';
      const result = CollaborationHistoryViewHelper.truncateNote(note, 10);
      expect(result).assertEqual('这是一个非常长的协作...');
    });
  });
}

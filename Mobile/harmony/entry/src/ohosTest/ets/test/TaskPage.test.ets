// TaskPage 任务页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：TaskViewHelper 视图模型纯函数行为契约。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对 TaskPage 导出的 TaskViewHelper 静态方法进行验证，
//       覆盖页面 getStatusColor / getStatusIcon / getStatusLabel /
//       getPriorityColor / getPriorityIcon / getPriorityLabel /
//       formatTags / formatDate 的核心视图逻辑。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { TaskViewHelper } from '../../../../main/ets/pages/TaskPage';
import { TaskStatus, TaskPriority } from '../../../../main/ets/libs/types';

export default function taskPageTest() {
  describe('TaskPage', () => {
    // ========== 切片1: getStatusColor - todo → text_secondary ==========

    it('status_color_todo_returns_text_secondary', 0, () => {
      expect(TaskViewHelper.getStatusColor('todo' as TaskStatus)).assertEqual('text_secondary');
    });

    // ========== 切片2: getStatusColor - in_progress → info ==========

    it('status_color_in_progress_returns_info', 0, () => {
      expect(TaskViewHelper.getStatusColor('in_progress' as TaskStatus)).assertEqual('info');
    });

    // ========== 切片3: getStatusColor - review → warning ==========

    it('status_color_review_returns_warning', 0, () => {
      expect(TaskViewHelper.getStatusColor('review' as TaskStatus)).assertEqual('warning');
    });

    // ========== 切片4: getStatusColor - done → success ==========

    it('status_color_done_returns_success', 0, () => {
      expect(TaskViewHelper.getStatusColor('done' as TaskStatus)).assertEqual('success');
    });

    // ========== 切片5: getStatusColor - blocked → error ==========

    it('status_color_blocked_returns_error', 0, () => {
      expect(TaskViewHelper.getStatusColor('blocked' as TaskStatus)).assertEqual('error');
    });

    // ========== 切片6: getStatusIcon - todo → 📋 ==========

    it('status_icon_todo_returns_clipboard_emoji', 0, () => {
      expect(TaskViewHelper.getStatusIcon('todo' as TaskStatus)).assertEqual('📋');
    });

    // ========== 切片7: getStatusIcon - in_progress → ⚡ ==========

    it('status_icon_in_progress_returns_bolt_emoji', 0, () => {
      expect(TaskViewHelper.getStatusIcon('in_progress' as TaskStatus)).assertEqual('⚡');
    });

    // ========== 切片8: getStatusIcon - review → 🔍 ==========

    it('status_icon_review_returns_search_emoji', 0, () => {
      expect(TaskViewHelper.getStatusIcon('review' as TaskStatus)).assertEqual('🔍');
    });

    // ========== 切片9: getStatusIcon - done → ✅ ==========

    it('status_icon_done_returns_check_emoji', 0, () => {
      expect(TaskViewHelper.getStatusIcon('done' as TaskStatus)).assertEqual('✅');
    });

    // ========== 切片10: getStatusIcon - blocked → 🚫 ==========

    it('status_icon_blocked_returns_block_emoji', 0, () => {
      expect(TaskViewHelper.getStatusIcon('blocked' as TaskStatus)).assertEqual('🚫');
    });

    // ========== 切片11: getStatusLabel - todo → 待办 ==========

    it('status_label_todo_returns_daiban', 0, () => {
      expect(TaskViewHelper.getStatusLabel('todo' as TaskStatus)).assertEqual('待办');
    });

    // ========== 切片12: getStatusLabel - in_progress → 进行中 ==========

    it('status_label_in_progress_returns_jinxingzhong', 0, () => {
      expect(TaskViewHelper.getStatusLabel('in_progress' as TaskStatus)).assertEqual('进行中');
    });

    // ========== 切片13: getStatusLabel - done → 已完成 ==========

    it('status_label_done_returns_yiwancheng', 0, () => {
      expect(TaskViewHelper.getStatusLabel('done' as TaskStatus)).assertEqual('已完成');
    });

    // ========== 切片14: getStatusLabel - blocked → 已阻塞 ==========

    it('status_label_blocked_returns_yizusai', 0, () => {
      expect(TaskViewHelper.getStatusLabel('blocked' as TaskStatus)).assertEqual('已阻塞');
    });

    // ========== 切片15: getPriorityColor - low → text_secondary ==========

    it('priority_color_low_returns_text_secondary', 0, () => {
      expect(TaskViewHelper.getPriorityColor('low' as TaskPriority)).assertEqual('text_secondary');
    });

    // ========== 切片16: getPriorityColor - medium → info ==========

    it('priority_color_medium_returns_info', 0, () => {
      expect(TaskViewHelper.getPriorityColor('medium' as TaskPriority)).assertEqual('info');
    });

    // ========== 切片17: getPriorityColor - high → warning ==========

    it('priority_color_high_returns_warning', 0, () => {
      expect(TaskViewHelper.getPriorityColor('high' as TaskPriority)).assertEqual('warning');
    });

    // ========== 切片18: getPriorityColor - urgent → error ==========

    it('priority_color_urgent_returns_error', 0, () => {
      expect(TaskViewHelper.getPriorityColor('urgent' as TaskPriority)).assertEqual('error');
    });

    // ========== 切片19: getPriorityIcon - low → ⬇️ ==========

    it('priority_icon_low_returns_arrow_down_emoji', 0, () => {
      expect(TaskViewHelper.getPriorityIcon('low' as TaskPriority)).assertEqual('⬇️');
    });

    // ========== 切片20: getPriorityIcon - medium → ➡️ ==========

    it('priority_icon_medium_returns_arrow_right_emoji', 0, () => {
      expect(TaskViewHelper.getPriorityIcon('medium' as TaskPriority)).assertEqual('➡️');
    });

    // ========== 切片21: getPriorityIcon - high → ⬆️ ==========

    it('priority_icon_high_returns_arrow_up_emoji', 0, () => {
      expect(TaskViewHelper.getPriorityIcon('high' as TaskPriority)).assertEqual('⬆️');
    });

    // ========== 切片22: getPriorityIcon - urgent → 🚨 ==========

    it('priority_icon_urgent_returns_siren_emoji', 0, () => {
      expect(TaskViewHelper.getPriorityIcon('urgent' as TaskPriority)).assertEqual('🚨');
    });

    // ========== 切片23: getPriorityLabel - low → 低 ==========

    it('priority_label_low_returns_di', 0, () => {
      expect(TaskViewHelper.getPriorityLabel('low' as TaskPriority)).assertEqual('低');
    });

    // ========== 切片24: getPriorityLabel - medium → 中 ==========

    it('priority_label_medium_returns_zhong', 0, () => {
      expect(TaskViewHelper.getPriorityLabel('medium' as TaskPriority)).assertEqual('中');
    });

    // ========== 切片25: getPriorityLabel - high → 高 ==========

    it('priority_label_high_returns_gao', 0, () => {
      expect(TaskViewHelper.getPriorityLabel('high' as TaskPriority)).assertEqual('高');
    });

    // ========== 切片26: getPriorityLabel - urgent → 紧急 ==========

    it('priority_label_urgent_returns_jinji', 0, () => {
      expect(TaskViewHelper.getPriorityLabel('urgent' as TaskPriority)).assertEqual('紧急');
    });

    // ========== 切片27: formatTags - 空数组 → "无标签" ==========

    it('format_tags_empty_returns_empty_text', 0, () => {
      expect(TaskViewHelper.formatTags([])).assertEqual('无标签');
    });

    // ========== 切片28: formatTags - 多元素 → "a · b" ==========

    it('format_tags_array_returns_joined', 0, () => {
      expect(TaskViewHelper.formatTags(['a', 'b', 'c'])).assertEqual('a · b · c');
    });

    // ========== 切片29: formatTags - 单元素 → 原样返回 ==========

    it('format_tags_single_returns_single', 0, () => {
      expect(TaskViewHelper.formatTags(['bug'])).assertEqual('bug');
    });

    // ========== 切片30: formatDate - undefined → "—" ==========

    it('format_date_undefined_returns_dash', 0, () => {
      expect(TaskViewHelper.formatDate(undefined)).assertEqual('—');
    });

    // ========== 切片31: formatDate - 空字符串 → "—" ==========

    it('format_date_empty_returns_dash', 0, () => {
      expect(TaskViewHelper.formatDate('')).assertEqual('—');
    });

    // ========== 切片32: formatDate - ISO → YYYY-MM-DD ==========

    it('format_date_iso_returns_yyyy_mm_dd', 0, () => {
      const result = TaskViewHelper.formatDate('2024-06-15T08:30:00Z');
      expect(result.length).assertEqual(10);
      expect(result.startsWith('2024-06-15')).assertTrue();
    });

    // ========== 切片33: formatDate - 无效日期 → "—" ==========

    it('format_date_invalid_returns_dash', 0, () => {
      expect(TaskViewHelper.formatDate('not-a-date')).assertEqual('—');
    });
  });
}

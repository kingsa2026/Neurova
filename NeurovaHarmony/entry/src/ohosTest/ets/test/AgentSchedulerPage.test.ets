// AgentSchedulerPage 调度任务页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：AgentSchedulerViewHelper 视图模型行为（status 颜色映射、status 图标映射、
//           status 中文标签、cron 简化、nextRun/lastRun 格式化）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 AgentSchedulerPage.ets 导出的 AgentSchedulerViewHelper
//       静态方法进行验证，覆盖页面 getStatusColor / getStatusIcon / getStatusLabel /
//       formatCron / formatNextRun / formatLastRun 的核心视图逻辑。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { AgentSchedulerViewHelper } from '../../../../main/ets/pages/AgentSchedulerPage';
import { ScheduleTaskStatus } from '../../../../main/ets/libs/types';

export default function agentSchedulerPageTest() {
  describe('AgentSchedulerPage', () => {
    // ========== 切片1: getStatusColor - pending → warning ==========

    it('status_color_pending_returns_warning', 0, () => {
      expect(AgentSchedulerViewHelper.getStatusColor('pending' as ScheduleTaskStatus)).assertEqual('warning');
    });

    // ========== 切片2: getStatusColor - running → info ==========

    it('status_color_running_returns_info', 0, () => {
      expect(AgentSchedulerViewHelper.getStatusColor('running' as ScheduleTaskStatus)).assertEqual('info');
    });

    // ========== 切片3: getStatusColor - completed → success ==========

    it('status_color_completed_returns_success', 0, () => {
      expect(AgentSchedulerViewHelper.getStatusColor('completed' as ScheduleTaskStatus)).assertEqual('success');
    });

    // ========== 切片4: getStatusColor - failed → error ==========

    it('status_color_failed_returns_error', 0, () => {
      expect(AgentSchedulerViewHelper.getStatusColor('failed' as ScheduleTaskStatus)).assertEqual('error');
    });

    // ========== 切片5: getStatusColor - cancelled → text_disabled ==========

    it('status_color_cancelled_returns_text_disabled', 0, () => {
      expect(AgentSchedulerViewHelper.getStatusColor('cancelled' as ScheduleTaskStatus)).assertEqual('text_disabled');
    });

    // ========== 切片6: getStatusIcon - pending → ⏳ ==========

    it('status_icon_pending_returns_hourglass', 0, () => {
      expect(AgentSchedulerViewHelper.getStatusIcon('pending' as ScheduleTaskStatus)).assertEqual('⏳');
    });

    // ========== 切片7: getStatusIcon - running → ⚡ ==========

    it('status_icon_running_returns_bolt', 0, () => {
      expect(AgentSchedulerViewHelper.getStatusIcon('running' as ScheduleTaskStatus)).assertEqual('⚡');
    });

    // ========== 切片8: getStatusLabel - pending → 待执行 ==========

    it('status_label_pending_returns_chinese', 0, () => {
      expect(AgentSchedulerViewHelper.getStatusLabel('pending' as ScheduleTaskStatus)).assertEqual('待执行');
    });

    // ========== 切片9: getStatusLabel - cancelled → 已取消 ==========

    it('status_label_cancelled_returns_chinese', 0, () => {
      expect(AgentSchedulerViewHelper.getStatusLabel('cancelled' as ScheduleTaskStatus)).assertEqual('已取消');
    });

    // ========== 切片10: formatCron - 去掉空格 ==========

    it('format_cron_removes_spaces', 0, () => {
      expect(AgentSchedulerViewHelper.formatCron('0 * * * *')).assertEqual('0****');
    });

    // ========== 切片11: formatCron - 超长截断（>20 字符） ==========

    it('format_cron_truncates_long', 0, () => {
      const long = 'a'.repeat(25);
      const result = AgentSchedulerViewHelper.formatCron(long);
      expect(result.length).assertEqual(23);
      expect(result.endsWith('...')).assertTrue();
    });

    // ========== 切片12: formatCron - 短表达式原样（仅去空格） ==========

    it('format_cron_short_keeps_no_spaces', 0, () => {
      expect(AgentSchedulerViewHelper.formatCron('*/5 * * * *')).assertEqual('*/5*****');
    });

    // ========== 切片13: formatNextRun - 无值 → "未安排" ==========

    it('format_next_run_no_value_returns_unscheduled', 0, () => {
      expect(AgentSchedulerViewHelper.formatNextRun(undefined)).assertEqual('未安排');
    });

    // ========== 切片14: formatNextRun - 有值 → "下次：YYYY-MM-DD HH:mm" ==========

    it('format_next_run_with_value_returns_prefixed', 0, () => {
      const result = AgentSchedulerViewHelper.formatNextRun('2024-01-15T10:30:00');
      expect(result.substring(0, 3)).assertEqual('下次：');
      expect(result.length).assertEqual(19);
    });

    // ========== 切片15: formatLastRun - 无值 → "未运行" ==========

    it('format_last_run_no_value_returns_never_run', 0, () => {
      expect(AgentSchedulerViewHelper.formatLastRun(undefined)).assertEqual('未运行');
    });

    // ========== 切片16: formatLastRun - 有值 → "上次：YYYY-MM-DD HH:mm" ==========

    it('format_last_run_with_value_returns_prefixed', 0, () => {
      const result = AgentSchedulerViewHelper.formatLastRun('2024-02-20T08:45:00');
      expect(result.substring(0, 3)).assertEqual('上次：');
      expect(result.length).assertEqual(19);
    });
  });
}

// AgentComputerPage 计算机任务页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：AgentComputerViewHelper 视图模型行为（action 图标映射、action 中文标签、
//           status 颜色映射、duration 格式化、result 截断）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 AgentComputerPage.ets 导出的 AgentComputerViewHelper
//       静态方法进行验证，覆盖页面 getActionIcon / getActionLabel / getStatusColor /
//       formatDuration / truncateResult 的核心视图逻辑。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { AgentComputerViewHelper } from '../../../../main/ets/pages/AgentComputerPage';
import { ScheduleTaskStatus } from '../../../../main/ets/libs/types';

export default function agentComputerPageTest() {
  describe('AgentComputerPage', () => {
    // ========== 切片1: getActionIcon - click → 👆 ==========

    it('action_icon_click_returns_point', 0, () => {
      expect(AgentComputerViewHelper.getActionIcon('click')).assertEqual('👆');
    });

    // ========== 切片2: getActionIcon - type → ⌨️ ==========

    it('action_icon_type_returns_keyboard', 0, () => {
      expect(AgentComputerViewHelper.getActionIcon('type')).assertEqual('⌨️');
    });

    // ========== 切片3: getActionIcon - scroll → 📜 ==========

    it('action_icon_scroll_returns_scroll', 0, () => {
      expect(AgentComputerViewHelper.getActionIcon('scroll')).assertEqual('📜');
    });

    // ========== 切片4: getActionIcon - screenshot → 📷 ==========

    it('action_icon_screenshot_returns_camera', 0, () => {
      expect(AgentComputerViewHelper.getActionIcon('screenshot')).assertEqual('📷');
    });

    // ========== 切片5: getActionIcon - 未知 action → ❓ ==========

    it('action_icon_unknown_returns_default', 0, () => {
      expect(AgentComputerViewHelper.getActionIcon('unknown_action')).assertEqual('❓');
    });

    // ========== 切片6: getActionLabel - click → 点击 ==========

    it('action_label_click_returns_chinese', 0, () => {
      expect(AgentComputerViewHelper.getActionLabel('click')).assertEqual('点击');
    });

    // ========== 切片7: getActionLabel - screenshot → 截图 ==========

    it('action_label_screenshot_returns_chinese', 0, () => {
      expect(AgentComputerViewHelper.getActionLabel('screenshot')).assertEqual('截图');
    });

    // ========== 切片8: getActionLabel - 未知 action → 未知 ==========

    it('action_label_unknown_returns_default', 0, () => {
      expect(AgentComputerViewHelper.getActionLabel('foo')).assertEqual('未知');
    });

    // ========== 切片9: getStatusColor - completed → success ==========

    it('status_color_completed_returns_success', 0, () => {
      expect(AgentComputerViewHelper.getStatusColor('completed' as ScheduleTaskStatus)).assertEqual('success');
    });

    // ========== 切片10: getStatusColor - failed → error ==========

    it('status_color_failed_returns_error', 0, () => {
      expect(AgentComputerViewHelper.getStatusColor('failed' as ScheduleTaskStatus)).assertEqual('error');
    });

    // ========== 切片11: formatDuration - 无值 → "—" ==========

    it('format_duration_none_returns_dash', 0, () => {
      expect(AgentComputerViewHelper.formatDuration(undefined)).assertEqual('—');
    });

    // ========== 切片12: formatDuration - <1000ms → "n ms" ==========

    it('format_duration_under_second_returns_ms', 0, () => {
      expect(AgentComputerViewHelper.formatDuration(500)).assertEqual('500 ms');
    });

    // ========== 切片13: formatDuration - <60000ms → "n.nn s" ==========

    it('format_duration_under_minute_returns_seconds', 0, () => {
      expect(AgentComputerViewHelper.formatDuration(1500)).assertEqual('1.50 s');
    });

    // ========== 切片14: formatDuration - >=60000ms → "M:SS" ==========

    it('format_duration_over_minute_returns_mss', 0, () => {
      expect(AgentComputerViewHelper.formatDuration(65000)).assertEqual('1:05');
    });

    // ========== 切片15: truncateResult - 无值 → "—" ==========

    it('truncate_result_none_returns_dash', 0, () => {
      expect(AgentComputerViewHelper.truncateResult(undefined)).assertEqual('—');
    });

    // ========== 切片16: truncateResult - 默认 maxLen=100，超长截断 ==========

    it('truncate_result_default_max_len_100', 0, () => {
      const long = 'a'.repeat(150);
      const result = AgentComputerViewHelper.truncateResult(long);
      expect(result.length).assertEqual(103);
      expect(result.endsWith('...')).assertTrue();
    });

    // ========== 切片17: truncateResult - 自定义 maxLen ==========

    it('truncate_result_custom_max_len', 0, () => {
      expect(AgentComputerViewHelper.truncateResult('abcdefghij', 5)).assertEqual('abcde...');
    });
  });
}

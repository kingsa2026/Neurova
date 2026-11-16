// SandboxPage 沙盒环境页单元测试 - R6 契约切换
//
// 测试范围：SandboxViewHelper 视图模型行为（状态颜色/图标/标签映射（后端 status
//           开放集合兜默认）、思维沙箱判定、超时格式化、步骤数格式化、时间格式化）。
// 契约：_publicView（id/name/status/image/language/timeout/steps_count/created_at/
//       updated_at/agent_id/topic）——无 CPU/内存限制、端口、过期时间字段；
//       思维沙箱保留 id 'null' 不可执行/销毁。
import { describe, it, expect } from '@ohos/hypium';
import { SandboxViewHelper } from '../../../main/ets/pages/SandboxPage';

export default function sandboxPageTest() {
  describe('SandboxPage', () => {
    // ========== 切片1: getStatusColor ==========

    it('status_color_running_returns_success', 0, () => {
      expect(SandboxViewHelper.getStatusColor('running')).assertEqual('success');
    });

    it('status_color_failed_returns_error', 0, () => {
      expect(SandboxViewHelper.getStatusColor('failed')).assertEqual('error');
    });

    it('status_color_timeout_returns_warning', 0, () => {
      expect(SandboxViewHelper.getStatusColor('timeout')).assertEqual('warning');
    });

    it('status_color_committed_returns_info', 0, () => {
      expect(SandboxViewHelper.getStatusColor('committed')).assertEqual('info');
    });

    it('status_color_unknown_defaults', 0, () => {
      expect(SandboxViewHelper.getStatusColor('paused')).assertEqual('text_secondary');
    });

    // ========== 切片2: getStatusIcon / getStatusLabel ==========

    it('status_icon_running_returns_play', 0, () => {
      expect(SandboxViewHelper.getStatusIcon('running')).assertEqual('▶️');
    });

    it('status_label_committed', 0, () => {
      expect(SandboxViewHelper.getStatusLabel('committed')).assertEqual('已提交');
    });

    it('status_label_unknown_returns_raw', 0, () => {
      expect(SandboxViewHelper.getStatusLabel('paused')).assertEqual('paused');
    });

    // ========== 切片3: isThoughtSandbox - 保留 id 'null' 判定 ==========

    it('thought_sandbox_null_id_detected', 0, () => {
      expect(SandboxViewHelper.isThoughtSandbox(null)).assertTrue();
      expect(SandboxViewHelper.isThoughtSandbox('null')).assertTrue();
    });

    it('normal_sandbox_id_not_thought', 0, () => {
      expect(SandboxViewHelper.isThoughtSandbox('abc123def456')).assertFalse();
    });

    // ========== 切片4: formatTimeout ==========

    it('format_timeout_under_minute_returns_seconds', 0, () => {
      expect(SandboxViewHelper.formatTimeout(45)).assertEqual('45s');
    });

    it('format_timeout_over_minute_returns_minutes', 0, () => {
      expect(SandboxViewHelper.formatTimeout(300)).assertEqual('5min');
    });

    // ========== 切片5: formatStepsCount ==========

    it('format_steps_zero_returns_no_records', 0, () => {
      expect(SandboxViewHelper.formatStepsCount(0)).assertEqual('无执行记录');
    });

    it('format_steps_value_returns_count', 0, () => {
      expect(SandboxViewHelper.formatStepsCount(3)).assertEqual('3 步');
    });

    // ========== 切片6: formatTimestamp ==========

    it('format_timestamp_valid_iso', 0, () => {
      const formatted = SandboxViewHelper.formatTimestamp('2025-03-01T09:00:00Z');
      // 时区无关：合法 ISO 必产出 16 位 YYYY-MM-DD HH:mm（日期随设备时区，不锁字面值）
      expect(formatted.length === 16).assertTrue();
      expect(formatted.charAt(10)).assertEqual(' ');
      expect(formatted.charAt(13)).assertEqual(':');
    });

    it('format_timestamp_invalid_returns_dash', 0, () => {
      expect(SandboxViewHelper.formatTimestamp('')).assertEqual('—');
      expect(SandboxViewHelper.formatTimestamp('garbage')).assertEqual('—');
    });
  });
}

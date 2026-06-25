// WebhookPage Webhook 管理页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：WebhookViewHelper 视图模型行为（状态颜色/图标/文案、事件文案、
//           成功率格式化、URL 截断）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 WebhookPage.ets 导出的 WebhookViewHelper 静态方法进行验证。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { WebhookViewHelper } from '../../../../main/ets/pages/WebhookPage';
import { WebhookStatus, WebhookEvent } from '../../../../main/ets/libs/types';

export default function webhookPageTest() {
  describe('WebhookPage', () => {
    // ========== 切片1: getStatusColor - active → success ==========

    it('status_color_active_returns_success', 0, () => {
      expect(WebhookViewHelper.getStatusColor('active')).assertEqual('success');
    });

    // ========== 切片2: getStatusColor - paused → warning ==========

    it('status_color_paused_returns_warning', 0, () => {
      expect(WebhookViewHelper.getStatusColor('paused')).assertEqual('warning');
    });

    // ========== 切片3: getStatusColor - error → error ==========

    it('status_color_error_returns_error', 0, () => {
      expect(WebhookViewHelper.getStatusColor('error')).assertEqual('error');
    });

    // ========== 切片4: getStatusIcon - active → ✅ ==========

    it('status_icon_active_returns_check', 0, () => {
      expect(WebhookViewHelper.getStatusIcon('active')).assertEqual('✅');
    });

    // ========== 切片5: getStatusIcon - paused → ⏸️ ==========

    it('status_icon_paused_returns_pause', 0, () => {
      expect(WebhookViewHelper.getStatusIcon('paused')).assertEqual('⏸️');
    });

    // ========== 切片6: getStatusIcon - error → ❌ ==========

    it('status_icon_error_returns_cross', 0, () => {
      expect(WebhookViewHelper.getStatusIcon('error')).assertEqual('❌');
    });

    // ========== 切片7: getStatusLabel - active → 活跃 ==========

    it('status_label_active_returns_active', 0, () => {
      expect(WebhookViewHelper.getStatusLabel('active')).assertEqual('活跃');
    });

    // ========== 切片8: getStatusLabel - paused → 暂停 ==========

    it('status_label_paused_returns_paused', 0, () => {
      expect(WebhookViewHelper.getStatusLabel('paused')).assertEqual('暂停');
    });

    // ========== 切片9: getStatusLabel - error → 错误 ==========

    it('status_label_error_returns_error', 0, () => {
      expect(WebhookViewHelper.getStatusLabel('error')).assertEqual('错误');
    });

    // ========== 切片10: getEventLabel - message.received → 消息接收 ==========

    it('event_label_message_received_returns_msg_received', 0, () => {
      expect(WebhookViewHelper.getEventLabel('message.received')).assertEqual('消息接收');
    });

    // ========== 切片11: getEventLabel - agent.created → 智能体创建 ==========

    it('event_label_agent_created_returns_agent_created', 0, () => {
      expect(WebhookViewHelper.getEventLabel('agent.created')).assertEqual('智能体创建');
    });

    // ========== 切片12: getEventLabel - task.completed → 任务完成 ==========

    it('event_label_task_completed_returns_task_completed', 0, () => {
      expect(WebhookViewHelper.getEventLabel('task.completed')).assertEqual('任务完成');
    });

    // ========== 切片13: getEventLabel - memory.created → 记忆创建 ==========

    it('event_label_memory_created_returns_memory_created', 0, () => {
      expect(WebhookViewHelper.getEventLabel('memory.created')).assertEqual('记忆创建');
    });

    // ========== 切片14: formatSuccessRate - 全 0 → "—" ==========

    it('format_success_rate_all_zero_returns_dash', 0, () => {
      expect(WebhookViewHelper.formatSuccessRate(0, 0)).assertEqual('—');
    });

    // ========== 切片15: formatSuccessRate - 90 成功 10 失败 → "90.0%" ==========

    it('format_success_rate_normal_returns_percentage', 0, () => {
      expect(WebhookViewHelper.formatSuccessRate(90, 10)).assertEqual('90.0%');
    });

    // ========== 切片16: formatSuccessRate - 全失败 → "0.0%" ==========

    it('format_success_rate_all_failure_returns_zero', 0, () => {
      expect(WebhookViewHelper.formatSuccessRate(0, 10)).assertEqual('0.0%');
    });

    // ========== 切片17: truncateUrl - 未超长 → 原样返回 ==========

    it('truncate_url_short_returns_original', 0, () => {
      expect(WebhookViewHelper.truncateUrl('https://example.com', 30)).assertEqual('https://example.com');
    });

    // ========== 切片18: truncateUrl - 超长 → 截断 + "..." ==========

    it('truncate_url_long_returns_truncated', 0, () => {
      const url = 'https://api.example.com/webhooks/receive/very-long-path/with-many-segments';
      const result = WebhookViewHelper.truncateUrl(url, 20);
      expect(result).assertEqual('https://api.example....');
    });
  });
}

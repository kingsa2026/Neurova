// FirewallPage 系统防火墙页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：SystemFirewallViewHelper 视图模型行为（动作颜色/图标/标签映射、
//           协议标签、命中次数格式化、优先级格式化）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 FirewallPage.ets 导出的 SystemFirewallViewHelper 静态方法进行验证。
// 注意：本页为系统级防火墙，与 AgentFirewallPage 的 agent 级 FirewallViewHelper 区分，
//       类名使用 SystemFirewallViewHelper 避免命名冲突。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { SystemFirewallViewHelper } from '../../../../main/ets/pages/FirewallPage';

export default function firewallPageTest() {
  describe('FirewallPage', () => {
    // ========== 切片1: getActionColor - allow → success ==========

    it('action_color_allow_returns_success', 0, () => {
      expect(SystemFirewallViewHelper.getActionColor('allow')).assertEqual('success');
    });

    // ========== 切片2: getActionColor - deny → error ==========

    it('action_color_deny_returns_error', 0, () => {
      expect(SystemFirewallViewHelper.getActionColor('deny')).assertEqual('error');
    });

    // ========== 切片3: getActionColor - log → info ==========

    it('action_color_log_returns_info', 0, () => {
      expect(SystemFirewallViewHelper.getActionColor('log')).assertEqual('info');
    });

    // ========== 切片4: getActionColor - rate_limit → warning ==========

    it('action_color_rate_limit_returns_warning', 0, () => {
      expect(SystemFirewallViewHelper.getActionColor('rate_limit')).assertEqual('warning');
    });

    // ========== 切片5: getActionIcon - allow 返回 emoji ==========

    it('action_icon_allow_returns_emoji', 0, () => {
      expect(SystemFirewallViewHelper.getActionIcon('allow').length > 0).assertTrue();
    });

    // ========== 切片6: getActionIcon - deny 返回 emoji ==========

    it('action_icon_deny_returns_emoji', 0, () => {
      expect(SystemFirewallViewHelper.getActionIcon('deny').length > 0).assertTrue();
    });

    // ========== 切片7: getActionIcon - log 返回 emoji ==========

    it('action_icon_log_returns_emoji', 0, () => {
      expect(SystemFirewallViewHelper.getActionIcon('log').length > 0).assertTrue();
    });

    // ========== 切片8: getActionIcon - rate_limit 返回 emoji ==========

    it('action_icon_rate_limit_returns_emoji', 0, () => {
      expect(SystemFirewallViewHelper.getActionIcon('rate_limit').length > 0).assertTrue();
    });

    // ========== 切片9: getActionLabel - allow → 允许 ==========

    it('action_label_allow_returns_允许', 0, () => {
      expect(SystemFirewallViewHelper.getActionLabel('allow')).assertEqual('允许');
    });

    // ========== 切片10: getActionLabel - deny → 拒绝 ==========

    it('action_label_deny_returns_拒绝', 0, () => {
      expect(SystemFirewallViewHelper.getActionLabel('deny')).assertEqual('拒绝');
    });

    // ========== 切片11: getActionLabel - log → 记录 ==========

    it('action_label_log_returns_记录', 0, () => {
      expect(SystemFirewallViewHelper.getActionLabel('log')).assertEqual('记录');
    });

    // ========== 切片12: getActionLabel - rate_limit → 限流 ==========

    it('action_label_rate_limit_returns_限流', 0, () => {
      expect(SystemFirewallViewHelper.getActionLabel('rate_limit')).assertEqual('限流');
    });

    // ========== 切片13: getProtocolLabel - tcp → TCP ==========

    it('protocol_label_tcp_returns_TCP', 0, () => {
      expect(SystemFirewallViewHelper.getProtocolLabel('tcp')).assertEqual('TCP');
    });

    // ========== 切片14: getProtocolLabel - udp → UDP ==========

    it('protocol_label_udp_returns_UDP', 0, () => {
      expect(SystemFirewallViewHelper.getProtocolLabel('udp')).assertEqual('UDP');
    });

    // ========== 切片15: getProtocolLabel - icmp → ICMP ==========

    it('protocol_label_icmp_returns_ICMP', 0, () => {
      expect(SystemFirewallViewHelper.getProtocolLabel('icmp')).assertEqual('ICMP');
    });

    // ========== 切片16: getProtocolLabel - any → 任意 ==========

    it('protocol_label_any_returns_任意', 0, () => {
      expect(SystemFirewallViewHelper.getProtocolLabel('any')).assertEqual('任意');
    });

    // ========== 切片17: getProtocolLabel - undefined → '—' ==========

    it('protocol_label_undefined_returns_dash', 0, () => {
      expect(SystemFirewallViewHelper.getProtocolLabel(undefined)).assertEqual('—');
    });

    // ========== 切片18: formatHitCount - 0 → '未命中' ==========

    it('hit_count_zero_returns_未命中', 0, () => {
      expect(SystemFirewallViewHelper.formatHitCount(0)).assertEqual('未命中');
    });

    // ========== 切片19: formatHitCount - 1-999 → 原值 + '次' ==========

    it('hit_count_normal_returns_count_times', 0, () => {
      expect(SystemFirewallViewHelper.formatHitCount(42)).assertEqual('42次');
    });

    // ========== 切片20: formatHitCount - 999 → 边界 ==========

    it('hit_count_999_returns_count_times', 0, () => {
      expect(SystemFirewallViewHelper.formatHitCount(999)).assertEqual('999次');
    });

    // ========== 切片21: formatHitCount - ≥1000 → '999+次' ==========

    it('hit_count_over_1000_returns_999_plus', 0, () => {
      expect(SystemFirewallViewHelper.formatHitCount(1000)).assertEqual('999+次');
    });

    // ========== 切片22: formatHitCount - 大量命中 ==========

    it('hit_count_large_returns_999_plus', 0, () => {
      expect(SystemFirewallViewHelper.formatHitCount(99999)).assertEqual('999+次');
    });

    // ========== 切片23: formatPriority - 优先级 1 ==========

    it('format_priority_one', 0, () => {
      expect(SystemFirewallViewHelper.formatPriority(1)).assertEqual('优先级 1');
    });

    // ========== 切片24: formatPriority - 优先级 50 ==========

    it('format_priority_fifty', 0, () => {
      expect(SystemFirewallViewHelper.formatPriority(50)).assertEqual('优先级 50');
    });

    // ========== 切片25: formatPriority - 优先级 100 ==========

    it('format_priority_hundred', 0, () => {
      expect(SystemFirewallViewHelper.formatPriority(100)).assertEqual('优先级 100');
    });
  });
}

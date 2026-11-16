// FirewallPage 系统防火墙页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：SystemFirewallViewHelper 视图模型行为（动作颜色/图标/标签映射）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 FirewallPage.ets 导出的 SystemFirewallViewHelper 静态方法进行验证。
// 注意：本页为系统级防火墙，与 AgentFirewallPage 的 agent 级 FirewallViewHelper 区分，
//       类名使用 SystemFirewallViewHelper 避免命名冲突。
//       P1-33 接线真实 API（/v1/firewall/rules）后，动作集合与后端 FirewallAction
//       对齐为 allow/deny/ask；协议/命中次数/优先级无后端字段，相关视图函数随 mock
//       一并退役。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { SystemFirewallViewHelper } from '../../../main/ets/pages/FirewallPage';

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

    // ========== 切片3: getActionColor - ask → warning ==========

    it('action_color_ask_returns_warning', 0, () => {
      expect(SystemFirewallViewHelper.getActionColor('ask')).assertEqual('warning');
    });

    // ========== 切片4: getActionIcon - allow 返回 emoji ==========

    it('action_icon_allow_returns_emoji', 0, () => {
      expect(SystemFirewallViewHelper.getActionIcon('allow').length > 0).assertTrue();
    });

    // ========== 切片5: getActionIcon - deny 返回 emoji ==========

    it('action_icon_deny_returns_emoji', 0, () => {
      expect(SystemFirewallViewHelper.getActionIcon('deny').length > 0).assertTrue();
    });

    // ========== 切片6: getActionIcon - ask 返回 emoji ==========

    it('action_icon_ask_returns_emoji', 0, () => {
      expect(SystemFirewallViewHelper.getActionIcon('ask').length > 0).assertTrue();
    });

    // ========== 切片7: getActionLabel - allow → 允许 ==========

    it('action_label_allow_returns_允许', 0, () => {
      expect(SystemFirewallViewHelper.getActionLabel('allow')).assertEqual('允许');
    });

    // ========== 切片8: getActionLabel - deny → 拒绝 ==========

    it('action_label_deny_returns_拒绝', 0, () => {
      expect(SystemFirewallViewHelper.getActionLabel('deny')).assertEqual('拒绝');
    });

    // ========== 切片9: getActionLabel - ask → 询问 ==========

    it('action_label_ask_returns_询问', 0, () => {
      expect(SystemFirewallViewHelper.getActionLabel('ask')).assertEqual('询问');
    });
  });
}

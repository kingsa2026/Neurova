// AgentFirewallPage 防火墙规则页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：FirewallViewHelper 视图模型行为契约（动作颜色映射、动作图标映射、动作标签映射、
//           范围颜色映射、范围标签映射、资源路径截断）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 AgentFirewallPage.ets 导出的 FirewallViewHelper 静态方法进行验证，
//       覆盖页面 getActionColor / getActionIcon / getActionLabel / getScopeColor /
//       getScopeLabel / truncateResource 共 6 个核心视图逻辑方法。
// 视图模型刻意设计为无 UI 依赖的纯函数，颜色方法返回 StyleManager 的 token 名（如 'success'）
// 而非已解析颜色值，便于测试与主题切换；其他方法返回 emoji 或中文字符串。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { FirewallViewHelper } from '../../../../main/ets/pages/AgentFirewallPage';
import { FirewallAction } from '../../../../main/ets/libs/types';

export default function agentFirewallPageTest() {
  describe('AgentFirewallPage', () => {
    // ========== 切片1: getActionColor - allow → success ==========

    it('action_color_allow_returns_success', 0, () => {
      expect(FirewallViewHelper.getActionColor('allow' as FirewallAction)).assertEqual('success');
    });

    // ========== 切片2: getActionColor - deny → error ==========

    it('action_color_deny_returns_error', 0, () => {
      expect(FirewallViewHelper.getActionColor('deny' as FirewallAction)).assertEqual('error');
    });

    // ========== 切片3: getActionColor - ask → warning ==========

    it('action_color_ask_returns_warning', 0, () => {
      expect(FirewallViewHelper.getActionColor('ask' as FirewallAction)).assertEqual('warning');
    });

    // ========== 切片4: getActionIcon - allow → ✅ ==========

    it('action_icon_allow_returns_check', 0, () => {
      expect(FirewallViewHelper.getActionIcon('allow' as FirewallAction)).assertEqual('✅');
    });

    // ========== 切片5: getActionIcon - deny → ⛔ ==========

    it('action_icon_deny_returns_block', 0, () => {
      expect(FirewallViewHelper.getActionIcon('deny' as FirewallAction)).assertEqual('⛔');
    });

    // ========== 切片6: getActionIcon - ask → ❓ ==========

    it('action_icon_ask_returns_question', 0, () => {
      expect(FirewallViewHelper.getActionIcon('ask' as FirewallAction)).assertEqual('❓');
    });

    // ========== 切片7: getActionLabel - allow/deny/ask → 允许/拒绝/询问 ==========

    it('action_label_returns_chinese', 0, () => {
      expect(FirewallViewHelper.getActionLabel('allow' as FirewallAction)).assertEqual('允许');
      expect(FirewallViewHelper.getActionLabel('deny' as FirewallAction)).assertEqual('拒绝');
      expect(FirewallViewHelper.getActionLabel('ask' as FirewallAction)).assertEqual('询问');
    });

    // ========== 切片8: getScopeColor - inbound → info ==========

    it('scope_color_inbound_returns_info', 0, () => {
      expect(FirewallViewHelper.getScopeColor('inbound')).assertEqual('info');
    });

    // ========== 切片9: getScopeColor - outbound → warning ==========

    it('scope_color_outbound_returns_warning', 0, () => {
      expect(FirewallViewHelper.getScopeColor('outbound')).assertEqual('warning');
    });

    // ========== 切片10: getScopeColor - both → error ==========

    it('scope_color_both_returns_error', 0, () => {
      expect(FirewallViewHelper.getScopeColor('both')).assertEqual('error');
    });

    // ========== 切片11: getScopeLabel - inbound/outbound/both → 入站/出站/双向 ==========

    it('scope_label_returns_chinese', 0, () => {
      expect(FirewallViewHelper.getScopeLabel('inbound')).assertEqual('入站');
      expect(FirewallViewHelper.getScopeLabel('outbound')).assertEqual('出站');
      expect(FirewallViewHelper.getScopeLabel('both')).assertEqual('双向');
    });

    // ========== 切片12: truncateResource - 默认 maxLen=60 ==========

    it('truncate_resource_default_max_len_60', 0, () => {
      // 60 字符以内原样返回
      const short = 'a'.repeat(60);
      const result1 = FirewallViewHelper.truncateResource(short);
      expect(result1).assertEqual(short);
      // 61 字符 → 截断到 60 + "..."（共 63 字符）
      const long = 'a'.repeat(61);
      const result2 = FirewallViewHelper.truncateResource(long);
      expect(result2.length).assertEqual(63);
      expect(result2.substring(60)).assertEqual('...');
    });

    // ========== 切片13: truncateResource - 自定义 maxLen ==========

    it('truncate_resource_custom_max_len', 0, () => {
      // 自定义 maxLen=20
      const text = 'abcdefghijklmnopqrstuvwxyz';
      const result = FirewallViewHelper.truncateResource(text, 20);
      expect(result.length).assertEqual(23);
      expect(result.substring(20)).assertEqual('...');
      // 未超长时原样返回
      expect(FirewallViewHelper.truncateResource('hello', 20)).assertEqual('hello');
    });

    // ========== 切片14: truncateResource - 空字符串边界 ==========

    it('truncate_resource_empty_string', 0, () => {
      // 空字符串原样返回
      expect(FirewallViewHelper.truncateResource('')).assertEqual('');
      // 0 长度自定义 maxLen
      expect(FirewallViewHelper.truncateResource('abc', 0)).assertEqual('...');
    });
  });
}

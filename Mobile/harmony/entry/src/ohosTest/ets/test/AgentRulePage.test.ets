// AgentRulePage 智能体规则页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：AgentRuleViewHelper 视图模型行为契约。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对 AgentRulePage 导出的 AgentRuleViewHelper 静态方法进行验证，
//       覆盖规则类型颜色/图标/标签映射、状态颜色/标签映射、优先级格式化、文本截断 7 个方法。
// 视图模型刻意设计为无 UI 依赖的纯函数，返回颜色 token 名（如 'warning'）而非已解析
// 颜色值，便于测试与主题切换。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { AgentRuleViewHelper } from '../../../../main/ets/pages/AgentRulePage';
import { RuleType, RuleStatus } from '../../../../main/ets/libs/types';

export default function agentRulePageTest() {
  describe('AgentRulePage', () => {
    // ========== 切片 1: getTypeColor - permission → warning ==========

    it('type_color_permission_returns_warning', 0, () => {
      expect(AgentRuleViewHelper.getTypeColor('permission' as RuleType)).assertEqual('warning');
    });

    // ========== 切片 2: getTypeColor - restriction → error ==========

    it('type_color_restriction_returns_error', 0, () => {
      expect(AgentRuleViewHelper.getTypeColor('restriction' as RuleType)).assertEqual('error');
    });

    // ========== 切片 3: getTypeColor - behavior → info ==========

    it('type_color_behavior_returns_info', 0, () => {
      expect(AgentRuleViewHelper.getTypeColor('behavior' as RuleType)).assertEqual('info');
    });

    // ========== 切片 4: getTypeColor - workflow → primary ==========

    it('type_color_workflow_returns_primary', 0, () => {
      expect(AgentRuleViewHelper.getTypeColor('workflow' as RuleType)).assertEqual('primary');
    });

    // ========== 切片 5: getTypeIcon - permission → 🛡️ ==========

    it('type_icon_permission_returns_shield', 0, () => {
      expect(AgentRuleViewHelper.getTypeIcon('permission' as RuleType)).assertEqual('🛡️');
    });

    // ========== 切片 6: getTypeIcon - restriction → 🚫 ==========

    it('type_icon_restriction_returns_block', 0, () => {
      expect(AgentRuleViewHelper.getTypeIcon('restriction' as RuleType)).assertEqual('🚫');
    });

    // ========== 切片 7: getTypeIcon - behavior → ⚙️ ==========

    it('type_icon_behavior_returns_gear', 0, () => {
      expect(AgentRuleViewHelper.getTypeIcon('behavior' as RuleType)).assertEqual('⚙️');
    });

    // ========== 切片 8: getTypeIcon - workflow → 🔄 ==========

    it('type_icon_workflow_returns_loop', 0, () => {
      expect(AgentRuleViewHelper.getTypeIcon('workflow' as RuleType)).assertEqual('🔄');
    });

    // ========== 切片 9: getTypeLabel - 四种类型对应中文 ==========

    it('type_label_returns_chinese', 0, () => {
      expect(AgentRuleViewHelper.getTypeLabel('permission' as RuleType)).assertEqual('权限');
      expect(AgentRuleViewHelper.getTypeLabel('restriction' as RuleType)).assertEqual('限制');
      expect(AgentRuleViewHelper.getTypeLabel('behavior' as RuleType)).assertEqual('行为');
      expect(AgentRuleViewHelper.getTypeLabel('workflow' as RuleType)).assertEqual('工作流');
    });

    // ========== 切片 10: getStatusColor - active/inactive/archived ==========

    it('status_color_returns_correct_token', 0, () => {
      expect(AgentRuleViewHelper.getStatusColor('active' as RuleStatus)).assertEqual('success');
      expect(AgentRuleViewHelper.getStatusColor('inactive' as RuleStatus)).assertEqual('text_disabled');
      expect(AgentRuleViewHelper.getStatusColor('archived' as RuleStatus)).assertEqual('text_secondary');
    });

    // ========== 切片 11: getStatusLabel - 启用/禁用/归档 ==========

    it('status_label_returns_chinese', 0, () => {
      expect(AgentRuleViewHelper.getStatusLabel('active' as RuleStatus)).assertEqual('启用');
      expect(AgentRuleViewHelper.getStatusLabel('inactive' as RuleStatus)).assertEqual('禁用');
      expect(AgentRuleViewHelper.getStatusLabel('archived' as RuleStatus)).assertEqual('归档');
    });

    // ========== 切片 12: formatPriority - 数字 → Pn 格式 ==========

    it('format_priority_returns_Pn_format', 0, () => {
      // 1 → "P1"，5 → "P5"，其他数字也按 P{n} 格式
      expect(AgentRuleViewHelper.formatPriority(1)).assertEqual('P1');
      expect(AgentRuleViewHelper.formatPriority(5)).assertEqual('P5');
      expect(AgentRuleViewHelper.formatPriority(3)).assertEqual('P3');
      expect(AgentRuleViewHelper.formatPriority(10)).assertEqual('P10');
    });

    // ========== 切片 13: truncateText - 默认 maxLen=80 ==========

    it('truncate_text_default_max_len_80', 0, () => {
      // 80 字符以内原样返回
      const short = 'a'.repeat(80);
      const result1 = AgentRuleViewHelper.truncateText(short);
      expect(result1).assertEqual(short);
      // 81 字符 → 截断到 80 + "..."（共 83 字符）
      const long = 'a'.repeat(81);
      const result2 = AgentRuleViewHelper.truncateText(long);
      expect(result2.length).assertEqual(83);
      expect(result2.substring(80)).assertEqual('...');
    });

    // ========== 切片 14: truncateText - 自定义 maxLen ==========

    it('truncate_text_custom_max_len', 0, () => {
      // 自定义 maxLen=10
      const text = 'abcdefghijklmnopqrstuvwxyz';
      const result = AgentRuleViewHelper.truncateText(text, 10);
      expect(result.length).assertEqual(13);
      expect(result.substring(10)).assertEqual('...');
      // 未超长时原样返回
      expect(AgentRuleViewHelper.truncateText('hello', 10)).assertEqual('hello');
    });
  });
}

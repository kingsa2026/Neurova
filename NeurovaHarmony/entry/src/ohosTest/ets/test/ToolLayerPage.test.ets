// ToolLayerPage 工具层管理页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：ToolLayerViewHelper 视图模型行为（启用状态颜色映射、启用状态图标、启用状态文案、
//           优先级格式化、工具数格式化、描述截断）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 ToolLayerPage.ets 导出的 ToolLayerViewHelper 静态方法进行验证，
//       覆盖页面 getEnabledColor / getEnabledIcon / getEnabledLabel / formatPriority /
//       formatToolCount / truncateDescription 的核心视图逻辑。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { ToolLayerViewHelper } from '../../../../main/ets/pages/ToolLayerPage';

export default function toolLayerPageTest() {
  describe('ToolLayerPage', () => {
    // ========== 切片1: getEnabledColor - true → success ==========

    it('enabled_color_true_returns_success', 0, () => {
      expect(ToolLayerViewHelper.getEnabledColor(true)).assertEqual('success');
    });

    // ========== 切片2: getEnabledColor - false → text_disabled ==========

    it('enabled_color_false_returns_text_disabled', 0, () => {
      expect(ToolLayerViewHelper.getEnabledColor(false)).assertEqual('text_disabled');
    });

    // ========== 切片3: getEnabledIcon - true → ✅ ==========

    it('enabled_icon_true_returns_check', 0, () => {
      expect(ToolLayerViewHelper.getEnabledIcon(true)).assertEqual('✅');
    });

    // ========== 切片4: getEnabledIcon - false → ❌ ==========

    it('enabled_icon_false_returns_cross', 0, () => {
      expect(ToolLayerViewHelper.getEnabledIcon(false)).assertEqual('❌');
    });

    // ========== 切片5: getEnabledLabel - true → 已启用 ==========

    it('enabled_label_true_returns_enabled', 0, () => {
      expect(ToolLayerViewHelper.getEnabledLabel(true)).assertEqual('已启用');
    });

    // ========== 切片6: getEnabledLabel - false → 已禁用 ==========

    it('enabled_label_false_returns_disabled', 0, () => {
      expect(ToolLayerViewHelper.getEnabledLabel(false)).assertEqual('已禁用');
    });

    // ========== 切片7: formatPriority - 1 → "优先级 1" ==========

    it('format_priority_one_returns_priority_1', 0, () => {
      expect(ToolLayerViewHelper.formatPriority(1)).assertEqual('优先级 1');
    });

    // ========== 切片8: formatPriority - 5 → "优先级 5" ==========

    it('format_priority_five_returns_priority_5', 0, () => {
      expect(ToolLayerViewHelper.formatPriority(5)).assertEqual('优先级 5');
    });

    // ========== 切片9: formatToolCount - 0 → "无工具" ==========

    it('format_tool_count_zero_returns_no_tools', 0, () => {
      expect(ToolLayerViewHelper.formatToolCount(0)).assertEqual('无工具');
    });

    // ========== 切片10: formatToolCount - 3 → "工具 3 个" ==========

    it('format_tool_count_three_returns_tools_3', 0, () => {
      expect(ToolLayerViewHelper.formatToolCount(3)).assertEqual('工具 3 个');
    });

    // ========== 切片11: truncateDescription - 默认 maxLen=80 ==========

    it('truncate_description_default_80', 0, () => {
      const long = 'a'.repeat(100);
      const result = ToolLayerViewHelper.truncateDescription(long);
      expect(result.length).assertEqual(83);
      expect(result.substring(80)).assertEqual('...');
    });

    // ========== 切片12: truncateDescription - 未超长原样返回 ==========

    it('truncate_description_no_truncation', 0, () => {
      const s = 'a'.repeat(80);
      const result = ToolLayerViewHelper.truncateDescription(s);
      expect(result).assertEqual(s);
    });

    // ========== 切片13: truncateDescription - 自定义 maxLen ==========

    it('truncate_description_custom_maxLen', 0, () => {
      const s = 'abcdefg';
      const result = ToolLayerViewHelper.truncateDescription(s, 5);
      expect(result).assertEqual('abcde...');
    });
  });
}

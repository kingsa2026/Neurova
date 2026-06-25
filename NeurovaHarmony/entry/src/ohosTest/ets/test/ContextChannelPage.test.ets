// ContextChannelPage 上下文消息页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：ContextChannelViewHelper 视图模型行为（role 颜色映射、role 图标映射、
//           role 中文标签、tokens 格式化、content 截断）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 ContextChannelPage.ets 导出的 ContextChannelViewHelper
//       静态方法进行验证，覆盖页面 getRoleColor / getRoleIcon / getRoleLabel /
//       formatTokens / truncateContent 的核心视图逻辑。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { ContextChannelViewHelper } from '../../../../main/ets/pages/ContextChannelPage';
import { ContextRole } from '../../../../main/ets/libs/types';

export default function contextChannelPageTest() {
  describe('ContextChannelPage', () => {
    // ========== 切片1: getRoleColor - system → text_secondary ==========

    it('role_color_system_returns_text_secondary', 0, () => {
      expect(ContextChannelViewHelper.getRoleColor('system' as ContextRole)).assertEqual('text_secondary');
    });

    // ========== 切片2: getRoleColor - user → primary ==========

    it('role_color_user_returns_primary', 0, () => {
      expect(ContextChannelViewHelper.getRoleColor('user' as ContextRole)).assertEqual('primary');
    });

    // ========== 切片3: getRoleColor - assistant → success ==========

    it('role_color_assistant_returns_success', 0, () => {
      expect(ContextChannelViewHelper.getRoleColor('assistant' as ContextRole)).assertEqual('success');
    });

    // ========== 切片4: getRoleColor - tool → warning ==========

    it('role_color_tool_returns_warning', 0, () => {
      expect(ContextChannelViewHelper.getRoleColor('tool' as ContextRole)).assertEqual('warning');
    });

    // ========== 切片5: getRoleIcon - system → ⚙️ ==========

    it('role_icon_system_returns_gear', 0, () => {
      expect(ContextChannelViewHelper.getRoleIcon('system' as ContextRole)).assertEqual('⚙️');
    });

    // ========== 切片6: getRoleIcon - assistant → 🤖 ==========

    it('role_icon_assistant_returns_robot', 0, () => {
      expect(ContextChannelViewHelper.getRoleIcon('assistant' as ContextRole)).assertEqual('🤖');
    });

    // ========== 切片7: getRoleLabel - user → 用户 ==========

    it('role_label_user_returns_chinese', 0, () => {
      expect(ContextChannelViewHelper.getRoleLabel('user' as ContextRole)).assertEqual('用户');
    });

    // ========== 切片8: getRoleLabel - tool → 工具 ==========

    it('role_label_tool_returns_chinese', 0, () => {
      expect(ContextChannelViewHelper.getRoleLabel('tool' as ContextRole)).assertEqual('工具');
    });

    // ========== 切片9: formatTokens - 0 → "0 tokens" ==========

    it('format_tokens_zero_returns_zero', 0, () => {
      expect(ContextChannelViewHelper.formatTokens(0)).assertEqual('0 tokens');
    });

    // ========== 切片10: formatTokens - 1024 → "1.0K tokens" ==========

    it('format_tokens_k_returns_k_format', 0, () => {
      expect(ContextChannelViewHelper.formatTokens(1024)).assertEqual('1.0K tokens');
    });

    // ========== 切片11: formatTokens - 1048576 → "1.0M tokens" ==========

    it('format_tokens_m_returns_m_format', 0, () => {
      expect(ContextChannelViewHelper.formatTokens(1048576)).assertEqual('1.0M tokens');
    });

    // ========== 切片12: truncateContent - 默认 maxLen=200，超长截断加省略号 ==========

    it('truncate_content_default_max_len_200', 0, () => {
      const long = 'a'.repeat(250);
      const result = ContextChannelViewHelper.truncateContent(long);
      expect(result.length).assertEqual(203);
      expect(result.endsWith('...')).assertTrue();
    });

    // ========== 切片13: truncateContent - 未超长原样返回 ==========

    it('truncate_content_short_returns_original', 0, () => {
      expect(ContextChannelViewHelper.truncateContent('短消息')).assertEqual('短消息');
    });

    // ========== 切片14: truncateContent - 自定义 maxLen ==========

    it('truncate_content_custom_max_len', 0, () => {
      const result = ContextChannelViewHelper.truncateContent('abcdefghij', 5);
      expect(result).assertEqual('abcde...');
    });
  });
}

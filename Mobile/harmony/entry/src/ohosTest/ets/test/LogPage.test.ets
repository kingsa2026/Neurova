// LogPage 日志页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：LogViewHelper 视图模型纯函数行为契约。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对 LogPage 导出的 LogViewHelper 静态方法进行验证，
//       覆盖页面 getLevelColor / getLevelIcon / getLevelLabel /
//       formatTimestamp / truncateMessage / formatContext 的核心视图逻辑。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
//
// 颜色 token 说明：返回 StyleManager 实际支持的 token 名（'info'/'warning'/'error'/
//   'success'/'text_secondary' 等），不加 'status_' 前缀，确保 StyleManager.getColor()
//   能正确解析为实际色值，与 TaskPage/ProjectPage 现有模式一致。
import { describe, it, expect } from '@ohos/hypium';
import { LogViewHelper } from '../../../../main/ets/pages/LogPage';
import { LogLevel, Metadata } from '../../../../main/ets/libs/types';

export default function logPageTest() {
  describe('LogPage', () => {
    // ========== 切片1: getLevelColor - debug → text_secondary ==========

    it('level_color_debug_returns_text_secondary', 0, () => {
      expect(LogViewHelper.getLevelColor('debug' as LogLevel)).assertEqual('text_secondary');
    });

    // ========== 切片2: getLevelColor - info → info ==========

    it('level_color_info_returns_info', 0, () => {
      expect(LogViewHelper.getLevelColor('info' as LogLevel)).assertEqual('info');
    });

    // ========== 切片3: getLevelColor - warn → warning ==========

    it('level_color_warn_returns_warning', 0, () => {
      expect(LogViewHelper.getLevelColor('warn' as LogLevel)).assertEqual('warning');
    });

    // ========== 切片4: getLevelColor - error → error ==========

    it('level_color_error_returns_error', 0, () => {
      expect(LogViewHelper.getLevelColor('error' as LogLevel)).assertEqual('error');
    });

    // ========== 切片5: getLevelColor - fatal → error（深红用 error token） ==========

    it('level_color_fatal_returns_error', 0, () => {
      expect(LogViewHelper.getLevelColor('fatal' as LogLevel)).assertEqual('error');
    });

    // ========== 切片6: getLevelIcon - debug → 🔍 ==========

    it('level_icon_debug_returns_magnifier_emoji', 0, () => {
      expect(LogViewHelper.getLevelIcon('debug' as LogLevel)).assertEqual('🔍');
    });

    // ========== 切片7: getLevelIcon - info → ℹ️ ==========

    it('level_icon_info_returns_info_emoji', 0, () => {
      expect(LogViewHelper.getLevelIcon('info' as LogLevel)).assertEqual('ℹ️');
    });

    // ========== 切片8: getLevelIcon - warn → ⚠️ ==========

    it('level_icon_warn_returns_warning_emoji', 0, () => {
      expect(LogViewHelper.getLevelIcon('warn' as LogLevel)).assertEqual('⚠️');
    });

    // ========== 切片9: getLevelIcon - error → ❌ ==========

    it('level_icon_error_returns_cross_emoji', 0, () => {
      expect(LogViewHelper.getLevelIcon('error' as LogLevel)).assertEqual('❌');
    });

    // ========== 切片10: getLevelIcon - fatal → 💀 ==========

    it('level_icon_fatal_returns_skull_emoji', 0, () => {
      expect(LogViewHelper.getLevelIcon('fatal' as LogLevel)).assertEqual('💀');
    });

    // ========== 切片11: getLevelLabel - debug → 调试 ==========

    it('level_label_debug_returns_tiaoshi', 0, () => {
      expect(LogViewHelper.getLevelLabel('debug' as LogLevel)).assertEqual('调试');
    });

    // ========== 切片12: getLevelLabel - info → 信息 ==========

    it('level_label_info_returns_xinxi', 0, () => {
      expect(LogViewHelper.getLevelLabel('info' as LogLevel)).assertEqual('信息');
    });

    // ========== 切片13: getLevelLabel - warn → 警告 ==========

    it('level_label_warn_returns_jinggao', 0, () => {
      expect(LogViewHelper.getLevelLabel('warn' as LogLevel)).assertEqual('警告');
    });

    // ========== 切片14: getLevelLabel - error → 错误 ==========

    it('level_label_error_returns_cuowu', 0, () => {
      expect(LogViewHelper.getLevelLabel('error' as LogLevel)).assertEqual('错误');
    });

    // ========== 切片15: getLevelLabel - fatal → 致命 ==========

    it('level_label_fatal_returns_zhiming', 0, () => {
      expect(LogViewHelper.getLevelLabel('fatal' as LogLevel)).assertEqual('致命');
    });

    // ========== 切片16: formatTimestamp - ISO → YYYY-MM-DD HH:mm:ss ==========

    it('format_timestamp_iso_returns_full_datetime', 0, () => {
      // 2024-06-15T08:30:45Z → 长度 19，前缀匹配 'YYYY-MM-DD HH:mm:ss'
      const result = LogViewHelper.formatTimestamp('2024-06-15T08:30:45Z');
      expect(result.length).assertEqual(19);
      expect(result.indexOf('2024-06-15')).assertEqual(0);
      expect(result.charAt(10)).assertEqual(' ');
      expect(result.charAt(4)).assertEqual('-');
      expect(result.charAt(13)).assertEqual(':');
    });

    // ========== 切片17: formatTimestamp - undefined → '-' ==========

    it('format_timestamp_undefined_returns_dash', 0, () => {
      expect(LogViewHelper.formatTimestamp(undefined)).assertEqual('-');
    });

    // ========== 切片18: formatTimestamp - 空字符串 → '-' ==========

    it('format_timestamp_empty_returns_dash', 0, () => {
      expect(LogViewHelper.formatTimestamp('')).assertEqual('-');
    });

    // ========== 切片19: formatTimestamp - 无效日期 → '-' ==========

    it('format_timestamp_invalid_returns_dash', 0, () => {
      expect(LogViewHelper.formatTimestamp('not-a-date')).assertEqual('-');
    });

    // ========== 切片20: truncateMessage - 未超长原样返回 ==========

    it('truncate_message_under_max_returns_original', 0, () => {
      const msg = '这是一条普通日志';
      expect(LogViewHelper.truncateMessage(msg, 100)).assertEqual(msg);
    });

    // ========== 切片21: truncateMessage - 超长截断加省略号 ==========

    it('truncate_message_over_max_returns_ellipsis', 0, () => {
      const long = 'a'.repeat(150);
      const result = LogViewHelper.truncateMessage(long, 50);
      expect(result.length).assertEqual(53);
      expect(result.substring(50)).assertEqual('...');
    });

    // ========== 切片22: truncateMessage - 默认 maxLen（100） ==========

    it('truncate_message_default_max_len', 0, () => {
      const long = 'x'.repeat(120);
      const result = LogViewHelper.truncateMessage(long);
      expect(result.length).assertEqual(103);
      expect(result.substring(100)).assertEqual('...');
    });

    // ========== 切片23: formatContext - undefined → '无' ==========

    it('format_context_undefined_returns_wu', 0, () => {
      expect(LogViewHelper.formatContext(undefined)).assertEqual('无');
    });

    // ========== 切片24: formatContext - 空对象 → '无' ==========

    it('format_context_empty_object_returns_wu', 0, () => {
      const empty: Metadata = {};
      expect(LogViewHelper.formatContext(empty)).assertEqual('无');
    });

    // ========== 切片25: formatContext - 非空对象 → JSON 字符串 ==========

    it('format_context_object_returns_json_string', 0, () => {
      const ctx: Metadata = { user: 'alice', count: 3 };
      const result = LogViewHelper.formatContext(ctx);
      // 应为合法 JSON 字符串，且可解析回原对象
      expect(result !== '无').assertTrue();
      expect(result.charAt(0)).assertEqual('{');
      const parsed = JSON.parse(result);
      expect(parsed['user']).assertEqual('alice');
      expect(parsed['count']).assertEqual(3);
    });
  });
}

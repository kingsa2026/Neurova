// AgentTracePage 追踪条目页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：AgentTraceViewHelper 视图模型行为（level 颜色映射、level 图标映射、
//           level 中文标签、payload 格式化、duration 格式化、timestamp 格式化）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 AgentTracePage.ets 导出的 AgentTraceViewHelper
//       静态方法进行验证，覆盖页面 getLevelColor / getLevelIcon / getLevelLabel /
//       formatPayload / formatDuration / formatTimestamp 的核心视图逻辑。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { AgentTraceViewHelper } from '../../../../main/ets/pages/AgentTracePage';
import { TraceLevel } from '../../../../main/ets/libs/types';

export default function agentTracePageTest() {
  describe('AgentTracePage', () => {
    // ========== 切片1: getLevelColor - debug → text_disabled ==========

    it('level_color_debug_returns_text_disabled', 0, () => {
      expect(AgentTraceViewHelper.getLevelColor('debug' as TraceLevel)).assertEqual('text_disabled');
    });

    // ========== 切片2: getLevelColor - info → info ==========

    it('level_color_info_returns_info', 0, () => {
      expect(AgentTraceViewHelper.getLevelColor('info' as TraceLevel)).assertEqual('info');
    });

    // ========== 切片3: getLevelColor - warn → warning ==========

    it('level_color_warn_returns_warning', 0, () => {
      expect(AgentTraceViewHelper.getLevelColor('warn' as TraceLevel)).assertEqual('warning');
    });

    // ========== 切片4: getLevelColor - error → error ==========

    it('level_color_error_returns_error', 0, () => {
      expect(AgentTraceViewHelper.getLevelColor('error' as TraceLevel)).assertEqual('error');
    });

    // ========== 切片5: getLevelIcon - debug → 🔍 ==========

    it('level_icon_debug_returns_magnifier', 0, () => {
      expect(AgentTraceViewHelper.getLevelIcon('debug' as TraceLevel)).assertEqual('🔍');
    });

    // ========== 切片6: getLevelIcon - error → 🔴 ==========

    it('level_icon_error_returns_red_circle', 0, () => {
      expect(AgentTraceViewHelper.getLevelIcon('error' as TraceLevel)).assertEqual('🔴');
    });

    // ========== 切片7: getLevelIcon - warn → ⚠️ ==========

    it('level_icon_warn_returns_warning', 0, () => {
      expect(AgentTraceViewHelper.getLevelIcon('warn' as TraceLevel)).assertEqual('⚠️');
    });

    // ========== 切片8: getLevelLabel - info → 信息 ==========

    it('level_label_info_returns_chinese', 0, () => {
      expect(AgentTraceViewHelper.getLevelLabel('info' as TraceLevel)).assertEqual('信息');
    });

    // ========== 切片9: getLevelLabel - warn → 警告 ==========

    it('level_label_warn_returns_chinese', 0, () => {
      expect(AgentTraceViewHelper.getLevelLabel('warn' as TraceLevel)).assertEqual('警告');
    });

    // ========== 切片10: formatPayload - 无值 → "—" ==========

    it('format_payload_none_returns_dash', 0, () => {
      expect(AgentTraceViewHelper.formatPayload(undefined)).assertEqual('—');
    });

    // ========== 切片11: formatPayload - 对象 → JSON.stringify 后截断 200 字符 ==========

    it('format_payload_object_returns_json', 0, () => {
      const payload = { foo: 'bar', num: 42 };
      const result = AgentTraceViewHelper.formatPayload(payload);
      expect(result.startsWith('{')).assertTrue();
      expect(result.indexOf('"foo"')).assertEqual(1);
    });

    // ========== 切片12: formatPayload - 大对象截断 200 字符 ==========

    it('format_payload_large_object_truncates', 0, () => {
      const big: Record<string, string> = {};
      for (let i = 0; i < 100; i++) {
        big[`key${i}`] = 'value'.repeat(10);
      }
      const result = AgentTraceViewHelper.formatPayload(big);
      expect(result.length).assertEqual(203);
      expect(result.endsWith('...')).assertTrue();
    });

    // ========== 切片13: formatDuration - 无值 → "—" ==========

    it('format_duration_none_returns_dash', 0, () => {
      expect(AgentTraceViewHelper.formatDuration(undefined)).assertEqual('—');
    });

    // ========== 切片14: formatDuration - <1000ms → "n ms" ==========

    it('format_duration_under_second_returns_ms', 0, () => {
      expect(AgentTraceViewHelper.formatDuration(250)).assertEqual('250 ms');
    });

    // ========== 切片15: formatTimestamp - YYYY-MM-DD HH:mm:ss ==========

    it('format_timestamp_returns_formatted', 0, () => {
      const result = AgentTraceViewHelper.formatTimestamp('2024-01-15T10:30:45');
      expect(result).assertEqual('2024-01-15 10:30:45');
    });
  });
}

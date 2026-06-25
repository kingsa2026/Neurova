// MetacognitionPage 元认知页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：MetacognitionViewHelper 视图模型行为（type 颜色映射、type 图标映射、
//           type 中文标签、confidence 格式化、内容截断）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 MetacognitionPage.ets 导出的 MetacognitionViewHelper
//       静态方法进行验证，覆盖页面 getTypeColor / getTypeIcon / getTypeLabel /
//       formatConfidence / truncateContent 的核心视图逻辑。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { MetacognitionViewHelper } from '../../../../main/ets/pages/MetacognitionPage';

export default function metacognitionPageTest() {
  describe('MetacognitionPage', () => {
    // ========== 切片1: getTypeColor - monitoring → info ==========

    it('type_color_monitoring_returns_info', 0, () => {
      expect(MetacognitionViewHelper.getTypeColor('monitoring')).assertEqual('info');
    });

    // ========== 切片2: getTypeColor - control → primary ==========

    it('type_color_control_returns_primary', 0, () => {
      expect(MetacognitionViewHelper.getTypeColor('control')).assertEqual('primary');
    });

    // ========== 切片3: getTypeColor - evaluation → warning ==========

    it('type_color_evaluation_returns_warning', 0, () => {
      expect(MetacognitionViewHelper.getTypeColor('evaluation')).assertEqual('warning');
    });

    // ========== 切片4: getTypeIcon - monitoring → 👁️ ==========

    it('type_icon_monitoring_returns_eye', 0, () => {
      expect(MetacognitionViewHelper.getTypeIcon('monitoring')).assertEqual('👁️');
    });

    // ========== 切片5: getTypeIcon - control → 🎛️ ==========

    it('type_icon_control_returns_knob', 0, () => {
      expect(MetacognitionViewHelper.getTypeIcon('control')).assertEqual('🎛️');
    });

    // ========== 切片6: getTypeIcon - evaluation → 📊 ==========

    it('type_icon_evaluation_returns_chart', 0, () => {
      expect(MetacognitionViewHelper.getTypeIcon('evaluation')).assertEqual('📊');
    });

    // ========== 切片7: getTypeLabel - monitoring → 监控 ==========

    it('type_label_monitoring_returns_chinese', 0, () => {
      expect(MetacognitionViewHelper.getTypeLabel('monitoring')).assertEqual('监控');
    });

    // ========== 切片8: getTypeLabel - control → 控制 ==========

    it('type_label_control_returns_chinese', 0, () => {
      expect(MetacognitionViewHelper.getTypeLabel('control')).assertEqual('控制');
    });

    // ========== 切片9: getTypeLabel - evaluation → 评估 ==========

    it('type_label_evaluation_returns_chinese', 0, () => {
      expect(MetacognitionViewHelper.getTypeLabel('evaluation')).assertEqual('评估');
    });

    // ========== 切片10: formatConfidence - 0.5 → "50%" ==========

    it('format_confidence_half_returns_50_percent', 0, () => {
      expect(MetacognitionViewHelper.formatConfidence(0.5)).assertEqual('50%');
    });

    // ========== 切片11: formatConfidence - 1 → "100%" ==========

    it('format_confidence_full_returns_100_percent', 0, () => {
      expect(MetacognitionViewHelper.formatConfidence(1)).assertEqual('100%');
    });

    // ========== 切片12: formatConfidence - 0 → "0%" ==========

    it('format_confidence_zero_returns_0_percent', 0, () => {
      expect(MetacognitionViewHelper.formatConfidence(0)).assertEqual('0%');
    });

    // ========== 切片13: truncateContent - 默认 maxLen=120，超长截断加省略号 ==========

    it('truncate_content_default_max_len_120', 0, () => {
      const long = 'a'.repeat(200);
      const result = MetacognitionViewHelper.truncateContent(long);
      expect(result.length).assertEqual(123);
      expect(result.substring(120)).assertEqual('...');
    });

    // ========== 切片14: truncateContent - 未超长原样返回 ==========

    it('truncate_content_short_returns_original', 0, () => {
      const short = '短内容';
      expect(MetacognitionViewHelper.truncateContent(short)).assertEqual('短内容');
    });

    // ========== 切片15: truncateContent - 自定义 maxLen ==========

    it('truncate_content_custom_max_len', 0, () => {
      const text = 'abcdefghij';
      const result = MetacognitionViewHelper.truncateContent(text, 5);
      expect(result).assertEqual('abcde...');
    });
  });
}

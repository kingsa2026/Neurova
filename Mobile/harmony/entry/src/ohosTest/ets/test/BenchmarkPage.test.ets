// BenchmarkPage 基准评测页单元测试 - R6 契约切换
//
// 测试范围：BenchmarkViewHelper 视图模型行为（难度颜色/标签映射、运行状态
//           颜色/图标/标签映射、延迟格式化（null → 未测量）、得分格式化、
//           时间戳短格式）。
// 契约：后端 benchmark.py 是 LLM 评测套件域（difficulty/category/suite/run），
//       评测执行器未接线时 status='simulated'、score/avg_latency_ms 恒 null；
//       开放集合未知值兜默认，不抛错。
import { describe, it, expect } from '@ohos/hypium';
import { BenchmarkViewHelper } from '../../../main/ets/pages/BenchmarkPage';

export default function benchmarkPageTest() {
  describe('BenchmarkPage', () => {
    // ========== 切片1: getDifficultyColor ==========

    it('difficulty_color_easy_returns_success', 0, () => {
      expect(BenchmarkViewHelper.getDifficultyColor('easy')).assertEqual('success');
    });

    it('difficulty_color_medium_returns_warning', 0, () => {
      expect(BenchmarkViewHelper.getDifficultyColor('medium')).assertEqual('warning');
    });

    it('difficulty_color_hard_returns_error', 0, () => {
      expect(BenchmarkViewHelper.getDifficultyColor('hard')).assertEqual('error');
    });

    it('difficulty_color_unknown_defaults_to_info', 0, () => {
      expect(BenchmarkViewHelper.getDifficultyColor('extreme')).assertEqual('info');
    });

    // ========== 切片2: getDifficultyLabel ==========

    it('difficulty_label_easy', 0, () => {
      expect(BenchmarkViewHelper.getDifficultyLabel('easy')).assertEqual('简单');
    });

    it('difficulty_label_unknown_returns_raw', 0, () => {
      expect(BenchmarkViewHelper.getDifficultyLabel('extreme')).assertEqual('extreme');
    });

    // ========== 切片3: getStatusColor - simulated 是执行器未接线的诚实标记 ==========

    it('status_color_simulated_returns_warning', 0, () => {
      expect(BenchmarkViewHelper.getStatusColor('simulated')).assertEqual('warning');
    });

    it('status_color_completed_returns_success', 0, () => {
      expect(BenchmarkViewHelper.getStatusColor('completed')).assertEqual('success');
    });

    it('status_color_failed_returns_error', 0, () => {
      expect(BenchmarkViewHelper.getStatusColor('failed')).assertEqual('error');
    });

    it('status_color_unknown_defaults', 0, () => {
      expect(BenchmarkViewHelper.getStatusColor('queued')).assertEqual('text_secondary');
    });

    // ========== 切片4: getStatusIcon / getStatusLabel ==========

    it('status_icon_simulated_returns_flask', 0, () => {
      expect(BenchmarkViewHelper.getStatusIcon('simulated')).assertEqual('🧪');
    });

    it('status_label_simulated', 0, () => {
      expect(BenchmarkViewHelper.getStatusLabel('simulated')).assertEqual('模拟运行');
    });

    // ========== 切片5: formatLatency - null 未测量 + ms/s 两档 ==========

    it('format_latency_null_returns_unmeasured', 0, () => {
      expect(BenchmarkViewHelper.formatLatency(null)).assertEqual('未测量');
    });

    it('format_latency_under_second_returns_ms', 0, () => {
      expect(BenchmarkViewHelper.formatLatency(5.2)).assertEqual('5.2ms');
    });

    it('format_latency_over_second_returns_s', 0, () => {
      expect(BenchmarkViewHelper.formatLatency(1500)).assertEqual('1.5s');
    });

    // ========== 切片6: formatScore ==========

    it('format_score_null_returns_unmeasured', 0, () => {
      expect(BenchmarkViewHelper.formatScore(null)).assertEqual('未测量');
    });

    it('format_score_value_returns_raw', 0, () => {
      expect(BenchmarkViewHelper.formatScore(8800)).assertEqual('8800');
    });

    // ========== 切片7: formatTimestampShort ==========

    it('format_timestamp_short_valid_iso', 0, () => {
      const formatted = BenchmarkViewHelper.formatTimestampShort('2025-03-01T09:00:00Z');
      // 时区无关：合法 ISO 必产出 16 位 YYYY-MM-DD HH:mm（日期随设备时区，不锁字面值）
      expect(formatted.length === 16).assertTrue();
      expect(formatted.charAt(10)).assertEqual(' ');
      expect(formatted.charAt(13)).assertEqual(':');
    });

    it('format_timestamp_short_invalid_returns_dash', 0, () => {
      expect(BenchmarkViewHelper.formatTimestampShort('')).assertEqual('—');
      expect(BenchmarkViewHelper.formatTimestampShort('garbage')).assertEqual('—');
    });
  });
}

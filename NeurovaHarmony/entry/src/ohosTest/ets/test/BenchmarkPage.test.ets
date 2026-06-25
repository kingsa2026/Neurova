// BenchmarkPage 性能基准页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：BenchmarkViewHelper 视图模型行为（基准类型颜色/图标/标签映射、
//           状态颜色/图标映射、延迟格式化、吞吐量格式化）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 BenchmarkPage.ets 导出的 BenchmarkViewHelper 静态方法进行验证。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { BenchmarkViewHelper } from '../../../../main/ets/pages/BenchmarkPage';

export default function benchmarkPageTest() {
  describe('BenchmarkPage', () => {
    // ========== 切片1: getTypeColor - cpu → primary ==========

    it('type_color_cpu_returns_primary', 0, () => {
      expect(BenchmarkViewHelper.getTypeColor('cpu')).assertEqual('primary');
    });

    // ========== 切片2: getTypeColor - memory → info ==========

    it('type_color_memory_returns_info', 0, () => {
      expect(BenchmarkViewHelper.getTypeColor('memory')).assertEqual('info');
    });

    // ========== 切片3: getTypeColor - disk → warning ==========

    it('type_color_disk_returns_warning', 0, () => {
      expect(BenchmarkViewHelper.getTypeColor('disk')).assertEqual('warning');
    });

    // ========== 切片4: getTypeColor - network → success ==========

    it('type_color_network_returns_success', 0, () => {
      expect(BenchmarkViewHelper.getTypeColor('network')).assertEqual('success');
    });

    // ========== 切片5: getTypeColor - llm_inference → error ==========

    it('type_color_llm_inference_returns_error', 0, () => {
      expect(BenchmarkViewHelper.getTypeColor('llm_inference')).assertEqual('error');
    });

    // ========== 切片6: getTypeColor - embedding → text_secondary ==========

    it('type_color_embedding_returns_text_secondary', 0, () => {
      expect(BenchmarkViewHelper.getTypeColor('embedding')).assertEqual('text_secondary');
    });

    // ========== 切片7: getTypeIcon - cpu 返回 emoji ==========

    it('type_icon_cpu_returns_emoji', 0, () => {
      const icon = BenchmarkViewHelper.getTypeIcon('cpu');
      expect(icon.length > 0).assertTrue();
    });

    // ========== 切片8: getTypeIcon - memory 返回 emoji ==========

    it('type_icon_memory_returns_emoji', 0, () => {
      const icon = BenchmarkViewHelper.getTypeIcon('memory');
      expect(icon.length > 0).assertTrue();
    });

    // ========== 切片9: getTypeLabel - cpu → CPU ==========

    it('type_label_cpu_returns_CPU', 0, () => {
      expect(BenchmarkViewHelper.getTypeLabel('cpu')).assertEqual('CPU');
    });

    // ========== 切片10: getTypeLabel - memory → 内存 ==========

    it('type_label_memory_returns_内存', 0, () => {
      expect(BenchmarkViewHelper.getTypeLabel('memory')).assertEqual('内存');
    });

    // ========== 切片11: getTypeLabel - disk → 磁盘 ==========

    it('type_label_disk_returns_磁盘', 0, () => {
      expect(BenchmarkViewHelper.getTypeLabel('disk')).assertEqual('磁盘');
    });

    // ========== 切片12: getTypeLabel - network → 网络 ==========

    it('type_label_network_returns_网络', 0, () => {
      expect(BenchmarkViewHelper.getTypeLabel('network')).assertEqual('网络');
    });

    // ========== 切片13: getTypeLabel - llm_inference → LLM 推理 ==========

    it('type_label_llm_inference_returns_LLM推理', 0, () => {
      expect(BenchmarkViewHelper.getTypeLabel('llm_inference')).assertEqual('LLM 推理');
    });

    // ========== 切片14: getTypeLabel - embedding → 向量嵌入 ==========

    it('type_label_embedding_returns_向量嵌入', 0, () => {
      expect(BenchmarkViewHelper.getTypeLabel('embedding')).assertEqual('向量嵌入');
    });

    // ========== 切片15: getStatusColor - pending → text_secondary ==========

    it('status_color_pending_returns_text_secondary', 0, () => {
      expect(BenchmarkViewHelper.getStatusColor('pending')).assertEqual('text_secondary');
    });

    // ========== 切片16: getStatusColor - running → info ==========

    it('status_color_running_returns_info', 0, () => {
      expect(BenchmarkViewHelper.getStatusColor('running')).assertEqual('info');
    });

    // ========== 切片17: getStatusColor - completed → success ==========

    it('status_color_completed_returns_success', 0, () => {
      expect(BenchmarkViewHelper.getStatusColor('completed')).assertEqual('success');
    });

    // ========== 切片18: getStatusColor - failed → error ==========

    it('status_color_failed_returns_error', 0, () => {
      expect(BenchmarkViewHelper.getStatusColor('failed')).assertEqual('error');
    });

    // ========== 切片19: getStatusIcon - pending 返回 emoji ==========

    it('status_icon_pending_returns_emoji', 0, () => {
      const icon = BenchmarkViewHelper.getStatusIcon('pending');
      expect(icon.length > 0).assertTrue();
    });

    // ========== 切片20: getStatusIcon - running 返回 emoji ==========

    it('status_icon_running_returns_emoji', 0, () => {
      const icon = BenchmarkViewHelper.getStatusIcon('running');
      expect(icon.length > 0).assertTrue();
    });

    // ========== 切片21: formatLatency - 小于 1000ms ==========

    it('format_latency_under_1000_returns_ms', 0, () => {
      expect(BenchmarkViewHelper.formatLatency(500)).assertEqual('500.0ms');
    });

    // ========== 切片22: formatLatency - 等于 1000ms → '1.0s' ==========

    it('format_latency_1000_returns_seconds', 0, () => {
      expect(BenchmarkViewHelper.formatLatency(1000)).assertEqual('1.0s');
    });

    // ========== 切片23: formatLatency - 大于 1000ms ==========

    it('format_latency_over_1000_returns_seconds', 0, () => {
      expect(BenchmarkViewHelper.formatLatency(1500)).assertEqual('1.5s');
    });

    // ========== 切片24: formatLatency - 小数毫秒 ==========

    it('format_latency_decimal_ms', 0, () => {
      expect(BenchmarkViewHelper.formatLatency(0.5)).assertEqual('0.5ms');
    });

    // ========== 切片25: formatThroughput - undefined → '—' ==========

    it('format_throughput_undefined_returns_dash', 0, () => {
      expect(BenchmarkViewHelper.formatThroughput(undefined)).assertEqual('—');
    });

    // ========== 切片26: formatThroughput - 小于 1000 ops/s ==========

    it('format_throughput_under_1000_returns_ops', 0, () => {
      expect(BenchmarkViewHelper.formatThroughput(500)).assertEqual('500 ops/s');
    });

    // ========== 切片27: formatThroughput - 等于 1000 → '1.0K ops/s' ==========

    it('format_throughput_1000_returns_kops', 0, () => {
      expect(BenchmarkViewHelper.formatThroughput(1000)).assertEqual('1.0K ops/s');
    });

    // ========== 切片28: formatThroughput - 大于 1000 ops/s ==========

    it('format_throughput_over_1000_returns_kops', 0, () => {
      expect(BenchmarkViewHelper.formatThroughput(2500)).assertEqual('2.5K ops/s');
    });
  });
}

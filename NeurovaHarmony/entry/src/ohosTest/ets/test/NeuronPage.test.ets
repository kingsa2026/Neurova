// NeuronPage 神经元页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：NeuronViewHelper 视图模型纯函数行为契约。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对 NeuronPage 导出的 NeuronViewHelper 静态方法进行验证，
//       覆盖页面 getStateColor / getStateIcon / getStateLabel / formatActivation /
//       getActivationBarColor / truncateNeuronName 的核心视图逻辑。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
//
// 颜色 token 说明：返回 StyleManager 实际支持的 token 名（'info'/'success'/'error'/
//   'warning'/'text_secondary'），不加 'status_' 前缀，与 TaskPage/ProjectPage 现有模式一致。
import { describe, it, expect } from '@ohos/hypium';
import { NeuronViewHelper } from '../../../../main/ets/pages/NeuronPage';
import { NeuronState } from '../../../../main/ets/libs/types';

export default function neuronPageTest() {
  describe('NeuronPage', () => {
    // ========== 切片1: getStateColor - idle → text_secondary ==========

    it('state_color_idle_returns_text_secondary', 0, () => {
      expect(NeuronViewHelper.getStateColor('idle' as NeuronState)).assertEqual('text_secondary');
    });

    // ========== 切片2: getStateColor - active → info ==========

    it('state_color_active_returns_info', 0, () => {
      expect(NeuronViewHelper.getStateColor('active' as NeuronState)).assertEqual('info');
    });

    // ========== 切片3: getStateColor - firing → success ==========

    it('state_color_firing_returns_success', 0, () => {
      expect(NeuronViewHelper.getStateColor('firing' as NeuronState)).assertEqual('success');
    });

    // ========== 切片4: getStateColor - inhibited → error ==========

    it('state_color_inhibited_returns_error', 0, () => {
      expect(NeuronViewHelper.getStateColor('inhibited' as NeuronState)).assertEqual('error');
    });

    // ========== 切片5: getStateIcon - idle → 💤 ==========

    it('state_icon_idle_returns_sleep_emoji', 0, () => {
      expect(NeuronViewHelper.getStateIcon('idle' as NeuronState)).assertEqual('💤');
    });

    // ========== 切片6: getStateIcon - active → ⚡ ==========

    it('state_icon_active_returns_bolt_emoji', 0, () => {
      expect(NeuronViewHelper.getStateIcon('active' as NeuronState)).assertEqual('⚡');
    });

    // ========== 切片7: getStateIcon - firing → 🔥 ==========

    it('state_icon_firing_returns_fire_emoji', 0, () => {
      expect(NeuronViewHelper.getStateIcon('firing' as NeuronState)).assertEqual('🔥');
    });

    // ========== 切片8: getStateIcon - inhibited → 🚫 ==========

    it('state_icon_inhibited_returns_block_emoji', 0, () => {
      expect(NeuronViewHelper.getStateIcon('inhibited' as NeuronState)).assertEqual('🚫');
    });

    // ========== 切片9: getStateLabel - idle → 空闲 ==========

    it('state_label_idle_returns_kongxian', 0, () => {
      expect(NeuronViewHelper.getStateLabel('idle' as NeuronState)).assertEqual('空闲');
    });

    // ========== 切片10: getStateLabel - active → 活跃 ==========

    it('state_label_active_returns_huoyue', 0, () => {
      expect(NeuronViewHelper.getStateLabel('active' as NeuronState)).assertEqual('活跃');
    });

    // ========== 切片11: getStateLabel - firing → 激发 ==========

    it('state_label_firing_returns_jifa', 0, () => {
      expect(NeuronViewHelper.getStateLabel('firing' as NeuronState)).assertEqual('激发');
    });

    // ========== 切片12: getStateLabel - inhibited → 抑制 ==========

    it('state_label_inhibited_returns_yizhi', 0, () => {
      expect(NeuronViewHelper.getStateLabel('inhibited' as NeuronState)).assertEqual('抑制');
    });

    // ========== 切片13: formatActivation - 0 → '0.0%' ==========

    it('format_activation_zero_returns_zero_percent', 0, () => {
      expect(NeuronViewHelper.formatActivation(0)).assertEqual('0.0%');
    });

    // ========== 切片14: formatActivation - 0.5 → '50.0%' ==========

    it('format_activation_half_returns_fifty_percent', 0, () => {
      expect(NeuronViewHelper.formatActivation(0.5)).assertEqual('50.0%');
    });

    // ========== 切片15: formatActivation - 1 → '100.0%' ==========

    it('format_activation_full_returns_hundred_percent', 0, () => {
      expect(NeuronViewHelper.formatActivation(1)).assertEqual('100.0%');
    });

    // ========== 切片16: formatActivation - 0.456 → '45.6%'（保留 1 位小数） ==========

    it('format_activation_decimal_returns_one_decimal', 0, () => {
      expect(NeuronViewHelper.formatActivation(0.456)).assertEqual('45.6%');
    });

    // ========== 切片17: formatActivation - 超出 1 → 截断到 100.0% ==========

    it('format_activation_over_one_clamped_to_hundred', 0, () => {
      expect(NeuronViewHelper.formatActivation(1.5)).assertEqual('100.0%');
    });

    // ========== 切片18: formatActivation - 负数 → 截断到 0.0% ==========

    it('format_activation_negative_clamped_to_zero', 0, () => {
      expect(NeuronViewHelper.formatActivation(-0.3)).assertEqual('0.0%');
    });

    // ========== 切片19: getActivationBarColor - <0.3 → info ==========

    it('activation_bar_color_low_returns_info', 0, () => {
      expect(NeuronViewHelper.getActivationBarColor(0.2)).assertEqual('info');
    });

    // ========== 切片20: getActivationBarColor - 0.3 边界 → warning ==========

    it('activation_bar_color_threshold_low_returns_warning', 0, () => {
      expect(NeuronViewHelper.getActivationBarColor(0.3)).assertEqual('warning');
    });

    // ========== 切片21: getActivationBarColor - 0.5（中段）→ warning ==========

    it('activation_bar_color_mid_returns_warning', 0, () => {
      expect(NeuronViewHelper.getActivationBarColor(0.5)).assertEqual('warning');
    });

    // ========== 切片22: getActivationBarColor - 0.7 边界 → warning ==========

    it('activation_bar_color_threshold_high_returns_warning', 0, () => {
      expect(NeuronViewHelper.getActivationBarColor(0.7)).assertEqual('warning');
    });

    // ========== 切片23: getActivationBarColor - >0.7 → success ==========

    it('activation_bar_color_high_returns_success', 0, () => {
      expect(NeuronViewHelper.getActivationBarColor(0.8)).assertEqual('success');
    });

    // ========== 切片24: truncateNeuronName - 未超长原样返回 ==========

    it('truncate_neuron_name_under_max_returns_original', 0, () => {
      const name = '神经元-001';
      expect(NeuronViewHelper.truncateNeuronName(name, 100)).assertEqual(name);
    });

    // ========== 切片25: truncateNeuronName - 超长截断加省略号 ==========

    it('truncate_neuron_name_over_max_returns_ellipsis', 0, () => {
      const long = 'n'.repeat(60);
      const result = NeuronViewHelper.truncateNeuronName(long, 30);
      expect(result.length).assertEqual(33);
      expect(result.substring(30)).assertEqual('...');
    });

    // ========== 切片26: truncateNeuronName - 默认 maxLen（100） ==========

    it('truncate_neuron_name_default_max_len', 0, () => {
      const long = 'm'.repeat(120);
      const result = NeuronViewHelper.truncateNeuronName(long);
      expect(result.length).assertEqual(103);
      expect(result.substring(100)).assertEqual('...');
    });
  });
}

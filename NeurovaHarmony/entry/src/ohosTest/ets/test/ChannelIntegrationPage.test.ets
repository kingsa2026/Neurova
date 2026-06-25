// ChannelIntegrationPage 渠道集成页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：ChannelIntegrationViewHelper 视图模型纯函数行为契约。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对 ChannelIntegrationPage 导出的 ChannelIntegrationViewHelper
//       静态方法进行验证，覆盖页面 getStatusColor / getStatusIcon / getStatusLabel /
//       getCapabilitiesText / truncateName 的核心视图逻辑。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { ChannelIntegrationViewHelper } from '../../../../main/ets/pages/ChannelIntegrationPage';
import { IntegrationStatus } from '../../../../main/ets/libs/types';

export default function channelIntegrationPageTest() {
  describe('ChannelIntegrationPage', () => {
    // ========== 切片1: getStatusColor - connected → status_success ==========

    it('status_color_connected_returns_status_success', 0, () => {
      expect(ChannelIntegrationViewHelper.getStatusColor('connected' as IntegrationStatus))
        .assertEqual('status_success');
    });

    // ========== 切片2: getStatusColor - disconnected → text_secondary ==========

    it('status_color_disconnected_returns_text_secondary', 0, () => {
      expect(ChannelIntegrationViewHelper.getStatusColor('disconnected' as IntegrationStatus))
        .assertEqual('text_secondary');
    });

    // ========== 切片3: getStatusColor - error → status_error ==========

    it('status_color_error_returns_status_error', 0, () => {
      expect(ChannelIntegrationViewHelper.getStatusColor('error' as IntegrationStatus))
        .assertEqual('status_error');
    });

    // ========== 切片4: getStatusColor - syncing → status_warning ==========

    it('status_color_syncing_returns_status_warning', 0, () => {
      expect(ChannelIntegrationViewHelper.getStatusColor('syncing' as IntegrationStatus))
        .assertEqual('status_warning');
    });

    // ========== 切片5: getStatusIcon - connected → ✅ ==========

    it('status_icon_connected_returns_check_emoji', 0, () => {
      expect(ChannelIntegrationViewHelper.getStatusIcon('connected' as IntegrationStatus))
        .assertEqual('✅');
    });

    // ========== 切片6: getStatusIcon - disconnected → ⚪ ==========

    it('status_icon_disconnected_returns_circle_emoji', 0, () => {
      expect(ChannelIntegrationViewHelper.getStatusIcon('disconnected' as IntegrationStatus))
        .assertEqual('⚪');
    });

    // ========== 切片7: getStatusIcon - error → ❌ ==========

    it('status_icon_error_returns_cross_emoji', 0, () => {
      expect(ChannelIntegrationViewHelper.getStatusIcon('error' as IntegrationStatus))
        .assertEqual('❌');
    });

    // ========== 切片8: getStatusIcon - syncing → 🔄 ==========

    it('status_icon_syncing_returns_refresh_emoji', 0, () => {
      expect(ChannelIntegrationViewHelper.getStatusIcon('syncing' as IntegrationStatus))
        .assertEqual('🔄');
    });

    // ========== 切片9: getStatusLabel - connected → 已连接 ==========

    it('status_label_connected_returns_connected_text', 0, () => {
      expect(ChannelIntegrationViewHelper.getStatusLabel('connected' as IntegrationStatus))
        .assertEqual('已连接');
    });

    // ========== 切片10: getStatusLabel - disconnected → 未连接 ==========

    it('status_label_disconnected_returns_disconnected_text', 0, () => {
      expect(ChannelIntegrationViewHelper.getStatusLabel('disconnected' as IntegrationStatus))
        .assertEqual('未连接');
    });

    // ========== 切片11: getStatusLabel - error → 错误 ==========

    it('status_label_error_returns_error_text', 0, () => {
      expect(ChannelIntegrationViewHelper.getStatusLabel('error' as IntegrationStatus))
        .assertEqual('错误');
    });

    // ========== 切片12: getStatusLabel - syncing → 同步中 ==========

    it('status_label_syncing_returns_syncing_text', 0, () => {
      expect(ChannelIntegrationViewHelper.getStatusLabel('syncing' as IntegrationStatus))
        .assertEqual('同步中');
    });

    // ========== 切片13: getCapabilitiesText - 空数组 → 无 ==========

    it('capabilities_text_empty_returns_none', 0, () => {
      expect(ChannelIntegrationViewHelper.getCapabilitiesText([])).assertEqual('无');
    });

    // ========== 切片14: getCapabilitiesText - 单个能力 → 原值 ==========

    it('capabilities_text_single_returns_value', 0, () => {
      expect(ChannelIntegrationViewHelper.getCapabilitiesText(['messaging']))
        .assertEqual('messaging');
    });

    // ========== 切片15: getCapabilitiesText - 多个能力 → 顿号分隔 ==========

    it('capabilities_text_multiple_returns_joined', 0, () => {
      const caps = ['messaging', 'file', 'audit'];
      expect(ChannelIntegrationViewHelper.getCapabilitiesText(caps))
        .assertEqual('messaging、file、audit');
    });

    // ========== 切片16: truncateName - 短名称原样返回 ==========

    it('truncate_name_short_returns_original', 0, () => {
      expect(ChannelIntegrationViewHelper.truncateName('飞书', 16)).assertEqual('飞书');
    });

    // ========== 切片17: truncateName - 等于最大长度原样返回 ==========

    it('truncate_name_equal_length_returns_original', 0, () => {
      const name = 'abcdefghijklmnop'; // 16 字符
      expect(ChannelIntegrationViewHelper.truncateName(name, 16)).assertEqual(name);
    });

    // ========== 切片18: truncateName - 超长截断加省略号 ==========

    it('truncate_name_over_max_returns_ellipsis', 0, () => {
      const name = '这是一个非常长的渠道名称需要被截断处理一下';
      const result = ChannelIntegrationViewHelper.truncateName(name, 16);
      expect(result.length).assertEqual(19); // 16 + '...'
      expect(result.substring(16)).assertEqual('...');
    });

    // ========== 切片19: truncateName - 默认 maxLen 16 ==========

    it('truncate_name_default_max_len_16', 0, () => {
      const name = 'a'.repeat(20);
      const result = ChannelIntegrationViewHelper.truncateName(name);
      expect(result.length).assertEqual(19);
      expect(result.substring(16)).assertEqual('...');
    });
  });
}

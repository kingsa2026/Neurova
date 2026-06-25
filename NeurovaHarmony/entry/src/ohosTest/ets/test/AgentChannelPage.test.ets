// AgentChannelPage 渠道管理页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：ChannelViewHelper 视图模型纯函数行为契约。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对 AgentChannelPage 导出的 ChannelViewHelper 视图模型层
//       （渠道类型图标映射 / 渠道类型显示名映射 / 状态颜色映射）进行验证，
//       覆盖页面渲染所需的全部纯函数。视图模型刻意设计为无 UI 依赖的纯函数，
//       返回颜色 token 名（如 'success'）而非已解析颜色值，便于测试与主题切换。
//
// TDD 切片执行顺序（每片：RED 写测试 → GREEN 写实现 → 重构）：
//   切片 1-9  ：getTypeIcon（feishu/dingtalk/telegram/discord/wechat/webhook/api/email/unknown）
//   切片 10-11：getTypeLabel（feishu/dingtalk）
//   切片 12-15：getStatusColor（connected/disconnected/error/disabled）
import { describe, it, expect } from '@ohos/hypium';
import { ChannelViewHelper } from '../../../../main/ets/pages/AgentChannelPage';
import { ChannelType, ChannelStatus } from '../../../../main/ets/libs/types';

export default function agentChannelPageTest() {
  describe('AgentChannelPage', () => {
    // ========== 切片 1: type_icon_feishu_returns_bird ==========
    // RED:   写测试，ChannelViewHelper.getTypeIcon 尚未实现 → 失败
    // GREEN: 实现 getTypeIcon，feishu 分支返回 '🐦'

    it('type_icon_feishu_returns_bird', 0, () => {
      const icon = ChannelViewHelper.getTypeIcon('feishu' as ChannelType);
      expect(icon).assertEqual('🐦');
    });

    // ========== 切片 2: type_icon_dingtalk_returns_chat ==========
    // RED:   写测试，dingtalk 分支未覆盖 → 失败
    // GREEN: 扩展 dingtalk 分支返回 '💬'

    it('type_icon_dingtalk_returns_chat', 0, () => {
      const icon = ChannelViewHelper.getTypeIcon('dingtalk' as ChannelType);
      expect(icon).assertEqual('💬');
    });

    // ========== 切片 3: type_icon_telegram_returns_plane ==========
    // RED:   写测试，telegram 分支未覆盖 → 失败
    // GREEN: 扩展 telegram 分支返回 '✈️'

    it('type_icon_telegram_returns_plane', 0, () => {
      const icon = ChannelViewHelper.getTypeIcon('telegram' as ChannelType);
      expect(icon).assertEqual('✈️');
    });

    // ========== 切片 4: type_icon_discord_returns_game ==========
    // RED:   写测试，discord 分支未覆盖 → 失败
    // GREEN: 扩展 discord 分支返回 '🎮'

    it('type_icon_discord_returns_game', 0, () => {
      const icon = ChannelViewHelper.getTypeIcon('discord' as ChannelType);
      expect(icon).assertEqual('🎮');
    });

    // ========== 切片 5: type_icon_wechat_returns_heart ==========
    // RED:   写测试，wechat 分支未覆盖 → 失败
    // GREEN: 扩展 wechat 分支返回 '💚'

    it('type_icon_wechat_returns_heart', 0, () => {
      const icon = ChannelViewHelper.getTypeIcon('wechat' as ChannelType);
      expect(icon).assertEqual('💚');
    });

    // ========== 切片 6: type_icon_webhook_returns_link ==========
    // RED:   写测试，webhook 分支未覆盖 → 失败
    // GREEN: 扩展 webhook 分支返回 '🔗'

    it('type_icon_webhook_returns_link', 0, () => {
      const icon = ChannelViewHelper.getTypeIcon('webhook' as ChannelType);
      expect(icon).assertEqual('🔗');
    });

    // ========== 切片 7: type_icon_api_returns_gear ==========
    // RED:   写测试，api 分支未覆盖 → 失败
    // GREEN: 扩展 api 分支返回 '⚙️'

    it('type_icon_api_returns_gear', 0, () => {
      const icon = ChannelViewHelper.getTypeIcon('api' as ChannelType);
      expect(icon).assertEqual('⚙️');
    });

    // ========== 切片 8: type_icon_email_returns_mail ==========
    // RED:   写测试，email 分支未覆盖 → 失败
    // GREEN: 扩展 email 分支返回 '📧'

    it('type_icon_email_returns_mail', 0, () => {
      const icon = ChannelViewHelper.getTypeIcon('email' as ChannelType);
      expect(icon).assertEqual('📧');
    });

    // ========== 切片 9: type_icon_unknown_returns_default ==========
    // RED:   写测试，未知类型未回退 → 失败
    // GREEN: 扩展默认分支返回 '❓'

    it('type_icon_unknown_returns_default', 0, () => {
      // 未知类型应回退到默认 ❓ 图标
      const icon = ChannelViewHelper.getTypeIcon('unknown_type' as ChannelType);
      expect(icon).assertEqual('❓');
    });

    // ========== 切片 10: type_label_feishu_returns_chinese_name ==========
    // RED:   写测试，ChannelViewHelper.getTypeLabel 尚未实现 → 失败
    // GREEN: 实现 getTypeLabel，feishu 分支返回 '飞书'

    it('type_label_feishu_returns_chinese_name', 0, () => {
      const label = ChannelViewHelper.getTypeLabel('feishu' as ChannelType);
      expect(label).assertEqual('飞书');
    });

    // ========== 切片 11: type_label_dingtalk_returns_chinese_name ==========
    // RED:   写测试，dingtalk 分支未覆盖 → 失败
    // GREEN: 扩展 dingtalk 分支返回 '钉钉'

    it('type_label_dingtalk_returns_chinese_name', 0, () => {
      const label = ChannelViewHelper.getTypeLabel('dingtalk' as ChannelType);
      expect(label).assertEqual('钉钉');
    });

    // ========== 切片 12: status_color_connected_returns_success ==========
    // RED:   写测试，ChannelViewHelper.getStatusColor 尚未实现 → 失败
    // GREEN: 实现 getStatusColor，connected 分支返回 'success'

    it('status_color_connected_returns_success', 0, () => {
      const token = ChannelViewHelper.getStatusColor('connected' as ChannelStatus);
      expect(token).assertEqual('success');
    });

    // ========== 切片 13: status_color_disconnected_returns_disabled ==========
    // RED:   写测试，disconnected 分支未覆盖 → 失败
    // GREEN: 扩展 disconnected 分支返回 'text_disabled'

    it('status_color_disconnected_returns_disabled', 0, () => {
      const token = ChannelViewHelper.getStatusColor('disconnected' as ChannelStatus);
      expect(token).assertEqual('text_disabled');
    });

    // ========== 切片 14: status_color_error_returns_error ==========
    // RED:   写测试，error 分支未覆盖 → 失败
    // GREEN: 扩展 error 分支返回 'error'

    it('status_color_error_returns_error', 0, () => {
      const token = ChannelViewHelper.getStatusColor('error' as ChannelStatus);
      expect(token).assertEqual('error');
    });

    // ========== 切片 15: status_color_disabled_returns_warning ==========
    // RED:   写测试，disabled 分支未覆盖 → 失败
    // GREEN: 扩展 disabled 分支返回 'warning'

    it('status_color_disabled_returns_warning', 0, () => {
      const token = ChannelViewHelper.getStatusColor('disabled' as ChannelStatus);
      expect(token).assertEqual('warning');
    });
  });
}

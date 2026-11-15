// MarketplacePage 应用市场页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：MarketplaceViewHelper 视图模型行为（分类颜色/图标/文案、商品类型文案、
//           价格格式化、下载数格式化、评分格式化）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 MarketplacePage.ets 导出的
//       MarketplaceViewHelper 静态方法进行验证。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { MarketplaceViewHelper } from '../../../../main/ets/pages/MarketplacePage';
import { MarketplaceCategory, MarketplaceItemType } from '../../../../main/ets/libs/types';

export default function marketplacePageTest() {
  describe('MarketplacePage', () => {
    // ========== 切片1: getCategoryColor - agent → primary ==========

    it('category_color_agent_returns_primary', 0, () => {
      expect(MarketplaceViewHelper.getCategoryColor('agent')).assertEqual('primary');
    });

    // ========== 切片2: getCategoryColor - skill → info ==========

    it('category_color_skill_returns_info', 0, () => {
      expect(MarketplaceViewHelper.getCategoryColor('skill')).assertEqual('info');
    });

    // ========== 切片3: getCategoryColor - template → success ==========

    it('category_color_template_returns_success', 0, () => {
      expect(MarketplaceViewHelper.getCategoryColor('template')).assertEqual('success');
    });

    // ========== 切片4: getCategoryColor - plugin → warning ==========

    it('category_color_plugin_returns_warning', 0, () => {
      expect(MarketplaceViewHelper.getCategoryColor('plugin')).assertEqual('warning');
    });

    // ========== 切片5: getCategoryColor - workflow → secondary ==========

    it('category_color_workflow_returns_secondary', 0, () => {
      expect(MarketplaceViewHelper.getCategoryColor('workflow')).assertEqual('secondary');
    });

    // ========== 切片6: getCategoryIcon - agent → 🤖 ==========

    it('category_icon_agent_returns_robot', 0, () => {
      expect(MarketplaceViewHelper.getCategoryIcon('agent')).assertEqual('🤖');
    });

    // ========== 切片7: getCategoryIcon - skill → ⚡ ==========

    it('category_icon_skill_returns_bolt', 0, () => {
      expect(MarketplaceViewHelper.getCategoryIcon('skill')).assertEqual('⚡');
    });

    // ========== 切片8: getCategoryIcon - template → 📋 ==========

    it('category_icon_template_returns_clipboard', 0, () => {
      expect(MarketplaceViewHelper.getCategoryIcon('template')).assertEqual('📋');
    });

    // ========== 切片9: getCategoryIcon - plugin → 🔌 ==========

    it('category_icon_plugin_returns_plug', 0, () => {
      expect(MarketplaceViewHelper.getCategoryIcon('plugin')).assertEqual('🔌');
    });

    // ========== 切片10: getCategoryIcon - workflow → 🔄 ==========

    it('category_icon_workflow_returns_workflow', 0, () => {
      expect(MarketplaceViewHelper.getCategoryIcon('workflow')).assertEqual('🔄');
    });

    // ========== 切片11: getCategoryLabel - agent → 智能体 ==========

    it('category_label_agent_returns_agent', 0, () => {
      expect(MarketplaceViewHelper.getCategoryLabel('agent')).assertEqual('智能体');
    });

    // ========== 切片12: getCategoryLabel - skill → 技能 ==========

    it('category_label_skill_returns_skill', 0, () => {
      expect(MarketplaceViewHelper.getCategoryLabel('skill')).assertEqual('技能');
    });

    // ========== 切片13: getCategoryLabel - template → 模板 ==========

    it('category_label_template_returns_template', 0, () => {
      expect(MarketplaceViewHelper.getCategoryLabel('template')).assertEqual('模板');
    });

    // ========== 切片14: getCategoryLabel - plugin → 插件 ==========

    it('category_label_plugin_returns_plugin', 0, () => {
      expect(MarketplaceViewHelper.getCategoryLabel('plugin')).assertEqual('插件');
    });

    // ========== 切片15: getCategoryLabel - workflow → 工作流 ==========

    it('category_label_workflow_returns_workflow', 0, () => {
      expect(MarketplaceViewHelper.getCategoryLabel('workflow')).assertEqual('工作流');
    });

    // ========== 切片16: getItemTypeLabel - free → 免费 ==========

    it('item_type_label_free_returns_free', 0, () => {
      expect(MarketplaceViewHelper.getItemTypeLabel('free')).assertEqual('免费');
    });

    // ========== 切片17: getItemTypeLabel - paid → 付费 ==========

    it('item_type_label_paid_returns_paid', 0, () => {
      expect(MarketplaceViewHelper.getItemTypeLabel('paid')).assertEqual('付费');
    });

    // ========== 切片18: getItemTypeLabel - subscription → 订阅 ==========

    it('item_type_label_subscription_returns_subscription', 0, () => {
      expect(MarketplaceViewHelper.getItemTypeLabel('subscription')).assertEqual('订阅');
    });

    // ========== 切片19: formatPrice - free → "免费" ==========

    it('format_price_free_returns_free', 0, () => {
      expect(MarketplaceViewHelper.formatPrice(0, 'CNY', 'free')).assertEqual('免费');
    });

    // ========== 切片20: formatPrice - paid → "¥99" ==========

    it('format_price_paid_returns_yuan', 0, () => {
      expect(MarketplaceViewHelper.formatPrice(99, 'CNY', 'paid')).assertEqual('¥99');
    });

    // ========== 切片21: formatPrice - subscription → "¥10/月" ==========

    it('format_price_subscription_returns_per_month', 0, () => {
      expect(MarketplaceViewHelper.formatPrice(10, 'CNY', 'subscription')).assertEqual('¥10/月');
    });

    // ========== 切片22: formatDownloadCount - 0 → "未下载" ==========

    it('format_download_count_zero_returns_none', 0, () => {
      expect(MarketplaceViewHelper.formatDownloadCount(0)).assertEqual('未下载');
    });

    // ========== 切片23: formatDownloadCount - 50 → "50次下载" ==========

    it('format_download_count_normal_returns_count', 0, () => {
      expect(MarketplaceViewHelper.formatDownloadCount(50)).assertEqual('50次下载');
    });

    // ========== 切片24: formatDownloadCount - 1000 → "999+次下载" ==========

    it('format_download_count_thousands_returns_999plus', 0, () => {
      expect(MarketplaceViewHelper.formatDownloadCount(1000)).assertEqual('999+次下载');
    });

    // ========== 切片25: formatRating - 1 → "★" ==========

    it('format_rating_one_returns_one_star', 0, () => {
      expect(MarketplaceViewHelper.formatRating(1)).assertEqual('★');
    });

    // ========== 切片26: formatRating - 3 → "★★★" ==========

    it('format_rating_three_returns_three_stars', 0, () => {
      expect(MarketplaceViewHelper.formatRating(3)).assertEqual('★★★');
    });

    // ========== 切片27: formatRating - 5 → "★★★★★" ==========

    it('format_rating_five_returns_five_stars', 0, () => {
      expect(MarketplaceViewHelper.formatRating(5)).assertEqual('★★★★★');
    });

    // ========== 切片28: truncateDescription - 未超长 → 原样返回 ==========

    it('truncate_description_short_returns_original', 0, () => {
      expect(MarketplaceViewHelper.truncateDescription('短描述', 10)).assertEqual('短描述');
    });

    // ========== 切片29: truncateDescription - 超长 → 截断 + "..." ==========

    it('truncate_description_long_returns_truncated', 0, () => {
      const desc = '这是一个非常长的市场商品描述文本用于测试截断功能是否正常工作';
      const result = MarketplaceViewHelper.truncateDescription(desc, 10);
      expect(result).assertEqual('这是一个非常长的市场...');
    });
  });
}

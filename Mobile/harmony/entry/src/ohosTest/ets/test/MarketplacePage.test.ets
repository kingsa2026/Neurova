// MarketplacePage 技能市场页单元测试 - R6 契约切换
//
// 测试范围：MarketplaceViewHelper 视图模型行为（来源徽章颜色/文案（开放集合）、
//           分类图标、下载数格式化、评分格式化、描述截断）。
// 契约：后端 marketplace.py 是技能市场（skill_id/author/version/downloads/
//       installed/source），无 itemType 价型维度；source/category 开放集合，
//       未知值兜默认，不抛错。
import { describe, it, expect } from '@ohos/hypium';
import { MarketplaceViewHelper } from '../../../main/ets/pages/MarketplacePage';

export default function marketplacePageTest() {
  describe('MarketplacePage', () => {
    // ========== 切片1: getSourceColor ==========

    it('source_color_local_returns_primary', 0, () => {
      expect(MarketplaceViewHelper.getSourceColor('local')).assertEqual('primary');
    });

    it('source_color_aliyun_returns_secondary', 0, () => {
      expect(MarketplaceViewHelper.getSourceColor('aliyun')).assertEqual('secondary');
    });

    it('source_color_unknown_defaults_to_info', 0, () => {
      expect(MarketplaceViewHelper.getSourceColor('future_market')).assertEqual('info');
    });

    // ========== 切片2: getSourceLabel ==========

    it('source_label_local', 0, () => {
      expect(MarketplaceViewHelper.getSourceLabel('local')).assertEqual('官方上架');
    });

    it('source_label_unknown_returns_raw', 0, () => {
      expect(MarketplaceViewHelper.getSourceLabel('future_market')).assertEqual('future_market');
    });

    // ========== 切片3: getCategoryIcon（开放集合兜默认） ==========

    it('category_icon_general_returns_puzzle', 0, () => {
      expect(MarketplaceViewHelper.getCategoryIcon('general')).assertEqual('🧩');
    });

    it('category_icon_unknown_defaults_to_puzzle', 0, () => {
      expect(MarketplaceViewHelper.getCategoryIcon('new_domain')).assertEqual('🧩');
    });

    // ========== 切片4: formatDownloadCount ==========

    it('format_downloads_zero_returns_none', 0, () => {
      expect(MarketplaceViewHelper.formatDownloadCount(0)).assertEqual('暂无下载');
    });

    it('format_downloads_small_returns_raw', 0, () => {
      expect(MarketplaceViewHelper.formatDownloadCount(42)).assertEqual('42 次下载');
    });

    it('format_downloads_thousands_returns_K', 0, () => {
      expect(MarketplaceViewHelper.formatDownloadCount(2048)).assertEqual('2.0K 次下载');
    });

    it('format_downloads_millions_returns_M', 0, () => {
      expect(MarketplaceViewHelper.formatDownloadCount(2097152)).assertEqual('2.0M 次下载');
    });

    // ========== 切片5: formatRating / formatRatingText ==========

    it('format_rating_four_returns_four_stars', 0, () => {
      expect(MarketplaceViewHelper.formatRating(4.0)).assertEqual('★★★★');
    });

    it('format_rating_fraction_floors', 0, () => {
      expect(MarketplaceViewHelper.formatRating(4.7)).assertEqual('★★★★');
    });

    it('format_rating_zero_returns_empty', 0, () => {
      expect(MarketplaceViewHelper.formatRating(0)).assertEqual('');
    });

    it('format_rating_text_zero_returns_no_rating', 0, () => {
      expect(MarketplaceViewHelper.formatRatingText(0)).assertEqual('暂无评分');
    });

    it('format_rating_text_value_returns_stars_and_number', 0, () => {
      expect(MarketplaceViewHelper.formatRatingText(4.5)).assertEqual('★★★★ 4.5');
    });

    // ========== 切片6: truncateDescription ==========

    it('truncate_short_desc_returns_raw', 0, () => {
      expect(MarketplaceViewHelper.truncateDescription('短描述', 60)).assertEqual('短描述');
    });

    it('truncate_long_desc_appends_ellipsis', 0, () => {
      const long = 'd'.repeat(70);
      expect(MarketplaceViewHelper.truncateDescription(long, 60)).assertEqual('d'.repeat(60) + '...');
    });
  });
}

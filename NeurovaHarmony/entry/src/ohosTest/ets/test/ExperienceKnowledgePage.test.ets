// ExperienceKnowledgePage 经验知识页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：ExperienceKnowledgeViewHelper 视图模型行为（category 颜色映射、
//           category 图标映射、importance 格式化、激活次数格式化、内容截断）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 ExperienceKnowledgePage.ets 导出的 ExperienceKnowledgeViewHelper
//       静态方法进行验证，覆盖页面 getCategoryColor / getCategoryIcon / formatImportance /
//       formatActivationCount / truncateContent 的核心视图逻辑。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { ExperienceKnowledgeViewHelper } from '../../../../main/ets/pages/ExperienceKnowledgePage';

export default function experienceKnowledgePageTest() {
  describe('ExperienceKnowledgePage', () => {
    // ========== 切片1: getCategoryColor - 工作场景 → primary ==========

    it('category_color_work_returns_primary', 0, () => {
      expect(ExperienceKnowledgeViewHelper.getCategoryColor('工作场景')).assertEqual('primary');
    });

    // ========== 切片2: getCategoryColor - 技术细节 → info ==========

    it('category_color_tech_returns_info', 0, () => {
      expect(ExperienceKnowledgeViewHelper.getCategoryColor('技术细节')).assertEqual('info');
    });

    // ========== 切片3: getCategoryColor - 用户偏好 → success ==========

    it('category_color_preference_returns_success', 0, () => {
      expect(ExperienceKnowledgeViewHelper.getCategoryColor('用户偏好')).assertEqual('success');
    });

    // ========== 切片4: getCategoryColor - 失败教训 → warning ==========

    it('category_color_failure_returns_warning', 0, () => {
      expect(ExperienceKnowledgeViewHelper.getCategoryColor('失败教训')).assertEqual('warning');
    });

    // ========== 切片5: getCategoryColor - 未知类别 → text_disabled ==========

    it('category_color_unknown_returns_text_disabled', 0, () => {
      expect(ExperienceKnowledgeViewHelper.getCategoryColor('其他')).assertEqual('text_disabled');
    });

    // ========== 切片6: getCategoryIcon - 工作场景 → 💼 ==========

    it('category_icon_work_returns_briefcase', 0, () => {
      expect(ExperienceKnowledgeViewHelper.getCategoryIcon('工作场景')).assertEqual('💼');
    });

    // ========== 切片7: getCategoryIcon - 技术细节 → 🔧 ==========

    it('category_icon_tech_returns_wrench', 0, () => {
      expect(ExperienceKnowledgeViewHelper.getCategoryIcon('技术细节')).assertEqual('🔧');
    });

    // ========== 切片8: getCategoryIcon - 用户偏好 → ❤️ ==========

    it('category_icon_preference_returns_heart', 0, () => {
      expect(ExperienceKnowledgeViewHelper.getCategoryIcon('用户偏好')).assertEqual('❤️');
    });

    // ========== 切片9: getCategoryIcon - 失败教训 → ⚠️ ==========

    it('category_icon_failure_returns_warning', 0, () => {
      expect(ExperienceKnowledgeViewHelper.getCategoryIcon('失败教训')).assertEqual('⚠️');
    });

    // ========== 切片10: getCategoryIcon - 未知类别 → 📄 ==========

    it('category_icon_unknown_returns_default', 0, () => {
      expect(ExperienceKnowledgeViewHelper.getCategoryIcon('未知')).assertEqual('📄');
    });

    // ========== 切片11: formatImportance - 0.5 → "50%" ==========

    it('format_importance_half_returns_50_percent', 0, () => {
      expect(ExperienceKnowledgeViewHelper.formatImportance(0.5)).assertEqual('50%');
    });

    // ========== 切片12: formatImportance - 1 → "100%" ==========

    it('format_importance_full_returns_100_percent', 0, () => {
      expect(ExperienceKnowledgeViewHelper.formatImportance(1)).assertEqual('100%');
    });

    // ========== 切片13: formatImportance - 0 → "0%" ==========

    it('format_importance_zero_returns_0_percent', 0, () => {
      expect(ExperienceKnowledgeViewHelper.formatImportance(0)).assertEqual('0%');
    });

    // ========== 切片14: formatActivationCount - 0 → "未激活" ==========

    it('format_activation_count_zero_returns_inactive', 0, () => {
      expect(ExperienceKnowledgeViewHelper.formatActivationCount(0)).assertEqual('未激活');
    });

    // ========== 切片15: formatActivationCount - n → "激活 n 次" ==========

    it('format_activation_count_n_returns_activated', 0, () => {
      expect(ExperienceKnowledgeViewHelper.formatActivationCount(5)).assertEqual('激活 5 次');
      expect(ExperienceKnowledgeViewHelper.formatActivationCount(1)).assertEqual('激活 1 次');
    });

    // ========== 切片16: truncateContent - 默认 maxLen=100，超长截断加省略号 ==========

    it('truncate_content_default_max_len_100', 0, () => {
      const long = 'a'.repeat(150);
      const result = ExperienceKnowledgeViewHelper.truncateContent(long);
      expect(result.length).assertEqual(103);
      expect(result.substring(100)).assertEqual('...');
    });

    // ========== 切片17: truncateContent - 未超长原样返回 ==========

    it('truncate_content_short_returns_original', 0, () => {
      const short = '短内容';
      expect(ExperienceKnowledgeViewHelper.truncateContent(short)).assertEqual('短内容');
    });

    // ========== 切片18: truncateContent - 自定义 maxLen ==========

    it('truncate_content_custom_max_len', 0, () => {
      const text = 'abcdefghij';
      const result = ExperienceKnowledgeViewHelper.truncateContent(text, 5);
      expect(result).assertEqual('abcde...');
    });
  });
}

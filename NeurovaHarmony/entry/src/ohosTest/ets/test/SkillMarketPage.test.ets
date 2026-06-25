// SkillMarketPage 技能市场页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：SkillMarketViewHelper 视图模型行为（分类颜色映射、分类图标、分类文案、
//           描述截断、评分格式化、安装数格式化）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 SkillMarketPage.ets 导出的 SkillMarketViewHelper 静态方法进行验证，
//       覆盖页面 getCategoryColor / getCategoryIcon / getCategoryLabel / truncateDescription /
//       formatRating / formatInstalls 的核心视图逻辑。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { SkillMarketViewHelper } from '../../../../main/ets/pages/SkillMarketPage';

export default function skillMarketPageTest() {
  describe('SkillMarketPage', () => {
    // ========== 切片1: getCategoryColor - AI → primary ==========

    it('category_color_AI_returns_primary', 0, () => {
      expect(SkillMarketViewHelper.getCategoryColor('AI')).assertEqual('primary');
    });

    // ========== 切片2: getCategoryColor - 工具 → info ==========

    it('category_color_tool_returns_info', 0, () => {
      expect(SkillMarketViewHelper.getCategoryColor('工具')).assertEqual('info');
    });

    // ========== 切片3: getCategoryColor - 集成 → warning ==========

    it('category_color_integration_returns_warning', 0, () => {
      expect(SkillMarketViewHelper.getCategoryColor('集成')).assertEqual('warning');
    });

    // ========== 切片4: getCategoryColor - 数据处理 → success ==========

    it('category_color_data_returns_success', 0, () => {
      expect(SkillMarketViewHelper.getCategoryColor('数据处理')).assertEqual('success');
    });

    // ========== 切片5: getCategoryColor - 其他 → text_secondary ==========

    it('category_color_other_returns_text_secondary', 0, () => {
      expect(SkillMarketViewHelper.getCategoryColor('其他')).assertEqual('text_secondary');
    });

    // ========== 切片6: getCategoryIcon - AI → 🤖 ==========

    it('category_icon_AI_returns_robot', 0, () => {
      expect(SkillMarketViewHelper.getCategoryIcon('AI')).assertEqual('🤖');
    });

    // ========== 切片7: getCategoryIcon - 工具 → 🔧 ==========

    it('category_icon_tool_returns_wrench', 0, () => {
      expect(SkillMarketViewHelper.getCategoryIcon('工具')).assertEqual('🔧');
    });

    // ========== 切片8: getCategoryIcon - 集成 → 🔌 ==========

    it('category_icon_integration_returns_plug', 0, () => {
      expect(SkillMarketViewHelper.getCategoryIcon('集成')).assertEqual('🔌');
    });

    // ========== 切片9: getCategoryIcon - 数据处理 → 📊 ==========

    it('category_icon_data_returns_chart', 0, () => {
      expect(SkillMarketViewHelper.getCategoryIcon('数据处理')).assertEqual('📊');
    });

    // ========== 切片10: getCategoryIcon - 其他 → 📦 ==========

    it('category_icon_other_returns_box', 0, () => {
      expect(SkillMarketViewHelper.getCategoryIcon('其他')).assertEqual('📦');
    });

    // ========== 切片11: getCategoryLabel - AI → AI ==========

    it('category_label_AI_returns_AI', 0, () => {
      expect(SkillMarketViewHelper.getCategoryLabel('AI')).assertEqual('AI');
    });

    // ========== 切片12: getCategoryLabel - 未知分类 → 其他 ==========

    it('category_label_unknown_returns_other', 0, () => {
      expect(SkillMarketViewHelper.getCategoryLabel('未知分类')).assertEqual('其他');
    });

    // ========== 切片13: truncateDescription - 超长截断加省略号 ==========

    it('truncate_description_over_max_returns_ellipsis', 0, () => {
      const long = 'a'.repeat(200);
      const result = SkillMarketViewHelper.truncateDescription(long);
      expect(result.length).assertEqual(123);
      expect(result.substring(120)).assertEqual('...');
    });

    // ========== 切片14: truncateDescription - 默认 maxLen=120 ==========

    it('truncate_description_default_maxLen_120', 0, () => {
      const s = 'a'.repeat(120);
      const result = SkillMarketViewHelper.truncateDescription(s);
      expect(result).assertEqual(s);
    });

    // ========== 切片15: truncateDescription - 自定义 maxLen ==========

    it('truncate_description_custom_maxLen', 0, () => {
      const s = 'abcdefg';
      const result = SkillMarketViewHelper.truncateDescription(s, 5);
      expect(result).assertEqual('abcde...');
    });

    // ========== 切片16: formatRating - 4.5 → "★★★★☆ 4.5" ==========

    it('format_rating_normal_returns_stars', 0, () => {
      expect(SkillMarketViewHelper.formatRating(4.5)).assertEqual('★★★★☆ 4.5');
    });

    // ========== 切片17: formatRating - 0 → "暂无评分" ==========

    it('format_rating_zero_returns_no_rating', 0, () => {
      expect(SkillMarketViewHelper.formatRating(0)).assertEqual('暂无评分');
    });

    // ========== 切片18: formatInstalls - 0 → "无安装" ==========

    it('format_installs_zero_returns_no_installs', 0, () => {
      expect(SkillMarketViewHelper.formatInstalls(0)).assertEqual('无安装');
    });

    // ========== 切片19: formatInstalls - 1024 → "1.0K 安装" ==========

    it('format_installs_thousands_returns_K', 0, () => {
      expect(SkillMarketViewHelper.formatInstalls(1024)).assertEqual('1.0K 安装');
    });

    // ========== 切片20: formatInstalls - 1048576 → "1.0M 安装" ==========

    it('format_installs_millions_returns_M', 0, () => {
      expect(SkillMarketViewHelper.formatInstalls(1048576)).assertEqual('1.0M 安装');
    });
  });
}

// SkillPoolPage 技能池页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：SkillPoolViewHelper 视图模型行为（技能状态颜色映射、状态图标、状态文案、
//           评分格式化、安装数格式化、标签格式化）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 SkillPoolPage.ets 导出的 SkillPoolViewHelper 静态方法进行验证，
//       覆盖页面 getStatusColor / getStatusIcon / getStatusLabel / formatRating /
//       formatInstalls / formatTags 的核心视图逻辑。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { SkillPoolViewHelper } from '../../../../main/ets/pages/SkillPoolPage';
import { SkillStatus } from '../../../../main/ets/libs/types';

export default function skillPoolPageTest() {
  describe('SkillPoolPage', () => {
    // ========== 切片1: getStatusColor - draft → warning ==========

    it('status_color_draft_returns_warning', 0, () => {
      expect(SkillPoolViewHelper.getStatusColor('draft')).assertEqual('warning');
    });

    // ========== 切片2: getStatusColor - published → success ==========

    it('status_color_published_returns_success', 0, () => {
      expect(SkillPoolViewHelper.getStatusColor('published')).assertEqual('success');
    });

    // ========== 切片3: getStatusColor - deprecated → text_disabled ==========

    it('status_color_deprecated_returns_text_disabled', 0, () => {
      expect(SkillPoolViewHelper.getStatusColor('deprecated')).assertEqual('text_disabled');
    });

    // ========== 切片4: getStatusIcon - draft → 📝 ==========

    it('status_icon_draft_returns_pencil', 0, () => {
      expect(SkillPoolViewHelper.getStatusIcon('draft')).assertEqual('📝');
    });

    // ========== 切片5: getStatusIcon - published → ✅ ==========

    it('status_icon_published_returns_check', 0, () => {
      expect(SkillPoolViewHelper.getStatusIcon('published')).assertEqual('✅');
    });

    // ========== 切片6: getStatusIcon - deprecated → 🗑️ ==========

    it('status_icon_deprecated_returns_trash', 0, () => {
      expect(SkillPoolViewHelper.getStatusIcon('deprecated')).assertEqual('🗑️');
    });

    // ========== 切片7: getStatusLabel - draft → 草稿 ==========

    it('status_label_draft_returns_draft', 0, () => {
      expect(SkillPoolViewHelper.getStatusLabel('draft')).assertEqual('草稿');
    });

    // ========== 切片8: getStatusLabel - published → 已发布 ==========

    it('status_label_published_returns_published', 0, () => {
      expect(SkillPoolViewHelper.getStatusLabel('published')).assertEqual('已发布');
    });

    // ========== 切片9: getStatusLabel - deprecated → 已弃用 ==========

    it('status_label_deprecated_returns_deprecated', 0, () => {
      expect(SkillPoolViewHelper.getStatusLabel('deprecated')).assertEqual('已弃用');
    });

    // ========== 切片10: formatRating - 4.5 → "★★★★☆ 4.5" ==========

    it('format_rating_normal_returns_stars', 0, () => {
      expect(SkillPoolViewHelper.formatRating(4.5)).assertEqual('★★★★☆ 4.5');
    });

    // ========== 切片11: formatRating - 0 → "暂无评分" ==========

    it('format_rating_zero_returns_no_rating', 0, () => {
      expect(SkillPoolViewHelper.formatRating(0)).assertEqual('暂无评分');
    });

    // ========== 切片12: formatRating - 5.0 → "★★★★★ 5.0" ==========

    it('format_rating_full_returns_five_stars', 0, () => {
      expect(SkillPoolViewHelper.formatRating(5.0)).assertEqual('★★★★★ 5.0');
    });

    // ========== 切片13: formatInstalls - 0 → "无安装" ==========

    it('format_installs_zero_returns_no_installs', 0, () => {
      expect(SkillPoolViewHelper.formatInstalls(0)).assertEqual('无安装');
    });

    // ========== 切片14: formatInstalls - 1024 → "1.0K 安装" ==========

    it('format_installs_thousands_returns_K', 0, () => {
      expect(SkillPoolViewHelper.formatInstalls(1024)).assertEqual('1.0K 安装');
    });

    // ========== 切片15: formatInstalls - 1048576 → "1.0M 安装" ==========

    it('format_installs_millions_returns_M', 0, () => {
      expect(SkillPoolViewHelper.formatInstalls(1048576)).assertEqual('1.0M 安装');
    });

    // ========== 切片16: formatTags - [] → "无标签" ==========

    it('format_tags_empty_returns_no_tags', 0, () => {
      expect(SkillPoolViewHelper.formatTags([])).assertEqual('无标签');
    });

    // ========== 切片17: formatTags - ["a","b"] → "a · b" ==========

    it('format_tags_with_items_returns_joined', 0, () => {
      expect(SkillPoolViewHelper.formatTags(['a', 'b'])).assertEqual('a · b');
    });
  });
}

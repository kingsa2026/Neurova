// ExperienceKnowledgePage 经验知识页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：ExperienceKnowledgeViewHelper 视图模型行为（熟练度格式化、内容截断）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 ExperienceKnowledgePage.ets 导出的 ExperienceKnowledgeViewHelper
//       静态方法进行验证，覆盖页面渲染所需的全部纯函数。
//
// R2 契约对齐（替代旧 legacy 视图用例）：真实方法面只有 formatProficiency /
// truncateContent 两个方法——旧用例覆盖的 category 颜色/图标映射、激活次数
// 格式化已随页面重写退役（无对应主源码方法，运行期必红）；importance 格式化
// 真名为 formatProficiency；truncateContent 真实签名只有单参（无自定义长度）。
// 旧用例按现状退役/改写，不保留必红用例。
import { describe, it, expect } from '@ohos/hypium';
import { ExperienceKnowledgeViewHelper } from '../../../main/ets/pages/ExperienceKnowledgePage';

export default function experienceKnowledgePageTest() {
  describe('ExperienceKnowledgePage', () => {
    // ========== 切片1: formatProficiency - 0.5 → "50%" ==========

    it('format_proficiency_half_returns_50_percent', 0, () => {
      expect(ExperienceKnowledgeViewHelper.formatProficiency(0.5)).assertEqual('50%');
    });

    // ========== 切片2: formatProficiency - 1 → "100%" ==========

    it('format_proficiency_full_returns_100_percent', 0, () => {
      expect(ExperienceKnowledgeViewHelper.formatProficiency(1)).assertEqual('100%');
    });

    // ========== 切片3: formatProficiency - 0 → "0%" ==========

    it('format_proficiency_zero_returns_0_percent', 0, () => {
      expect(ExperienceKnowledgeViewHelper.formatProficiency(0)).assertEqual('0%');
    });

    // ========== 切片4: formatProficiency - null（未测量）→ "0%" ==========

    it('format_proficiency_null_returns_0_percent', 0, () => {
      expect(ExperienceKnowledgeViewHelper.formatProficiency(null)).assertEqual('0%');
    });

    // ========== 切片5: truncateContent - 默认 100 字符截断加省略号 ==========

    it('truncate_content_over_100_truncated_with_ellipsis', 0, () => {
      const long = 'a'.repeat(150);
      const result = ExperienceKnowledgeViewHelper.truncateContent(long);
      expect(result.length).assertEqual(101);
      expect(result.substring(100)).assertEqual('…');
    });

    // ========== 切片6: truncateContent - 未超长原样返回 ==========

    it('truncate_content_short_returns_original', 0, () => {
      const short = '短内容';
      expect(ExperienceKnowledgeViewHelper.truncateContent(short)).assertEqual('短内容');
    });

    // ========== 切片7: truncateContent - 恰好 100 字符不截断 ==========

    it('truncate_content_exactly_100_returns_original', 0, () => {
      const exact = 'b'.repeat(100);
      expect(ExperienceKnowledgeViewHelper.truncateContent(exact)).assertEqual(exact);
    });
  });
}

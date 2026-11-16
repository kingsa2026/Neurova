// CollaborationTemplatePage 协作模板页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：CollaborationTemplateViewHelper 视图模型行为（参与者数量格式化、
//           描述截断）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 CollaborationTemplatePage.ets 导出的
//       CollaborationTemplateViewHelper 静态方法进行验证。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { CollaborationTemplateViewHelper } from '../../../main/ets/pages/CollaborationTemplatePage';

export default function collaborationTemplatePageTest() {
  describe('CollaborationTemplatePage', () => {
    // ========== 切片1: formatParticipantsCount - 0 → "无参与者" ==========

    it('format_participants_count_zero_returns_none', 0, () => {
      expect(CollaborationTemplateViewHelper.formatParticipantsCount(0)).assertEqual('无参与者');
    });

    // ========== 切片2: formatParticipantsCount - 1 → "1 人" ==========

    it('format_participants_count_one_returns_one_person', 0, () => {
      expect(CollaborationTemplateViewHelper.formatParticipantsCount(1)).assertEqual('1 人');
    });

    // ========== 切片3: formatParticipantsCount - 5 → "5 人" ==========

    it('format_participants_count_multi_returns_multi_persons', 0, () => {
      expect(CollaborationTemplateViewHelper.formatParticipantsCount(5)).assertEqual('5 人');
    });

    // ========== 切片4: truncateDescription - 未超长 → 原样返回 ==========

    it('truncate_description_short_returns_original', 0, () => {
      expect(CollaborationTemplateViewHelper.truncateDescription('短描述', 10)).assertEqual('短描述');
    });

    // ========== 切片5: truncateDescription - 超长 → 截断 + "..." ==========

    it('truncate_description_long_returns_truncated', 0, () => {
      const desc = '这是一个非常长的协作模板描述文本，用于测试截断功能是否正常工作';
      const result = CollaborationTemplateViewHelper.truncateDescription(desc, 10);
      expect(result).assertEqual('这是一个非常长的协作...');
    });
  });
}

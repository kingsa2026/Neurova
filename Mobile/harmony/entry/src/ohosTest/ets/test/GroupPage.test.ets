// GroupPage 用户组管理页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：GroupViewHelper 视图模型行为（成员数格式化、描述截断）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 GroupPage.ets 导出的 GroupViewHelper 静态方法进行验证。
//       P1-33 接线真实 API（/v1/groups，GroupInfo 投影）后，视图模型与后端字段
//       对齐：成员数与描述截断保留；角色/权限筛选无后端字段支撑，相关视图函数
//       随 mock 一并退役。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { GroupViewHelper } from '../../../main/ets/pages/GroupPage';

export default function groupPageTest() {
  describe('GroupPage', () => {
    // ========== 切片1: formatMemberCount - 0 → 空组 ==========

    it('member_count_zero_returns_空组', 0, () => {
      expect(GroupViewHelper.formatMemberCount(0)).assertEqual('空组');
    });

    // ========== 切片2: formatMemberCount - 1 → 1 人 ==========

    it('member_count_one_returns_1人', 0, () => {
      expect(GroupViewHelper.formatMemberCount(1)).assertEqual('1 人');
    });

    // ========== 切片3: formatMemberCount - 5 → 5 人 ==========

    it('member_count_five_returns_5人', 0, () => {
      expect(GroupViewHelper.formatMemberCount(5)).assertEqual('5 人');
    });

    // ========== 切片4: truncateDescription - 默认 80 字符截断 ==========

    it('truncate_description_default_80', 0, () => {
      const long = 'a'.repeat(100);
      const got = GroupViewHelper.truncateDescription(long);
      expect(got.length).assertEqual(83);
      expect(got.endsWith('...')).assertTrue();
    });

    // ========== 切片5: truncateDescription - 未超长原样返回 ==========

    it('truncate_description_no_truncation', 0, () => {
      expect(GroupViewHelper.truncateDescription('短描述')).assertEqual('短描述');
    });

    // ========== 切片6: truncateDescription - 自定义上限 ==========

    it('truncate_description_custom_maxLen', 0, () => {
      const got = GroupViewHelper.truncateDescription('abcdef', 4);
      expect(got).assertEqual('abcd...');
    });
  });
}

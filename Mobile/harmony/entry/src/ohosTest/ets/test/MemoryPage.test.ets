// MemoryPage 记忆管理页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：MemoryViewHelper 视图模型行为（类型颜色映射、类型过滤、温度格式化、内容截断）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 MemoryPage.ets 导出的 MemoryViewHelper 静态方法进行验证，
//       覆盖页面 getTypeColor / filterByType / formatTemperature / truncateContent 的核心视图逻辑。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { MemoryViewHelper } from '../../../../main/ets/pages/MemoryPage';
import { Memory, MemoryType } from '../../../../main/ets/libs/types';

export default function memoryPageTest() {
  describe('MemoryPage', () => {
    // ========== 切片1: getTypeColor - episodic → primary ==========

    it('type_color_episodic_returns_primary', 0, () => {
      expect(MemoryViewHelper.getTypeColor('episodic')).assertEqual('primary');
    });

    // ========== 切片2: getTypeColor - semantic → info ==========

    it('type_color_semantic_returns_info', 0, () => {
      expect(MemoryViewHelper.getTypeColor('semantic')).assertEqual('info');
    });

    // ========== 切片3: getTypeColor - procedural → success ==========

    it('type_color_procedural_returns_success', 0, () => {
      expect(MemoryViewHelper.getTypeColor('procedural')).assertEqual('success');
    });

    // ========== 切片4: getTypeColor - emotional → warning ==========

    it('type_color_emotional_returns_warning', 0, () => {
      expect(MemoryViewHelper.getTypeColor('emotional')).assertEqual('warning');
    });

    // ========== 切片5: getTypeColor - 未知类型 → text_secondary ==========

    it('type_color_unknown_returns_text_secondary', 0, () => {
      expect(MemoryViewHelper.getTypeColor('fact')).assertEqual('text_secondary');
    });

    // ========== 切片6: filterByType - 按类型过滤返回匹配项 ==========

    it('filter_by_type_returns_matching', 0, () => {
      const memories: Memory[] = [
        { id: 'm1', type: 'episodic', content: 'a', agentId: 'a1', createdAt: '', updatedAt: '' },
        { id: 'm2', type: 'semantic', content: 'b', agentId: 'a1', createdAt: '', updatedAt: '' },
        { id: 'm3', type: 'episodic', content: 'c', agentId: 'a1', createdAt: '', updatedAt: '' },
      ];
      const result = MemoryViewHelper.filterByType(memories, 'episodic');
      expect(result.length).assertEqual(2);
      expect(result[0].id).assertEqual('m1');
      expect(result[1].id).assertEqual('m3');
    });

    // ========== 切片7: filterByType - null 返回全部 ==========

    it('filter_by_type_null_returns_all', 0, () => {
      const memories: Memory[] = [
        { id: 'm1', type: 'episodic', content: 'a', agentId: 'a1', createdAt: '', updatedAt: '' },
        { id: 'm2', type: 'semantic', content: 'b', agentId: 'a1', createdAt: '', updatedAt: '' },
      ];
      const result = MemoryViewHelper.filterByType(memories, null);
      expect(result.length).assertEqual(2);
    });

    // ========== 切片8: formatTemperature - 0.5 → "50%" ==========

    it('format_temperature_displays_percentage', 0, () => {
      expect(MemoryViewHelper.formatTemperature(0.5)).assertEqual('50%');
    });

    // ========== 切片9: truncateContent - 超长截断加省略号 ==========

    it('truncate_content_over_3_lines', 0, () => {
      const long = 'abcdefghijklmnopqrstuvwxyz'.repeat(10);
      const result = MemoryViewHelper.truncateContent(long, 100);
      expect(result.length).assertEqual(103);
      expect(result.substring(100)).assertEqual('...');
    });
  });
}

// SleepStatusPage 休眠状态页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：SleepStatusViewHelper 视图模型行为契约（休眠模式颜色映射、模式图标映射、
//           模式标签映射、休眠时长格式化、待办数格式化、是否可唤醒判定）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 SleepStatusPage.ets 导出的 SleepStatusViewHelper 静态方法进行验证，
//       覆盖页面 getModeColor / getModeIcon / getModeLabel / formatSleepDuration /
//       formatPendingCount / isAwakeable 共 6 个核心视图逻辑方法 + formatSleepDuration 边界场景。
// 视图模型刻意设计为无 UI 依赖的纯函数，返回颜色 token 名（如 'success'）而非已解析
// 颜色值，便于测试与主题切换。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { SleepStatusViewHelper } from '../../../../main/ets/pages/SleepStatusPage';
import { SleepStatus } from '../../../../main/ets/libs/types';

export default function sleepStatusPageTest() {
  describe('SleepStatusPage', () => {
    // ========== 切片1: getModeColor - idle → success ==========

    it('mode_color_idle_returns_success', 0, () => {
      expect(SleepStatusViewHelper.getModeColor('idle')).assertEqual('success');
    });

    // ========== 切片2: getModeColor - light → warning ==========

    it('mode_color_light_returns_warning', 0, () => {
      expect(SleepStatusViewHelper.getModeColor('light')).assertEqual('warning');
    });

    // ========== 切片3: getModeColor - deep → error ==========

    it('mode_color_deep_returns_error', 0, () => {
      expect(SleepStatusViewHelper.getModeColor('deep')).assertEqual('error');
    });

    // ========== 切片4: getModeIcon - idle → 💡 ==========

    it('mode_icon_idle_returns_bulb', 0, () => {
      expect(SleepStatusViewHelper.getModeIcon('idle')).assertEqual('💡');
    });

    // ========== 切片5: getModeIcon - light → 🌤️ ==========

    it('mode_icon_light_returns_cloud', 0, () => {
      expect(SleepStatusViewHelper.getModeIcon('light')).assertEqual('🌤️');
    });

    // ========== 切片6: getModeIcon - deep → 🌙 ==========

    it('mode_icon_deep_returns_moon', 0, () => {
      expect(SleepStatusViewHelper.getModeIcon('deep')).assertEqual('🌙');
    });

    // ========== 切片7: getModeLabel - idle → 空闲 ==========

    it('mode_label_idle_returns_chinese', 0, () => {
      expect(SleepStatusViewHelper.getModeLabel('idle')).assertEqual('空闲');
    });

    // ========== 切片8: getModeLabel - light → 浅睡 ==========

    it('mode_label_light_returns_chinese', 0, () => {
      expect(SleepStatusViewHelper.getModeLabel('light')).assertEqual('浅睡');
    });

    // ========== 切片9: getModeLabel - deep → 深睡 ==========

    it('mode_label_deep_returns_chinese', 0, () => {
      expect(SleepStatusViewHelper.getModeLabel('deep')).assertEqual('深睡');
    });

    // ========== 切片10: formatSleepDuration - 无值 → "未休眠" ==========

    it('format_sleep_duration_undefined_returns_not_sleeping', 0, () => {
      expect(SleepStatusViewHelper.formatSleepDuration(undefined)).assertEqual('未休眠');
    });

    // ========== 切片11: formatSleepDuration - 有时长（小时+分钟） → "已休眠 n 小时 n 分钟" ==========

    it('format_sleep_duration_with_hours_and_minutes', 0, () => {
      // 2 小时 30 分钟前开始休眠
      const sleepSince = new Date(Date.now() - (2 * 60 + 30) * 60 * 1000).toISOString();
      const result = SleepStatusViewHelper.formatSleepDuration(sleepSince, new Date());
      expect(result).assertEqual('已休眠 2 小时 30 分钟');
    });

    // ========== 切片12: formatSleepDuration - 边界（仅分钟，无小时） → "已休眠 n 分钟" ==========

    it('format_sleep_duration_only_minutes', 0, () => {
      // 5 分钟前开始休眠
      const sleepSince = new Date(Date.now() - 5 * 60 * 1000).toISOString();
      const result = SleepStatusViewHelper.formatSleepDuration(sleepSince, new Date());
      expect(result).assertEqual('已休眠 5 分钟');
    });

    // ========== 切片13: formatPendingCount - 0 → "无待办" ==========

    it('format_pending_count_zero_returns_none', 0, () => {
      expect(SleepStatusViewHelper.formatPendingCount(0)).assertEqual('无待办');
    });

    // ========== 切片14: formatPendingCount - n → "待办 n 项" ==========

    it('format_pending_count_n_returns_pending', 0, () => {
      expect(SleepStatusViewHelper.formatPendingCount(3)).assertEqual('待办 3 项');
    });

    // ========== 切片15: isAwakeable - isSleeping=true → true ==========

    it('is_awakeable_sleeping_returns_true', 0, () => {
      const status: SleepStatus = {
        agentId: 'a1',
        isSleeping: true,
        mode: 'deep',
        sleepSince: new Date().toISOString(),
        pendingTasks: 2,
      };
      expect(SleepStatusViewHelper.isAwakeable(status)).assertTrue();
    });

    // ========== 切片16: isAwakeable - isSleeping=false → false ==========

    it('is_awakeable_awake_returns_false', 0, () => {
      const status: SleepStatus = {
        agentId: 'a1',
        isSleeping: false,
        mode: 'idle',
        pendingTasks: 0,
      };
      expect(SleepStatusViewHelper.isAwakeable(status)).assertFalse();
    });
  });
}

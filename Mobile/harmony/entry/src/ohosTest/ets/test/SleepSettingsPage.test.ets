// SleepSettingsPage 休眠设置页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：SleepSettingsViewHelper 视图模型行为契约（设置项标签映射、分钟格式化、
//           时间格式校验、脏数据判定、设置项负载构建、模式选项列表）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 SleepSettingsPage.ets 导出的 SleepSettingsViewHelper 静态方法进行验证，
//       覆盖页面 getSettingLabel / formatMinutes / isValidTimeFormat / isDirty /
//       buildSettingsPayload / getModeOptions 共 6 个核心视图逻辑方法。
// 视图模型刻意设计为无 UI 依赖的纯函数，便于测试与主题切换。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { SleepSettingsViewHelper } from '../../../../main/ets/pages/SleepSettingsPage';

export default function sleepSettingsPageTest() {
  describe('SleepSettingsPage', () => {
    // ========== 切片1: getSettingLabel - idleTimeout → 空闲超时 ==========

    it('setting_label_idle_timeout_returns_chinese', 0, () => {
      expect(SleepSettingsViewHelper.getSettingLabel('idleTimeout')).assertEqual('空闲超时');
    });

    // ========== 切片2: getSettingLabel - sleepMode → 休眠模式 ==========

    it('setting_label_sleep_mode_returns_chinese', 0, () => {
      expect(SleepSettingsViewHelper.getSettingLabel('sleepMode')).assertEqual('休眠模式');
    });

    // ========== 切片3: getSettingLabel - wakeOnMessage → 消息唤醒 ==========

    it('setting_label_wake_on_message_returns_chinese', 0, () => {
      expect(SleepSettingsViewHelper.getSettingLabel('wakeOnMessage')).assertEqual('消息唤醒');
    });

    // ========== 切片4: getSettingLabel - wakeOnSchedule → 定时唤醒 ==========

    it('setting_label_wake_on_schedule_returns_chinese', 0, () => {
      expect(SleepSettingsViewHelper.getSettingLabel('wakeOnSchedule')).assertEqual('定时唤醒');
    });

    // ========== 切片5: getSettingLabel - wakeTime → 唤醒时间 ==========

    it('setting_label_wake_time_returns_chinese', 0, () => {
      expect(SleepSettingsViewHelper.getSettingLabel('wakeTime')).assertEqual('唤醒时间');
    });

    // ========== 切片6: getSettingLabel - 未知 key → 原样返回 ==========

    it('setting_label_unknown_returns_key', 0, () => {
      expect(SleepSettingsViewHelper.getSettingLabel('fooBar')).assertEqual('fooBar');
    });

    // ========== 切片7: formatMinutes - 5 → "5 分钟" ==========

    it('format_minutes_short_returns_minutes', 0, () => {
      expect(SleepSettingsViewHelper.formatMinutes(5)).assertEqual('5 分钟');
    });

    // ========== 切片8: formatMinutes - 60 → "1 小时" ==========

    it('format_minutes_one_hour_returns_hour', 0, () => {
      expect(SleepSettingsViewHelper.formatMinutes(60)).assertEqual('1 小时');
    });

    // ========== 切片9: formatMinutes - 90 → "1 小时 30 分钟"（小时+分钟混合） ==========

    it('format_minutes_mixed_returns_hour_and_minutes', 0, () => {
      expect(SleepSettingsViewHelper.formatMinutes(90)).assertEqual('1 小时 30 分钟');
    });

    // ========== 切片10: isValidTimeFormat - "08:30" → true ==========

    it('is_valid_time_format_valid_returns_true', 0, () => {
      expect(SleepSettingsViewHelper.isValidTimeFormat('08:30')).assertTrue();
    });

    // ========== 切片11: isValidTimeFormat - "25:00" → false（小时越界） ==========

    it('is_valid_time_format_invalid_hour_returns_false', 0, () => {
      expect(SleepSettingsViewHelper.isValidTimeFormat('25:00')).assertFalse();
    });

    // ========== 切片12: isValidTimeFormat - "08:60" → false（分钟越界） ==========

    it('is_valid_time_format_invalid_minute_returns_false', 0, () => {
      expect(SleepSettingsViewHelper.isValidTimeFormat('08:60')).assertFalse();
    });

    // ========== 切片13: isValidTimeFormat - "8:30" → false（格式不符 HH:mm） ==========

    it('is_valid_time_format_wrong_pattern_returns_false', 0, () => {
      expect(SleepSettingsViewHelper.isValidTimeFormat('8:30')).assertFalse();
    });

    // ========== 切片14: isDirty - 字段不同 → true ==========

    it('is_dirty_different_returns_true', 0, () => {
      const current: Record<string, Object> = { idleTimeout: 10, sleepMode: 'deep' };
      const original: Record<string, Object> = { idleTimeout: 5, sleepMode: 'deep' };
      expect(SleepSettingsViewHelper.isDirty(current, original)).assertTrue();
    });

    // ========== 切片15: isDirty - 字段相同 → false ==========

    it('is_dirty_same_returns_false', 0, () => {
      const current: Record<string, Object> = { idleTimeout: 10, sleepMode: 'deep' };
      const original: Record<string, Object> = { idleTimeout: 10, sleepMode: 'deep' };
      expect(SleepSettingsViewHelper.isDirty(current, original)).assertFalse();
    });

    // ========== 切片16: buildSettingsPayload - 转换为 settings.update 格式 ==========

    it('build_settings_payload_returns_array', 0, () => {
      const current: Record<string, Object> = {
        idleTimeout: 10,
        sleepMode: 'light',
        wakeOnMessage: true,
        wakeTime: '08:30',
      };
      const result = SleepSettingsViewHelper.buildSettingsPayload(current);
      expect(result.length).assertEqual(4);
      expect(result[0].key).assertEqual('idleTimeout');
      expect(result[0].value).assertEqual(10);
      expect(result[1].key).assertEqual('sleepMode');
      expect(result[1].value).assertEqual('light');
      expect(result[2].key).assertEqual('wakeOnMessage');
      expect(result[2].value).assertEqual(true);
      expect(result[3].key).assertEqual('wakeTime');
      expect(result[3].value).assertEqual('08:30');
    });

    // ========== 切片17: getModeOptions - 返回 3 个选项 idle/light/deep ==========

    it('get_mode_options_returns_three_options', 0, () => {
      const result = SleepSettingsViewHelper.getModeOptions();
      expect(result.length).assertEqual(3);
      expect(result[0].value).assertEqual('idle');
      expect(result[0].label).assertEqual('空闲');
      expect(result[1].value).assertEqual('light');
      expect(result[1].label).assertEqual('浅睡');
      expect(result[2].value).assertEqual('deep');
      expect(result[2].label).assertEqual('深睡');
    });
  });
}

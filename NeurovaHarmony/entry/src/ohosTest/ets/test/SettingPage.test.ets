// SettingPage 应用设置页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：SettingViewHelper 视图模型纯函数行为契约。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对 SettingPage 导出的 SettingViewHelper 视图模型层
//       （findItem / updateItemValue / filterGroups / getGroupItemCount /
//        buildDefaultGroups / isItemDirty）进行验证，
//       覆盖页面渲染与数据流所需的全部纯函数。视图模型刻意设计为无 UI 依赖的纯函数，
//       返回新数组而非原地修改，便于不可变状态更新与测试。
import { describe, it, expect } from '@ohos/hypium';
import { SettingViewHelper } from '../../../../main/ets/pages/SettingPage';
import { SettingGroup, SettingItem } from '../../../../main/ets/libs/types';

export default function settingPageTest() {
  describe('SettingPage', () => {
    // ========== 切片 1: find_item_by_key_returns_item ==========

    it('find_item_by_key_returns_item', 0, () => {
      const groups: SettingGroup[] = [
        {
          key: 'general', title: '通用', items: [
            { key: 'language', label: '语言', type: 'select', value: 'zh-CN', defaultValue: 'zh-CN', group: 'general' },
          ],
        },
      ];
      const item = SettingViewHelper.findItem(groups, 'language');
      expect(item).assertNotNull();
      expect(item!.key).assertEqual('language');
    });

    // ========== 切片 2: find_item_not_found_returns_undefined ==========

    it('find_item_not_found_returns_undefined', 0, () => {
      const groups: SettingGroup[] = [
        {
          key: 'general', title: '通用', items: [
            { key: 'language', label: '语言', type: 'select', value: 'zh-CN', defaultValue: 'zh-CN', group: 'general' },
          ],
        },
      ];
      // 不存在的 key 应返回 undefined
      const item = SettingViewHelper.findItem(groups, 'not_exist_key');
      expect(item).assertUndefined();
    });

    // ========== 切片 3: update_item_value_replaces_value ==========

    it('update_item_value_replaces_value', 0, () => {
      const groups: SettingGroup[] = [
        {
          key: 'appearance', title: '外观', items: [
            { key: 'theme', label: '主题', type: 'select', value: 'light', defaultValue: 'light', group: 'appearance' },
          ],
        },
      ];
      // 不可变更新：返回新数组，原数组不变；匹配项 value 替换为新值
      const next = SettingViewHelper.updateItemValue(groups, 'theme', 'dark');
      // 原数组不变
      expect(groups[0].items[0].value).assertEqual('light');
      // 新数组对应项 value 已替换
      expect(next[0].items[0].value).assertEqual('dark');
      // 其他字段保持不变
      expect(next[0].items[0].key).assertEqual('theme');
      expect(next[0].items[0].label).assertEqual('主题');
    });

    // ========== 切片 4: update_item_value_not_found_returns_original ==========

    it('update_item_value_not_found_returns_original', 0, () => {
      const groups: SettingGroup[] = [
        {
          key: 'general', title: '通用', items: [
            { key: 'language', label: '语言', type: 'select', value: 'zh-CN', defaultValue: 'zh-CN', group: 'general' },
          ],
        },
      ];
      // 未找到 key 应返回原数组（引用相等）
      const next = SettingViewHelper.updateItemValue(groups, 'not_exist_key', 'value');
      // 返回的数组项数与原数组一致
      expect(next.length).assertEqual(groups.length);
      // 未命中分组保持原样（value 不变）
      expect(next[0].items[0].value).assertEqual('zh-CN');
    });

    // ========== 切片 5: filter_groups_by_keys_returns_matching ==========

    it('filter_groups_by_keys_returns_matching', 0, () => {
      const groups: SettingGroup[] = [
        { key: 'general', title: '通用', items: [] },
        { key: 'appearance', title: '外观', items: [] },
        { key: 'privacy', title: '隐私', items: [] },
      ];
      // 只保留 general 和 privacy 分组
      const filtered = SettingViewHelper.filterGroups(groups, ['general', 'privacy']);
      expect(filtered.length).assertEqual(2);
      expect(filtered[0].key).assertEqual('general');
      expect(filtered[1].key).assertEqual('privacy');
    });

    // ========== 切片 6: group_settings_count_returns_correct_count ==========

    it('group_settings_count_returns_correct_count', 0, () => {
      const groups: SettingGroup[] = [
        {
          key: 'general', title: '通用', items: [
            { key: 'language', label: '语言', type: 'select', value: 'zh-CN', defaultValue: 'zh-CN', group: 'general' },
            { key: 'clear_cache', label: '清缓存', type: 'action', value: '', defaultValue: '', group: 'general' },
          ],
        },
        {
          key: 'appearance', title: '外观', items: [
            { key: 'theme', label: '主题', type: 'select', value: 'light', defaultValue: 'light', group: 'appearance' },
          ],
        },
      ];
      // general 分组有 2 个设置项
      expect(SettingViewHelper.getGroupItemCount(groups, 'general')).assertEqual(2);
      // appearance 分组有 1 个设置项
      expect(SettingViewHelper.getGroupItemCount(groups, 'appearance')).assertEqual(1);
      // 不存在的分组返回 0
      expect(SettingViewHelper.getGroupItemCount(groups, 'not_exist')).assertEqual(0);
    });

    // ========== 切片 7: build_default_groups_returns_5_groups ==========

    it('build_default_groups_returns_5_groups', 0, () => {
      const groups = SettingViewHelper.buildDefaultGroups();
      // 必须返回 5 个分组：general / appearance / notification / privacy / about
      expect(groups.length).assertEqual(5);
      expect(groups[0].key).assertEqual('general');
      expect(groups[1].key).assertEqual('appearance');
      expect(groups[2].key).assertEqual('notification');
      expect(groups[3].key).assertEqual('privacy');
      expect(groups[4].key).assertEqual('about');
    });

    // ========== 切片 8: build_default_groups_appearance_has_theme_select ==========

    it('build_default_groups_appearance_has_theme_select', 0, () => {
      const groups = SettingViewHelper.buildDefaultGroups();
      const appearance = groups.find((g) => g.key === 'appearance');
      expect(appearance).assertNotNull();
      // appearance 分组必须包含 theme select 项（light/dark/auto 三选项）
      const theme = appearance!.items.find((it) => it.key === 'theme');
      expect(theme).assertNotNull();
      expect(theme!.type).assertEqual('select');
      expect(theme!.group).assertEqual('appearance');
      expect(theme!.options!.length).assertEqual(3);
      const optionValues = theme!.options!.map((o) => o.value);
      expect(optionValues.indexOf('light') >= 0).assertTrue();
      expect(optionValues.indexOf('dark') >= 0).assertTrue();
      expect(optionValues.indexOf('auto') >= 0).assertTrue();
    });

    // ========== 切片 9: build_default_groups_privacy_has_logout_action ==========

    it('build_default_groups_privacy_has_logout_action', 0, () => {
      const groups = SettingViewHelper.buildDefaultGroups();
      const privacy = groups.find((g) => g.key === 'privacy');
      expect(privacy).assertNotNull();
      // privacy 分组必须包含 logout action 项
      const logout = privacy!.items.find((it) => it.key === 'logout');
      expect(logout).assertNotNull();
      expect(logout!.type).assertEqual('action');
      expect(logout!.group).assertEqual('privacy');
      expect(logout!.label).assertEqual('退出登录');
    });

    // ========== 切片 10: is_dirty_item_changed_returns_true ==========

    it('is_dirty_item_changed_returns_true', 0, () => {
      const original: SettingItem = {
        key: 'theme', label: '主题', type: 'select',
        value: 'light', defaultValue: 'light', group: 'appearance',
      };
      const current: SettingItem = {
        key: 'theme', label: '主题', type: 'select',
        value: 'dark', defaultValue: 'light', group: 'appearance',
      };
      // value 不等 → dirty = true
      expect(SettingViewHelper.isItemDirty(original, current)).assertTrue();
    });

    // ========== 切片 11: is_dirty_item_unchanged_returns_false ==========

    it('is_dirty_item_unchanged_returns_false', 0, () => {
      const original: SettingItem = {
        key: 'theme', label: '主题', type: 'select',
        value: 'light', defaultValue: 'light', group: 'appearance',
      };
      const current: SettingItem = {
        key: 'theme', label: '主题', type: 'select',
        value: 'light', defaultValue: 'light', group: 'appearance',
      };
      // value 相等 → dirty = false
      expect(SettingViewHelper.isItemDirty(original, current)).assertFalse();
    });
  });
}

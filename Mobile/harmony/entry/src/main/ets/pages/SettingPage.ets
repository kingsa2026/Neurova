/**
 * SettingPage - 应用设置页
 *
 * 职责：按分组展示设置项，支持 toggle/select/input/slider/action 五种类型，
 *       修改后即时保存或批量保存；支持退出登录、清缓存、重置等操作
 * 设计：
 *   - Column [TopNavMenu(标题+返回+保存)] + [分组列表] + [底部版本号]；
 *   - 每个 SettingGroup 一个区块（分组标题 + GlassCard 列表）；
 *   - toggle 类型：Toggle 开关 + label + description；
 *   - select 类型：点击弹出 AlertDialog 选择器；
 *   - input 类型：GlassInput；
 *   - slider 类型：Slider + 当前值；
 *   - action 类型：GlassButton（如"清除缓存"、"退出登录"）。
 *   - 颜色统一走 StyleManager，路由走 Router，API 走 ApiFacade.settings，
 *     状态走 AppStore/AuthStore，配置走 ConfigManager，消息走 MessageManager。
 *
 * 视图模型层（SettingViewHelper）：
 *   - 刻意设计为无 UI 依赖的纯函数集合，便于单元测试；
 *   - findItem / updateItemValue / filterGroups / getGroupItemCount /
 *     buildDefaultGroups / isItemDirty 全部为静态方法、无副作用；
 *   - updateItemValue 返回新数组而非原地修改，便于不可变状态更新。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（settings 模块：list/update/reset）
 *   - ../libs/state/stores/AppStore：应用状态（theme/language）
 *   - ../libs/state/stores/AuthStore：认证状态（logout 用于"退出登录"）
 *   - ../routing/Router：统一路由跳转 + RouteNames（SETTINGS/LOGIN）
 *   - ../libs/style/StyleManager：统一样式 token + 主题切换
 *   - ../libs/config/ConfigManager：配置管理（清缓存 / 版本号）
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：SettingItem、SettingGroup、SettingType
 *
 * 用法：
 *   由 Router.push(RouteNames.SETTINGS) 跳转进入；
 *   aboutToAppear 调用 api.settings.list() 加载分组并缓存原始值；
 *   toggle/slider 实时调用 api.settings.update(key, value)；
 *   select/input 本地更新，点击保存按钮批量提交；
 *   主题切换同步 styleManager.setThemeMode + appStore.setTheme + api.settings.update；
 *   退出登录 AlertDialog 二次确认 → authStore.logout → router.resetTo(LOGIN)；
 *   清缓存调用 ConfigManager + MessageManager.success 提示。
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput } from '../components/glass';
import { AppIcon } from '../components/common/AppIcon';
import { mediaquery, window } from '@kit.ArkUI';
import { ConfigurationConstant } from '@kit.AbilityKit';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AppStore } from '../libs/state/stores/AppStore';
import { AuthStore } from '../libs/state/stores/AuthStore';
import { Router, RouteNames } from '../routing/Router';
import { StyleManager, ThemeMode } from '../libs/style/StyleManager';
import { ConfigManager } from '../libs/config/ConfigManager';
import { ServerProfiles } from '../libs/config/ServerProfiles';
import { PlatformAdapter } from '../libs/adapters/PlatformAdapter';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { SettingGroup, SettingItem } from '../libs/types';

/** 日志标签 */
const TAG = 'SettingPage';

/**
 * SettingViewHelper - 应用设置页视图模型纯函数集合
 *
 * 职责：封装设置项查找、不可变更新、分组过滤、计数、默认分组构建、脏数据比较
 * 设计：全部为静态方法、无副作用、无 UI 依赖，可直接单元测试
 *
 * 用法：
 *   const item = SettingViewHelper.findItem(groups, 'theme');
 *   const next = SettingViewHelper.updateItemValue(groups, 'theme', 'dark');
 *   const dirty = SettingViewHelper.isItemDirty(original, current);
 */
export class SettingViewHelper {
  /**
   * 按 key 在所有分组中查找设置项
   * 遍历 groups → items，返回首个 key 匹配的 item；未找到返回 undefined
   */
  static findItem(groups: SettingGroup[], key: string): SettingItem | undefined {
    for (const group of groups) {
      for (const item of group.items) {
        if (item.key === key) {
          return item;
        }
      }
    }
    return undefined;
  }

  /**
   * 不可变更新：返回新 groups 数组，匹配 key 的 item 的 value 替换为 newValue
   * 原数组保持不变；其他字段保持原样
   */
  static updateItemValue(groups: SettingGroup[], key: string, newValue: Object): SettingGroup[] {
    return groups.map((group): SettingGroup => {
      const hasKey = group.items.some((it) => it.key === key);
      if (!hasKey) {
        return group;
      }
      const nextItems: SettingItem[] = group.items.map((it): SettingItem => {
        if (it.key === key) {
          // ArkTS 禁止对象展开，逐键拷贝（可选字段显式带回 undefined 亦合法）
          return {
            key: it.key,
            label: it.label,
            description: it.description,
            type: it.type,
            value: newValue,
            defaultValue: it.defaultValue,
            options: it.options,
            min: it.min,
            max: it.max,
            step: it.step,
            group: it.group,
            requiresRestart: it.requiresRestart,
          };
        }
        return it;
      });
      return {
        key: group.key,
        title: group.title,
        icon: group.icon,
        items: nextItems,
      };
    });
  }

  /**
   * 按 group key 列表过滤分组，只返回 keys 中包含的分组（保持原顺序）
   */
  static filterGroups(groups: SettingGroup[], keys: string[]): SettingGroup[] {
    return groups.filter((g) => keys.indexOf(g.key) >= 0);
  }

  /**
   * 获取指定分组的设置项数量；分组不存在返回 0
   */
  static getGroupItemCount(groups: SettingGroup[], groupKey: string): number {
    for (const group of groups) {
      if (group.key === groupKey) {
        return group.items.length;
      }
    }
    return 0;
  }

  /**
   * 构建默认设置分组（视图模型）
   * 5 个分组：general / appearance / notification / privacy / about
   * 各分组设置项按需求定义：
   *   - general：语言（select）、清缓存（action）
   *   - appearance：主题（select: light/dark/auto）、字号（slider）
   *   - notification：推送开关（toggle）、声音（toggle）、震动（toggle）
   *   - privacy：数据分析（toggle）、错误上报（toggle）、退出登录（action）
   *   - about：版本号（input readonly）、检查更新（action）
   */
  static buildDefaultGroups(): SettingGroup[] {
    return [
      {
        key: 'general', title: '通用', icon: '⚙️', items: [
          {
            key: 'language', label: '语言', description: '应用界面语言',
            type: 'select', value: 'zh-CN', defaultValue: 'zh-CN', group: 'general',
            options: [
              { label: '简体中文', value: 'zh-CN' },
              { label: 'English', value: 'en-US' },
            ],
          },
          {
            key: 'clear_cache', label: '清除缓存', description: '清理本地临时数据',
            type: 'action', value: '', defaultValue: '', group: 'general',
          },
        ],
      },
      {
        key: 'appearance', title: '外观', icon: '🎨', items: [
          {
            key: 'theme', label: '主题', description: 'light / dark / auto',
            type: 'select', value: 'auto', defaultValue: 'auto', group: 'appearance',
            options: [
              { label: '浅色', value: 'light' },
              { label: '深色', value: 'dark' },
              { label: '跟随系统', value: 'auto' },
            ],
          },
          {
            key: 'font_size', label: '字号', description: '正文字号（12-24）',
            type: 'slider', value: 16, defaultValue: 16, group: 'appearance',
            min: 12, max: 24, step: 1,
          },
        ],
      },
      {
        key: 'notification', title: '通知', icon: '🔔', items: [
          {
            key: 'notify_push', label: '推送通知', description: '接收消息推送',
            type: 'toggle', value: true, defaultValue: true, group: 'notification',
          },
          {
            key: 'notify_sound', label: '声音', description: '消息提示音',
            type: 'toggle', value: true, defaultValue: true, group: 'notification',
          },
          {
            key: 'notify_vibrate', label: '震动', description: '消息震动反馈',
            type: 'toggle', value: false, defaultValue: false, group: 'notification',
          },
        ],
      },
      {
        key: 'privacy', title: '隐私', icon: '🔒', items: [
          {
            key: 'data_analytics', label: '数据分析', description: '匿名使用数据分析',
            type: 'toggle', value: false, defaultValue: false, group: 'privacy',
          },
          {
            key: 'error_report', label: '错误上报', description: '自动上报错误堆栈',
            type: 'toggle', value: true, defaultValue: true, group: 'privacy',
          },
          {
            key: 'logout', label: '退出登录', description: '清除账号并返回登录页',
            type: 'action', value: '', defaultValue: '', group: 'privacy',
          },
        ],
      },
      {
        key: 'about', title: '关于', icon: 'ℹ️', items: [
          {
            key: 'version', label: '版本号', description: '当前应用版本',
            type: 'input', value: '1.0.0', defaultValue: '1.0.0', group: 'about',
          },
          {
            key: 'check_update', label: '检查更新', description: '检查最新版本',
            type: 'action', value: '', defaultValue: '', group: 'about',
          },
        ],
      },
    ];
  }

  /**
   * 判断设置项是否已修改（dirty）：比较 original 与 current 的 value
   * value 不等返回 true（已修改）；相等返回 false（未修改）
   */
  static isItemDirty(original: SettingItem, current: SettingItem): boolean {
    return original.value !== current.value;
  }
}

/**
 * SettingPage - 应用设置页组件
 *
 * 渲染规则：
 *   - aboutToAppear 调用 api.settings.list() 加载分组，失败则回退到 buildDefaultGroups()
 *   - 缓存原始 groups（深拷贝）用于 isItemDirty 比较
 *   - toggle/slider 修改：实时调用 api.settings.update(key, value)
 *   - select/input 修改：本地更新，点击保存按钮批量提交
 *   - 主题切换：同步 styleManager.setThemeMode + appStore.setTheme + api.settings.update
 *   - 退出登录：AlertDialog 二次确认 → authStore.logout → router.resetTo(LOGIN)
 *   - 清缓存：调用 ConfigManager.clear + MessageManager.success
 *   - 重置：调用 api.settings.reset(group) → 重新加载
 */
@Component
export struct SettingPage {
  // 设置分组列表（由 API 加载或 buildDefaultGroups 回退，驱动列表渲染）
  @State groups: SettingGroup[] = [];
  // 原始分组快照（aboutToAppear 时深拷贝，用于 isItemDirty 比较）
  @State originalGroups: SettingGroup[] = [];
  // 加载态
  @State loading: boolean = true;

  // 统一库单例
  private api = ApiFacade.getInstance();
  private appStore = new AppStore();
  private authStore = new AuthStore();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private cm = ConfigManager.getInstance();
  private platform = PlatformAdapter.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  // F10 入口行徽标数据（真实计数，fail-soft）
  @State private serverCount: number = 0;
  @State private unreadCount: number = 0;

  aboutToAppear() {
    this.loadSettings();
    this.loadEntryCounts();
  }

  /** F10 分组一徽标：服务器档案数 + 未读通知数（真端点，失败置 0 不阻塞页面） */
  private async loadEntryCounts(): Promise<void> {
    try {
      this.serverCount = ServerProfiles.getInstance().getList().length;
    } catch (e) {
      this.serverCount = 0;
    }
    try {
      const res = await this.api.monitor.getUnreadCount();
      if (res.code === 0 && res.data !== undefined && res.data !== null) {
        this.unreadCount = Number(res.data);
      }
    } catch (e) {
      this.unreadCount = 0;
    }
  }

  /** 工作区地址（档案地址去 /api/v1 尾缀） */
  private workspaceHost(): string {
    const base = ServerProfiles.getInstance().getActiveApiBase();
    if (base.length === 0) {
      return '未连接';
    }
    return base.replace('/api/v1', '').replace('http://', '').replace('https://', '');
  }

  /** 当前登录用户是否管理员（role 取自 /auth/me；非 admin 时管理员分组不渲染） */
  private isAdmin(): boolean {
    const u = this.authStore.user;
    return u !== undefined && u.role === 'admin';
  }

  /**
   * 加载设置分组
   * 流程：调用 API 获取分组 → 深拷贝原始快照 → 失败回退默认分组
   * 异常：记录日志并使用默认分组兜底，保证页面可用
   */
  private async loadSettings(): Promise<void> {
    this.loading = true;
    try {
      const res = await this.api.settings.list();
      if (res.code === 0 && res.data && res.data.length > 0) {
        this.groups = res.data;
      } else {
        // 后端无数据时使用默认分组
        this.groups = SettingViewHelper.buildDefaultGroups();
      }
      this.originalGroups = this.cloneGroups(this.groups);
    } catch (e) {
      this.logger.error(TAG, '加载设置失败，使用默认分组', e as Error);
      this.groups = SettingViewHelper.buildDefaultGroups();
      this.originalGroups = this.cloneGroups(this.groups);
    } finally {
      this.loading = false;
    }
  }

  /** 深拷贝分组数组（用于原始快照） */
  private cloneGroups(groups: SettingGroup[]): SettingGroup[] {
    return groups.map((g): SettingGroup => ({
      key: g.key,
      title: g.title,
      icon: g.icon,
      // ArkTS 禁止对象展开，逐键拷贝
      items: g.items.map((it): SettingItem => ({
        key: it.key,
        label: it.label,
        description: it.description,
        type: it.type,
        value: it.value,
        defaultValue: it.defaultValue,
        options: it.options,
        min: it.min,
        max: it.max,
        step: it.step,
        group: it.group,
        requiresRestart: it.requiresRestart,
      })),
    }));
  }

  /**
   * 修改设置项值（通用入口）
   * toggle/slider/select/input 都走此入口
   * 流程：不可变更新本地 groups → 实时调用 API 持久化 → 主题/语言同步全局状态
   */
  private async updateValue(key: string, newValue: Object): Promise<void> {
    this.groups = SettingViewHelper.updateItemValue(this.groups, key, newValue);
    // 主题切换：同步 StyleManager + AppStore
    if (key === 'theme') {
      this.applyTheme(newValue as string);
    }
    // 语言切换：同步 AppStore
    if (key === 'language') {
      this.appStore.setLanguage(newValue as string);
    }
    // 实时持久化
    try {
      await this.api.settings.update(key, newValue);
    } catch (e) {
      this.logger.error(TAG, `更新设置失败: ${key}`, e as Error);
      this.msg.error('保存设置失败');
    }
  }

  /** 应用主题：light/dark/auto → StyleManager + AppStore + 窗口色彩模式 */
  private applyTheme(theme: string): void {
    let mode: ThemeMode;
    if (theme === 'auto') {
      // 跟随系统：实时探测系统深色模式（此前恒落 light，auto 名不副实——审计 3.8-4）
      const dark = this.systemPrefersDark();
      mode = dark ? ThemeMode.DARK : ThemeMode.LIGHT;
    } else if (theme === 'dark') {
      mode = ThemeMode.DARK;
    } else {
      mode = ThemeMode.LIGHT;
    }
    this.sm.setThemeMode(mode);
    this.appStore.setTheme(mode === ThemeMode.DARK ? 'dark' : 'light');
    // 应用色彩模式与系统条同步（模糊材质/状态栏/页签栏材质都跟随应用色彩模式）
    try {
      getContext(this).getApplicationContext()
        .setColorMode(mode === ThemeMode.DARK
          ? ConfigurationConstant.ColorMode.COLOR_MODE_DARK
          : ConfigurationConstant.ColorMode.COLOR_MODE_LIGHT);
      window.getLastWindow(getContext(this)).then((win: window.Window) => {
        win.setWindowBackgroundColor(mode === ThemeMode.DARK ? '#0a0e1d' : '#f5f6fb');
        // 系统栏透明（边到边）：底色由窗口/页面星野承担，只按模式切换栏内容色
        win.setWindowSystemBarProperties({
          statusBarColor: '#00000000',
          navigationBarColor: '#00000000',
          statusBarContentColor: mode === ThemeMode.DARK ? '#ffffff' : '#0a0e1d',
          navigationBarContentColor: mode === ThemeMode.DARK ? '#ffffff' : '#0a0e1d',
        });
      }).catch((e: Error) => {
        this.logger.warn(TAG, '系统条同步失败', e);
      });
    } catch (e) {
      this.logger.warn(TAG, '窗口主题同步失败', e as Error);
    }
  }

  /** 系统当前是否深色模式（dark-mode 媒体查询；探测失败按浅色兜底，只影响 auto 档初值） */
  private systemPrefersDark(): boolean {
    try {
      return mediaquery.matchMediaSync('(dark-mode: true)').matches;
    } catch (e) {
      this.logger.warn(TAG, '系统深色模式探测失败，auto 档按浅色处理', e as Error);
      return false;
    }
  }

  /**
   * 批量保存：遍历所有设置项，对 dirty 项调用 api.settings.update
   * 由顶部"保存"按钮触发
   */
  private async saveAll(): Promise<void> {
    let saved = 0;
    for (const group of this.groups) {
      for (const item of group.items) {
        const orig = SettingViewHelper.findItem(this.originalGroups, item.key);
        if (orig && SettingViewHelper.isItemDirty(orig, item)) {
          try {
            await this.api.settings.update(item.key, item.value);
            saved++;
          } catch (e) {
            this.logger.error(TAG, `批量保存失败: ${item.key}`, e as Error);
          }
        }
      }
    }
    // 更新原始快照
    this.originalGroups = this.cloneGroups(this.groups);
    if (saved > 0) {
      this.msg.success(`已保存 ${saved} 项`);
    } else {
      this.msg.info('无修改');
    }
  }

  /**
   * 点击 action 类型设置项的统一处理
   * 根据 key 分发到 clearCache / logout / checkUpdate 等具体操作
   */
  private handleAction(key: string): void {
    if (key === 'clear_cache') {
      this.confirmClearCache();
    } else if (key === 'logout') {
      this.confirmLogout();
    } else if (key === 'check_update') {
      this.msg.info('当前已是最新版本');
    } else {
      this.msg.info('功能开发中');
    }
  }

  /** 清缓存二次确认 */
  private confirmClearCache(): void {
    AlertDialog.show({
      title: '清除缓存',
      message: '确定要清除本地缓存数据吗？',
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: { value: '取消', action: () => {} },
      secondaryButton: {
        value: '确定',
        action: () => { this.clearCache(); },
      },
    });
  }

  /** 执行清缓存：调用 ConfigManager + MessageManager 提示 */
  private clearCache(): void {
    try {
      this.cm.clear();
      this.cm.initDefaults();
      this.msg.success('缓存已清除');
    } catch (e) {
      this.logger.error(TAG, '清缓存失败', e as Error);
      this.msg.error('清缓存失败');
    }
  }

  /** 退出登录二次确认 */
  private confirmLogout(): void {
    AlertDialog.show({
      title: '退出登录',
      message: '确定要退出当前账号吗？需要重新登录才能继续使用。',
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: { value: '取消', action: () => {} },
      secondaryButton: {
        value: '退出',
        fontColor: this.sm.getColor('error'),
        action: () => { this.logout(); },
      },
    });
  }

  /** 执行退出登录：清除认证状态 → 重置路由到登录页 */
  private logout(): void {
    try {
      // 推送令牌注销（fire-and-forget；失败不影响登出）。
      // deviceId 与登录上报同走 PlatformAdapter.getDeviceId() 单源（后端按 device_id
      // 索引注册表，两端口径不一致时注销永远打不中登记项——审计 3.8-5）；
      // 仅在真实推送令牌存在时发起，从未上报过的设备不发无主请求
      if (this.cm.get<string>('push_token', '').length > 0) {
        this.api.push.remove(this.platform.getDeviceId()).catch((e: Object) => {
          this.logger.warn(TAG, '推送令牌注销失败（不影响登出）', e as Error);
        });
      }
      this.authStore.logout();
      this.msg.success('已退出登录');
      this.router.resetTo(RouteNames.LOGIN);
    } catch (e) {
      this.logger.error(TAG, '退出登录失败', e as Error);
      this.msg.error('退出登录失败');
    }
  }

  /**
   * 重置指定分组为默认值
   * 流程：调用 api.settings.reset(group) → 重新加载分组
   */
  private async resetGroup(groupKey: string): Promise<void> {
    try {
      await this.api.settings.reset(groupKey);
      this.msg.success('已重置');
      await this.loadSettings();
    } catch (e) {
      this.logger.error(TAG, `重置分组失败: ${groupKey}`, e as Error);
      this.msg.error('重置失败');
    }
  }

  /** 获取 select 类型当前选中项的 label */
  private getSelectLabel(item: SettingItem): string {
    if (!item.options) return String(item.value);
    const opt = item.options.find((o) => String(o.value) === String(item.value));
    return opt ? opt.label : String(item.value);
  }

  /**
   * 点击 select 类型设置项：弹出选项选择对话框，每个选项一个按钮，点选即回写
   * （此前是空壳对话框：只有无动作的取消/确定按钮，选不了任何值——审计 3.8-4）
   */
  private showSelectPicker(item: SettingItem): void {
    if (!item.options || item.options.length === 0) return;
    // 每个选项生成一个按钮；当前选中项以主题色高亮，点选后经 updateValue 回写并持久化
    const optionButtons: AlertDialogButtonOptions[] = [];
    for (const opt of item.options) {
      const selected = String(opt.value) === String(item.value);
      optionButtons.push({
        value: opt.label,
        fontColor: selected ? this.sm.getColor('primary') : this.sm.getColor('text_secondary'),
        action: () => {
          this.updateValue(item.key, opt.value);
        },
      });
    }
    // 字面量先赋给 SDK 显式类型，避免 AlertDialog.show 联合参数类型的重载解析失败
    const dialogParam: AlertDialogParamWithOptions = {
      title: item.label,
      message: '请选择',
      autoCancel: true,
      alignment: DialogAlignment.Center,
      buttons: optionButtons,
    };
    AlertDialog.show(dialogParam);
  }

  build() {
    Column() {
      // 内联头（原型 F10：21/700 我的 + 保存渐变胶囊）
      Row() {
        Text('我的')
          .fontSize(21)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.sm.getColor('text_primary'))
          .layoutWeight(1)
        Button() {
          Text('保存')
            .fontSize(13)
            .fontColor(this.sm.getColor('text_on_primary'))
        }
        .height(34)
        .linearGradient({ angle: 135, colors: [[this.sm.getColor('secondary'), 0], [this.sm.getColor('primary'), 1]] })
        .onClick(() => {
          this.saveAll();
        })
      }
      .width('100%')
      .padding({ left: 20, right: 20, top: 8, bottom: 10 })

      // 个人卡（原型 F10：渐变头像 + 用户名 + 工作区/配对态 + 箭头）
      Row() {
        Text((this.authStore.user?.username ?? 'U').slice(0, 1))
          .fontSize(20)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.sm.getColor('text_on_primary'))
          .width(52)
          .height(52)
          .borderRadius(18)
          .textAlign(TextAlign.Center)
          .linearGradient({ angle: 135, colors: [[this.sm.getColor('secondary'), 0], [this.sm.getColor('primary'), 1]] })
        Column() {
          Text(this.authStore.user?.username ?? '未登录')
            .fontSize(16)
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
          Row() {
            Row()
              .width(5)
              .height(5)
              .borderRadius(3)
              .backgroundColor(this.authStore.isPaired ? this.sm.getColor('success') : this.sm.getColor('warning'))
            Text('工作区 ' + this.workspaceHost() + (this.authStore.isPaired ? ' · 已配对' : ' · 未配对'))
              .fontSize(this.sm.getFontSize('badge'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ left: 6 })
          }
          .margin({ top: 3 })
          .alignItems(VerticalAlign.Center)
        }
        .alignItems(HorizontalAlign.Start)
        .margin({ left: 12 })
        .layoutWeight(1)
        AppIcon({ name: 'chev', iconSize: 16, color: this.sm.getColor('text_tertiary') })
      }
      .width('calc(100% - 32vp)')
      .margin({ left: 16, right: 16, bottom: 10 })
      .padding(14)
      .borderRadius(16)
      .backgroundColor(this.sm.getColor('glass'))
      .border({ width: 1, color: this.sm.getColor('border') })
      .alignItems(VerticalAlign.Center)

      // 分组一（原型 F10：功能入口行 = 圆角图标 + 标题(+徽标) + 数值 + 箭头）
      Column() {
        this.entryRow('server', '服务器与配对', this.serverCount > 0 ? this.serverCount.toString() + ' 台档案' : '', '', RouteNames.CONNECTION)
        this.entryRow('model', '模型管理', '', '', RouteNames.MODEL)
        this.entryRow('bell', '通知中心', this.unreadCount > 0 ? this.unreadCount.toString() : '', '', RouteNames.NOTIFICATION)
        this.entryRow('task', '任务看板', '', '', RouteNames.TASK)
        this.entryRow('folder', '文件', '', '', RouteNames.FILE)
        this.entryRow('book', '技能市场', '', '', RouteNames.MARKETPLACE)
      }
      .width('calc(100% - 32vp)')
      .margin({ left: 16, right: 16, bottom: 10 })
      .borderRadius(16)
      .backgroundColor(this.sm.getColor('glass'))
      .border({ width: 1, color: this.sm.getColor('border') })
      .clip(true)

      // 管理员分组：仅 role=admin 渲染（原型 F10；紫边框 + 组标完整语义）
      if (this.isAdmin()) {
        Column() {
          Row() {
            AppIcon({ name: 'shield', iconSize: 11, color: this.sm.getColor('primary') })
            Text('管理员 · 仅 role=admin 时渲染')
              .fontSize(10)
              .fontColor(this.sm.getColor('primary'))
              .letterSpacing(0.6)
              .margin({ left: 6 })
          }
          .margin({ left: 20, top: 4, bottom: 8 })
          .alignItems(VerticalAlign.Center)

          Column() {
            this.entryRow('user', '用户管理', '', '', RouteNames.ADMIN_USERS)
            this.entryRow('task', '用户组管理', '', '', RouteNames.ADMIN_GROUPS)
            this.entryRow('book', '市场管理', '', '', RouteNames.ADMIN_MARKET)
            this.entryRow('gear', '系统设置（治理）', '', '', RouteNames.ADMIN_SETTINGS)
          }
          .width('calc(100% - 32vp)')
          .margin({ left: 16 })
          .borderRadius(16)
          .backgroundColor(this.sm.getColor('glass'))
          .border({ width: 1, color: this.sm.getColor('primary') })
          .clip(true)
        }
        .width('100%')
        .margin({ bottom: 10 })
      }

      if (this.loading) {
        // 加载态
        Column() {
          Text('加载中...')
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_secondary'))
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      } else {
        // 分组列表
        List({ space: 16 }) {
          ForEach(this.groups, (group: SettingGroup) => {
            ListItem() {
              this.buildGroupSection(group)
            }
          }, (group: SettingGroup) => group.key)
        }
        .layoutWeight(1)
        .width('100%')
        .scrollBar(BarState.Off)
        .padding({
          left: this.sm.getSpacing('md'),
          right: this.sm.getSpacing('md'),
          top: this.sm.getSpacing('sm'),
          bottom: this.sm.getSpacing('sm'),
        })
      }

      // 退出登录（设计 F10 .me-out：独立红色卡；与隐私组内 logout 动作同一处理单源）
      Row() {
        AppIcon({ name: 'logout', iconSize: 18, color: this.sm.getColor('error') })
        Text('退出登录')
          .fontSize(this.sm.getFontSize('body_sm'))
          .fontColor(this.sm.getColor('error'))
          .margin({ left: 8 })
      }
      .width('calc(100% - 32vp)')
      .justifyContent(FlexAlign.Center)
      .padding(14)
      .borderRadius(16)
      .backgroundColor('rgba(248,113,113,0.06)')
      .border({ width: 1, color: 'rgba(248,113,113,0.25)' })
      .margin({ left: 16, right: 16, bottom: 16 })
      .alignItems(VerticalAlign.Center)
      .onClick(() => {
        this.logout();
      })
    }
    .width('100%')
    .height('100%')

  }

  // ===========================================================================
  // F10 功能入口行构建器（圆角图标 + 标题(+徽标) + 数值 + 箭头）
  // ===========================================================================

  @Builder
  entryRow(icon: string, title: string, badge: string, value: string, route: string) {
    Row() {
      Column() {
        AppIcon({ name: icon, iconSize: 18, color: this.sm.getColor('primary') })
      }
      .width(30)
      .height(30)
      .borderRadius(10)
      .backgroundColor(this.sm.getColor('primary_soft'))
      .justifyContent(FlexAlign.Center)
      .alignItems(HorizontalAlign.Center)

      Text(title)
        .fontSize(this.sm.getFontSize('body_sm'))
        .fontColor(this.sm.getColor('text_primary'))
        .margin({ left: 12 })
      if (badge !== '') {
        Text(badge)
          .fontSize(9.5)
          .fontWeight(FontWeight.Medium)
          .fontColor(this.sm.getColor('text_on_primary'))
          .backgroundColor('rgba(99,102,241,0.85)')
          .borderRadius(999)
          .padding({ left: 7, right: 7, top: 1, bottom: 1 })
          .margin({ left: 8 })
      }
      Blank()
      if (value !== '') {
        Text(value)
          .fontSize(this.sm.getFontSize('badge'))
          .fontColor(this.sm.getColor('text_tertiary'))
      }
      AppIcon({ name: 'chev', iconSize: 14, color: this.sm.getColor('text_tertiary') })
        .margin({ left: 6 })
    }
    .width('100%')
    .padding({ left: 14, right: 14, top: 11, bottom: 11 })
    .border({ width: { bottom: 1 }, color: this.sm.getColor('divider') })
    .alignItems(VerticalAlign.Center)
    .onClick(() => {
      this.router.push(route);
    })
  }

  // ===========================================================================
  // 分组区块构建器
  // ===========================================================================

  /** 单个分组区块：分组标题 + 设置项列表 */
  @Builder
  buildGroupSection(group: SettingGroup) {
    Column() {
      // 分组标题（带图标）
      Row() {
        Text(group.icon ?? '')
          .fontSize(this.sm.getFontSize('subtitle'))
        Text(group.title)
          .fontSize(this.sm.getFontSize('subtitle'))
          .fontWeight(FontWeight.Bold)
          .fontColor(this.sm.getColor('text_primary'))
          .margin({ left: this.sm.getSpacing('xs') })
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
      .margin({ bottom: this.sm.getSpacing('sm') })

      // 分组下设置项列表
      ForEach(group.items, (item: SettingItem) => {
        // ArkTS 解析器不允许尾随闭包组件调用后再链属性修饰，外包 Column 承接宽度与间距
        Column() {
          GlassCard() {
            this.buildItemRow(item)
          }
        }
        .width('100%')
        .margin({ bottom: this.sm.getSpacing('xs') })
      }, (item: SettingItem) => item.key)
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
  }

  /** 根据设置项类型分发到对应构建器 */
  @Builder
  buildItemRow(item: SettingItem) {
    if (item.type === 'toggle') {
      this.buildToggleItem(item)
    } else if (item.type === 'select') {
      this.buildSelectItem(item)
    } else if (item.type === 'input') {
      this.buildInputItem(item)
    } else if (item.type === 'slider') {
      this.buildSliderItem(item)
    } else if (item.type === 'action') {
      this.buildActionItem(item)
    }
  }

  /** toggle 类型：label + description + Toggle 开关 */
  @Builder
  buildToggleItem(item: SettingItem) {
    Row() {
      Column() {
        Text(item.label)
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_primary'))
        if (item.description) {
          Text(item.description)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: 2 })
        }
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)

      Toggle({ type: ToggleType.Switch, isOn: Boolean(item.value) })
        .onChange((isOn: boolean) => {
          // 与 GlassInput 同理：属性同步回声（isOn 等于受控值）不外抛，防渲染驱动写状态
          if (isOn === Boolean(item.value)) {
            return;
          }
          this.updateValue(item.key, isOn);
        })
    }
    .width('100%')
    .alignItems(VerticalAlign.Center)
  }

  /** select 类型：label + description + 当前值（点击弹出选择器） */
  @Builder
  buildSelectItem(item: SettingItem) {
    Row() {
      Column() {
        Text(item.label)
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_primary'))
        if (item.description) {
          Text(item.description)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: 2 })
        }
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)

      Text(this.getSelectLabel(item))
        .fontSize(this.sm.getFontSize('body'))
        .fontColor(this.sm.getColor('text_secondary'))
        .onClick(() => { this.showSelectPicker(item); })
    }
    .width('100%')
    .alignItems(VerticalAlign.Center)
  }

  /** input 类型：label + description + GlassInput */
  @Builder
  buildInputItem(item: SettingItem) {
    Column() {
      Text(item.label)
        .fontSize(this.sm.getFontSize('body'))
        .fontColor(this.sm.getColor('text_primary'))
      if (item.description) {
        Text(item.description)
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .margin({ top: 2 })
      }
      GlassInput({
        placeholder: `请输入${item.label}`,
        value: String(item.value),
        type: 'text',
        onChange: (v: string) => { this.updateValue(item.key, v); }
      })
        .width('100%')
        .margin({ top: this.sm.getSpacing('sm') })
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
  }

  /** slider 类型：label + description + Slider + 当前值 */
  @Builder
  buildSliderItem(item: SettingItem) {
    Column() {
      Row() {
        Text(item.label)
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_primary'))
          .layoutWeight(1)
        Text(String(item.value))
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('primary'))
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Slider({
        value: Number(item.value),
        min: item.min ?? 0,
        max: item.max ?? 100,
        step: item.step ?? 1,
      })
        .width('100%')
        .margin({ top: this.sm.getSpacing('xs') })
        .onChange((v: number) => {
          // 同上：初挂/属性同步的回声值不外抛
          if (v === Number(item.value)) {
            return;
          }
          this.updateValue(item.key, v);
        })
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
  }

  /** action 类型：label + description + GlassButton */
  @Builder
  buildActionItem(item: SettingItem) {
    Row() {
      Column() {
        Text(item.label)
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_primary'))
        if (item.description) {
          Text(item.description)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: 2 })
        }
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)

      GlassButton({
        text: item.label,
        type: item.key === 'logout' ? 'danger' : 'default',
        btnSize: 'small',
        onTap: () => { this.handleAction(item.key); }
      })
    }
    .width('100%')
    .alignItems(VerticalAlign.Center)
  }
}

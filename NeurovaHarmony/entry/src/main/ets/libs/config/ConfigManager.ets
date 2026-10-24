/**
 * ConfigManager - 统一配置管理库
 *
 * 职责：管理应用所有配置项，支持类型安全的读写
 * 设计：单例模式，所有 UI 功能必须通过此库访问配置
 *
 * 用法：
 *   const cm = ConfigManager.getInstance();
 *   cm.set('api_base_url', 'http://...');
 *   const url = cm.get<string>('api_base_url', 'default');
 */

import { preferences } from '@kit.ArkData';

const PREFERENCES_NAME = 'neurova_config';

/** 默认配置项 */
const DEFAULT_CONFIG: Record<string, Object> = {
  // 服务器地址**不在编译期写死**（原值是一台开发机的局域网 IP，换网络即全体失联，
  // 且打包后改不了）。默认留空 = 尚未配对过任何服务器；地址只来自两条真路：
  //   1) 扫码后 resolve 换回来的那一条（PairingPage 写入并持久化）
  //   2) 用户在「连接」页自己填的服务器档案
  // 空值在这里是**信息**，不是兜底：读它的人会明确报"还没有服务器可连"，不会蒙着连。
  api_base_url: '',
  ws_base_url: '',
  request_timeout: 30000,
  ws_reconnect_interval: 5000,
  ws_heartbeat_interval: 30000,
  app_name: 'Neurova',
  app_version: '1.0.0',
  default_language: 'zh-CN',
  default_theme: 'dark',
  debug: false,
};

export class ConfigManager {
  private static instance: ConfigManager;
  private config: Record<string, Object> = {};
  private prefs: preferences.Preferences | null = null;

  private constructor() {
    // 私有构造，强制单例
  }

  /**
   * 把当前配置落到真装配点：HTTP 的 baseUrl ＋ 持久化。
   *
   * `HttpClient.setBaseUrl()` 与 `saveToPreferences()` 都早已实装，但**生产代码里无人调用**
   * ——于是换过地址后重开 App 又回落到默认值（AGENTS §2 的"写了没人读"断点）。
   * 这一条就是那个缺失的调用者：配对成功、切换服务器档案、启动恢复，三处都走它。
   */
  async applyServerProfile(apiBaseUrl: string, context: Context): Promise<void> {
    this.set<string>('api_base_url', apiBaseUrl);
    // ws_base_url 不在这里猜：它由配对流程 resolve 回来后写进 AuthStore——服务器地址会漂，
    // 存成一份配置就会陈旧（正是本案要摆脱的那个形状）。这里只落 HTTP 侧那条稳定前缀。
    if (!this.prefs) {
      this.prefs = await preferences.getPreferences(context, PREFERENCES_NAME);
    }
    await this.saveToPreferences();
  }

  /** 获取单例实例 */
  static getInstance(): ConfigManager {
    if (!ConfigManager.instance) {
      ConfigManager.instance = new ConfigManager();
    }
    return ConfigManager.instance;
  }

  /** 初始化默认配置 */
  initDefaults(): void {
    for (const key in DEFAULT_CONFIG) {
      if (!this.config.hasOwnProperty(key)) {
        this.config[key] = DEFAULT_CONFIG[key];
      }
    }
  }

  /** 读取配置值，不存在则返回 defaultValue */
  get<T>(key: string, defaultValue: T): T {
    const value = this.config[key];
    if (value === undefined || value === null) {
      return defaultValue;
    }
    return value as T;
  }

  /** 写入配置值 */
  set<T>(key: string, value: T): void {
    this.config[key] = value as Object;
  }

  /** 获取所有配置 */
  getAll(): Record<string, Object> {
    return { ...this.config };
  }

  /** 清空所有配置（主要用于测试） */
  clear(): void {
    this.config = {};
  }

  /** 从 Preferences 持久化加载 */
  async loadFromPreferences(context: Context): Promise<void> {
    try {
      this.prefs = await preferences.getPreferences(context, PREFERENCES_NAME);
      const all = await this.prefs.getAll();
      for (const key in all) {
        this.config[key] = all[key];
      }
    } catch (e) {
      console.error('ConfigManager loadFromPreferences failed:', e);
    }
  }

  /** 保存到 Preferences 持久化 */
  async saveToPreferences(): Promise<void> {
    if (!this.prefs) {
      return;
    }
    try {
      for (const key in this.config) {
        await this.prefs.put(key, this.config[key]);
      }
      await this.prefs.flush();
    } catch (e) {
      console.error('ConfigManager saveToPreferences failed:', e);
    }
  }
}

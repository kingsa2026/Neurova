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
  api_base_url: 'http://192.168.10.132:9527/api/v1',
  ws_base_url: 'ws://192.168.10.132:9527/v1/mobile/ws',
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

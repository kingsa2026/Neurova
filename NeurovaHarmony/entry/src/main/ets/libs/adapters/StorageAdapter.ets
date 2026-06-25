/**
 * StorageAdapter - 存储适配层
 *
 * 职责：桥接上层与鸿蒙 @kit.ArkData preferences 模块，将统一异步读写接口
 *      转译为鸿蒙系统 Preferences API；最小封装，不含业务逻辑
 * 设计：单例模式，纯桥接层；通过 init(context) 注入 UIAbilityContext 后可用
 *
 * 用法：
 *   // EntryAbility.onCreate 中一次性初始化
 *   await StorageAdapter.getInstance().init(context);
 *   // 之后任意位置异步读写
 *   await StorageAdapter.getInstance().set('token', 'xxx');
 *   const token = await StorageAdapter.getInstance().get('token', '');
 */

import { preferences } from '@kit.ArkData';
import { common } from '@kit.AbilityKit';
import { Logger } from '../logger/Logger';
import { ErrorManager, ErrorCategory } from '../error/ErrorManager';

/** 日志标签 */
const TAG = 'StorageAdapter';

export class StorageAdapter {
  private static instance: StorageAdapter;
  /** preferences 实例，init 后赋值；未初始化时为 null */
  private prefs: preferences.Preferences | null = null;
  private logger: Logger = Logger.getInstance();
  private errors: ErrorManager = ErrorManager.getInstance();
  /** 存储名称：所有键值对落在同名 preferences 文件中 */
  private readonly STORE_NAME = 'neurova_default';

  private constructor() {}

  /** 获取单例实例 */
  static getInstance(): StorageAdapter {
    if (!StorageAdapter.instance) {
      StorageAdapter.instance = new StorageAdapter();
    }
    return StorageAdapter.instance;
  }

  /**
   * 初始化：在 EntryAbility.onCreate 中调用，传入 UIAbilityContext
   * 获取 preferences 实例并缓存到 this.prefs
   */
  async init(context: common.UIAbilityContext): Promise<void> {
    try {
      this.prefs = await preferences.getPreferences(context, { name: this.STORE_NAME });
      this.logger.info(TAG, `初始化成功 store=${this.STORE_NAME}`);
    } catch (e) {
      const err = e as Error;
      this.logger.error(TAG, `初始化失败 store=${this.STORE_NAME}`, err);
      // 上报到错误管理器，便于全局感知
      this.errors.reportError(
        'storage_init_failed',
        `存储初始化失败: ${err.message}`,
        ErrorCategory.STORAGE,
        { store: this.STORE_NAME },
      );
      throw new Error(`[StorageAdapter] init 失败 (store=${this.STORE_NAME}): ${err.message}`);
    }
  }

  /**
   * 内部前置检查：确保 prefs 已初始化
   * 所有读写方法调用前先执行此检查
   */
  private ensureReady(): void {
    if (!this.prefs) {
      throw new Error('StorageAdapter 未初始化，请先调用 init(context)');
    }
  }

  /**
   * 读取键值
   * @param key 键名
   * @param defaultValue 默认值（键不存在或类型不匹配时返回）
   */
  async get<T>(key: string, defaultValue: T): Promise<T> {
    this.ensureReady();
    try {
      // preferences.get 返回 ValueType（number|string|boolean|Array|Uint8Array），需类型断言为 T
      const v = await this.prefs!.get(key, defaultValue as preferences.ValueType);
      return v as T;
    } catch (e) {
      const err = e as Error;
      this.logger.error(TAG, `get(${key}) 失败`, err);
      this.errors.reportError(
        'storage_get_failed',
        `读取失败 key=${key}: ${err.message}`,
        ErrorCategory.STORAGE,
        { key, op: 'get' },
      );
      throw new Error(`[StorageAdapter] get ${key} 失败: ${err.message}`);
    }
  }

  /**
   * 写入键值并立即持久化到磁盘
   * @param key 键名
   * @param value 值（需为 preferences 支持的类型）
   */
  async set<T>(key: string, value: T): Promise<void> {
    this.ensureReady();
    try {
      await this.prefs!.put(key, value as preferences.ValueType);
      // put 后立即 flush，保证崩溃时数据不丢失
      await this.prefs!.flush();
    } catch (e) {
      const err = e as Error;
      this.logger.error(TAG, `set(${key}) 失败`, err);
      this.errors.reportError(
        'storage_set_failed',
        `写入失败 key=${key}: ${err.message}`,
        ErrorCategory.STORAGE,
        { key, op: 'set' },
      );
      throw new Error(`[StorageAdapter] set ${key} 失败: ${err.message}`);
    }
  }

  /**
   * 删除指定键并立即持久化
   * @param key 键名
   */
  async remove(key: string): Promise<void> {
    this.ensureReady();
    try {
      await this.prefs!.delete(key);
      await this.prefs!.flush();
    } catch (e) {
      const err = e as Error;
      this.logger.error(TAG, `remove(${key}) 失败`, err);
      this.errors.reportError(
        'storage_remove_failed',
        `删除失败 key=${key}: ${err.message}`,
        ErrorCategory.STORAGE,
        { key, op: 'remove' },
      );
      throw new Error(`[StorageAdapter] remove ${key} 失败: ${err.message}`);
    }
  }

  /**
   * 判断键是否存在
   * @param key 键名
   */
  async has(key: string): Promise<boolean> {
    this.ensureReady();
    try {
      return await this.prefs!.has(key);
    } catch (e) {
      const err = e as Error;
      this.logger.error(TAG, `has(${key}) 失败`, err);
      this.errors.reportError(
        'storage_has_failed',
        `查询失败 key=${key}: ${err.message}`,
        ErrorCategory.STORAGE,
        { key, op: 'has' },
      );
      throw new Error(`[StorageAdapter] has ${key} 失败: ${err.message}`);
    }
  }

  /**
   * 清空所有键值并立即持久化
   * 谨慎使用：会清空整个 neurova_default preferences 文件
   */
  async clear(): Promise<void> {
    this.ensureReady();
    try {
      await this.prefs!.clear();
      await this.prefs!.flush();
      this.logger.info(TAG, '已清空所有键值');
    } catch (e) {
      const err = e as Error;
      this.logger.error(TAG, 'clear 失败', err);
      this.errors.reportError(
        'storage_clear_failed',
        `清空失败: ${err.message}`,
        ErrorCategory.STORAGE,
        { op: 'clear' },
      );
      throw new Error(`[StorageAdapter] clear 失败: ${err.message}`);
    }
  }

  /**
   * 获取所有键值对
   * @returns Record<键, 值> 副本
   */
  async getAll(): Promise<Record<string, Object>> {
    this.ensureReady();
    try {
      const all = await this.prefs!.getAll();
      // preferences.getAll 返回 Record<string, ValueType>，向上转型为 Object 兼容接口
      return all as Record<string, Object>;
    } catch (e) {
      const err = e as Error;
      this.logger.error(TAG, 'getAll 失败', err);
      this.errors.reportError(
        'storage_getall_failed',
        `读取全部失败: ${err.message}`,
        ErrorCategory.STORAGE,
        { op: 'getAll' },
      );
      throw new Error(`[StorageAdapter] getAll 失败: ${err.message}`);
    }
  }

  /**
   * 立即将内存中的修改写入磁盘
   * 一般无需手动调用：set/remove/clear 已自动 flush
   * 仅在特殊场景（如直接调用 prefs.put 后）需要使用
   */
  async flush(): Promise<void> {
    this.ensureReady();
    try {
      await this.prefs!.flush();
    } catch (e) {
      const err = e as Error;
      this.logger.error(TAG, 'flush 失败', err);
      this.errors.reportError(
        'storage_flush_failed',
        `持久化失败: ${err.message}`,
        ErrorCategory.STORAGE,
        { op: 'flush' },
      );
      throw new Error(`[StorageAdapter] flush 失败: ${err.message}`);
    }
  }
}

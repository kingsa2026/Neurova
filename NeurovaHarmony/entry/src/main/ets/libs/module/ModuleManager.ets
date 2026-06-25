/**
 * ModuleManager - 统一模块加载器库
 *
 * 职责：统一管理所有核心模块的注册、加载、卸载、事件分发
 * 设计：单例模式；模块通过 ModuleInterface 契约接入；
 *      注册与加载状态分离（register 不等于 load）；
 *      事件广播对单模块异常做隔离，避免影响其他模块
 *
 * 用法：
 *   const mm = ModuleManager.getInstance();
 *   mm.register(myModule);           // 注册（未加载）
 *   await mm.load('MyModule');       // 加载（触发 onLoad）
 *   mm.emit('app:ready', {});        // 向已加载模块广播事件
 *   await mm.unload('MyModule');     // 卸载（触发 onUnload）
 *   mm.unregister('MyModule');       // 注销
 */

import { Logger } from '../logger/Logger';
import { ModuleInterface } from './ModuleInterface';

/** 模块记录：模块实例 + 加载状态 */
interface ModuleRecord {
  module: ModuleInterface;
  loaded: boolean;
}

export class ModuleManager {
  private static instance: ModuleManager;
  /** 模块名 → 模块记录 */
  private modules: Map<string, ModuleRecord> = new Map();
  private logger: Logger = Logger.getInstance();

  private constructor() {}

  static getInstance(): ModuleManager {
    if (!ModuleManager.instance) {
      ModuleManager.instance = new ModuleManager();
    }
    return ModuleManager.instance;
  }

  /** 注册模块（未加载状态）。同名模块重复注册抛出错误 */
  register(module: ModuleInterface): void {
    if (this.modules.has(module.name)) {
      throw new Error(`模块 "${module.name}" 已注册`);
    }
    this.modules.set(module.name, { module, loaded: false });
    this.logger.info('ModuleManager', `注册模块 ${module.name}@${module.version}`);
  }

  /** 注销模块。若已加载则先触发 onUnload（best-effort），再删除记录 */
  unregister(name: string): void {
    const record = this.modules.get(name);
    if (!record) {
      return;
    }
    if (record.loaded) {
      // 契约为同步：触发 onUnload 但不 await，异常隔离避免影响注销流程
      this.fireOnUnload(record);
    }
    this.modules.delete(name);
    this.logger.info('ModuleManager', `注销模块 ${name}`);
  }

  /** 是否已注册 */
  isRegistered(name: string): boolean {
    return this.modules.has(name);
  }

  /** 所有已注册模块名 */
  list(): string[] {
    return Array.from(this.modules.keys());
  }

  /** 已加载模块名 */
  listLoaded(): string[] {
    const result: string[] = [];
    this.modules.forEach((record, name) => {
      if (record.loaded) {
        result.push(name);
      }
    });
    return result;
  }

  /** 加载模块。未注册抛出错误；调用 onLoad（若存在）后置为已加载 */
  async load(name: string): Promise<void> {
    const record = this.modules.get(name);
    if (!record) {
      throw new Error(`模块 "${name}" 未注册，无法加载`);
    }
    if (record.loaded) {
      return;
    }
    if (record.module.onLoad) {
      await record.module.onLoad();
    }
    record.loaded = true;
    this.logger.info('ModuleManager', `加载模块 ${name}`);
  }

  /** 卸载模块。未注册或未加载直接返回；调用 onUnload（若存在）后置为未加载 */
  async unload(name: string): Promise<void> {
    const record = this.modules.get(name);
    if (!record) {
      return;
    }
    if (!record.loaded) {
      return;
    }
    if (record.module.onUnload) {
      await record.module.onUnload();
    }
    record.loaded = false;
    this.logger.info('ModuleManager', `卸载模块 ${name}`);
  }

  /** 是否已加载 */
  isLoaded(name: string): boolean {
    const record = this.modules.get(name);
    return record ? record.loaded : false;
  }

  /** 向所有已加载模块广播事件。单模块异常隔离，不影响其他模块 */
  emit(event: string, data: Object): void {
    this.modules.forEach((record) => {
      if (record.loaded && record.module.onEvent) {
        try {
          record.module.onEvent(event, data);
        } catch (e) {
          this.logger.error(
            'ModuleManager',
            `模块 "${record.module.name}" 处理事件 "${event}" 异常`,
            e as Error,
          );
        }
      }
    });
  }

  /** 同步触发 onUnload（用于 unregister 内部）：best-effort，异常隔离 */
  private fireOnUnload(record: ModuleRecord): void {
    if (record.module.onUnload) {
      try {
        // onUnload 返回 Promise，此处不 await（unregister 契约为同步），
        // 捕获同步异常；Promise 内异常由调用方自行处理或被忽略
        const p = record.module.onUnload();
        if (p && typeof p.then === 'function') {
          p.catch((e: Error) => {
            this.logger.error(
              'ModuleManager',
              `模块 "${record.module.name}" 异步卸载异常`,
              e,
            );
          });
        }
      } catch (e) {
        this.logger.error(
          'ModuleManager',
          `模块 "${record.module.name}" 卸载同步异常`,
          e as Error,
        );
      }
    }
    record.loaded = false;
  }
}

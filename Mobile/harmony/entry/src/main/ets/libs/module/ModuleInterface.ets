/**
 * ModuleInterface - 统一模块接口
 *
 * 职责：定义所有核心模块必须实现的接口契约
 * 设计：接口隔离原则，模块通过统一接口被 ModuleManager 加载/卸载/通信；
 *      生命周期回调（onLoad/onUnload）与事件回调（onEvent）均为可选，
 *      由模块按需实现，Manager 调用前做存在性判断
 *
 * 用法：
 *   class MyModule implements ModuleInterface {
 *     readonly name = 'MyModule';
 *     readonly version = '1.0.0';
 *     async onLoad() { /\* 初始化资源 *\/ }
 *     async onUnload() { /\* 释放资源 *\/ }
 *     onEvent(event: string, data: Object) { /\* 处理广播事件 *\/ }
 *   }
 */

/** 统一模块接口：所有核心模块必须实现 */
export interface ModuleInterface {
  /** 模块名（全局唯一标识） */
  readonly name: string;
  /** 模块版本（语义化版本号） */
  readonly version: string;
  /** 加载时回调（可选）：模块被 load 时调用，用于初始化 */
  onLoad?(): Promise<void>;
  /** 卸载时回调（可选）：模块被 unload 时调用，用于清理 */
  onUnload?(): Promise<void>;
  /** 事件处理（可选）：ModuleManager 广播事件时调用 */
  onEvent?(event: string, data: Object): void;
}

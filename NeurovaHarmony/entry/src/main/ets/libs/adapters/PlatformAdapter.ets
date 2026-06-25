/**
 * PlatformAdapter - 平台适配层
 *
 * 职责：桥接上层与鸿蒙系统平台能力（设备信息、网络状态、剪贴板、扫码），
 *      将系统 API 封装为统一同步/异步接口；最小封装，不含业务逻辑
 * 设计：单例模式，纯桥接层；屏幕尺寸由 EntryAbility 在 onWindowStageCreate
 *      时通过 setScreenSize 注入；网络类型采用异步刷新 + 同步读取缓存策略
 *
 * 用法：
 *   const platform = PlatformAdapter.getInstance();
 *   const info = platform.getDeviceInfo();
 *   const net = platform.getNetworkState();
 *   const off = platform.onNetworkChange((state) => { /* ... *\/ });
 *   off();                              // 取消订阅
 *   await platform.copyToClipboard('text');
 *   const text = await platform.getClipboardText();
 *   const code = await platform.scanQRCode();
 *
 * 事件分发（EventBus）：
 *   network:status   网络状态变化（data 为 NetworkState 对象）
 */

import { deviceInfo } from '@kit.BasicServicesKit';
import { connection } from '@kit.NetworkKit';
import { pasteboard } from '@kit.BasicServicesKit';
import { scanBarcode } from '@kit.ScanKit';
import { Logger } from '../logger/Logger';
import { EventBus } from '../bus/EventBus';
import { ErrorManager, ErrorCategory } from '../error/ErrorManager';

/** 日志标签 */
const TAG = 'PlatformAdapter';

/** 设备信息 */
export interface DeviceInfo {
  brand: string;          // 设备品牌
  model: string;          // 设备型号
  osVersion: string;      // 系统版本
  osName: string;         // 系统名称 'harmony'
  apiVersion: number;     // API 版本
  screenW: number;        // 屏幕宽度 vp
  screenH: number;        // 屏幕高度 vp
}

/** 网络状态 */
export interface NetworkState {
  type: 'wifi' | 'cellular' | 'ethernet' | 'none';
  isConnected: boolean;
}

/** 网络类型枚举（内部缓存值） */
type NetworkType = 'wifi' | 'cellular' | 'ethernet' | 'none';

export class PlatformAdapter {
  private static instance: PlatformAdapter;
  private logger: Logger = Logger.getInstance();
  private bus: EventBus = EventBus.getInstance();
  private errors: ErrorManager = ErrorManager.getInstance();

  /** 屏幕宽度（vp），由 setScreenSize 设置，未设置时为 0 */
  private screenW: number = 0;
  /** 屏幕高度（vp），由 setScreenSize 设置，未设置时为 0 */
  private screenH: number = 0;
  /** 网络类型缓存：由网络变化监听器异步刷新，初始 'none' */
  private cachedNetworkType: NetworkType = 'none';
  /** 已注册的网络变化回调列表 */
  private networkCallbacks: Array<(state: NetworkState) => void> = [];
  /** 鸿蒙网络连接对象，用于注册/注销系统网络事件；无订阅者时为 null */
  private netConnection: connection.NetConnection | null = null;

  private constructor() {}

  /** 获取单例实例 */
  static getInstance(): PlatformAdapter {
    if (!PlatformAdapter.instance) {
      PlatformAdapter.instance = new PlatformAdapter();
    }
    return PlatformAdapter.instance;
  }

  /**
   * 设置屏幕尺寸：由 EntryAbility.onWindowStageCreate 中获取窗口属性后调用
   * @param w 宽度（vp）
   * @param h 高度（vp）
   */
  setScreenSize(w: number, h: number): void {
    this.screenW = w;
    this.screenH = h;
    this.logger.info(TAG, `屏幕尺寸已设置: ${w}x${h}`);
  }

  /**
   * 获取设备信息（同步）
   * 直接读取 deviceInfo 模块；屏幕尺寸依赖 setScreenSize 先注入，未设置时返回 0
   * 异常时返回兜底默认值，保证上层不崩溃
   */
  getDeviceInfo(): DeviceInfo {
    try {
      return {
        brand: deviceInfo.brand,
        model: deviceInfo.deviceModel,
        osVersion: deviceInfo.osVersion,
        osName: 'harmony',
        apiVersion: deviceInfo.apiVersion,
        screenW: this.screenW,
        screenH: this.screenH,
      };
    } catch (e) {
      const err = e as Error;
      this.logger.error(TAG, '获取设备信息失败', err);
      this.errors.reportError(
        'platform_device_info_failed',
        `获取设备信息失败: ${err.message}`,
        ErrorCategory.UNKNOWN,
        { op: 'getDeviceInfo' },
      );
      // 返回兜底默认值，避免上层因取设备信息失败而崩溃
      return {
        brand: 'unknown',
        model: 'unknown',
        osVersion: 'unknown',
        osName: 'harmony',
        apiVersion: 0,
        screenW: 0,
        screenH: 0,
      };
    }
  }

  /**
   * 获取当前网络状态（同步）
   * 连通性使用 connection.hasDefaultNetSync() 同步判断；
   * 类型字段取缓存值（由网络变化监听器异步刷新），未刷新时为 'none'
   * 若已连接但类型未知，会在后台异步触发一次类型刷新
   */
  getNetworkState(): NetworkState {
    try {
      const isConnected: boolean = connection.hasDefaultNetSync();
      if (!isConnected) {
        return { type: 'none', isConnected: false };
      }
      // 已连接但缓存类型为 'none'：后台异步刷新一次（不阻塞当前同步调用）
      if (this.cachedNetworkType === 'none') {
        this.refreshNetworkType().catch((e: Error) => {
          this.logger.warn(TAG, `后台刷新网络类型失败: ${e.message}`);
        });
      }
      return { type: this.cachedNetworkType, isConnected: true };
    } catch (e) {
      const err = e as Error;
      this.logger.error(TAG, '获取网络状态失败', err);
      return { type: 'none', isConnected: false };
    }
  }

  /**
   * 注册网络变化监听
   * @param callback 网络变化回调，参数为最新 NetworkState
   * @returns 取消订阅函数；调用后移除该回调，当无其他订阅者时自动注销系统监听
   */
  onNetworkChange(callback: (state: NetworkState) => void): () => void {
    this.networkCallbacks.push(callback);

    // 首个订阅者加入时，注册系统网络监听
    if (this.networkCallbacks.length === 1) {
      this.registerSystemNetListener();
    }

    return () => {
      const idx = this.networkCallbacks.indexOf(callback);
      if (idx >= 0) {
        this.networkCallbacks.splice(idx, 1);
      }
      // 无更多订阅者时注销系统监听，避免资源泄漏
      if (this.networkCallbacks.length === 0) {
        this.unregisterSystemNetListener();
      }
    };
  }

  /**
   * 复制文本到系统剪贴板
   * @param text 待复制的文本
   */
  async copyToClipboard(text: string): Promise<void> {
    try {
      const clipboard = pasteboard.getSystemPasteboard();
      const pasteData = pasteboard.createData(pasteboard.MIMETYPE_TEXT_PLAIN, text);
      await clipboard.setData(pasteData);
      this.logger.debug(TAG, `已复制 ${text.length} 字符到剪贴板`);
    } catch (e) {
      const err = e as Error;
      this.logger.error(TAG, '复制到剪贴板失败', err);
      this.errors.reportError(
        'platform_clipboard_set_failed',
        `复制到剪贴板失败: ${err.message}`,
        ErrorCategory.UNKNOWN,
        { op: 'copyToClipboard' },
      );
      throw new Error(`[PlatformAdapter] copyToClipboard 失败: ${err.message}`);
    }
  }

  /**
   * 从系统剪贴板获取文本
   * @returns 剪贴板中的文本；空剪贴板或非文本类型时返回空字符串
   */
  async getClipboardText(): Promise<string> {
    try {
      const clipboard = pasteboard.getSystemPasteboard();
      const pasteData = await clipboard.getData();
      if (!pasteData) {
        return '';
      }
      // getPrimaryText 返回 string，无文本时返回空字符串
      const text = pasteData.getPrimaryText();
      return text ?? '';
    } catch (e) {
      const err = e as Error;
      this.logger.error(TAG, '获取剪贴板文本失败', err);
      this.errors.reportError(
        'platform_clipboard_get_failed',
        `获取剪贴板文本失败: ${err.message}`,
        ErrorCategory.UNKNOWN,
        { op: 'getClipboardText' },
      );
      throw new Error(`[PlatformAdapter] getClipboardText 失败: ${err.message}`);
    }
  }

  /**
   * 调用系统扫码能力
   * @returns 扫码结果字符串（ScanResult.originalValue）
   * 异常（用户取消、权限拒绝、无相机等）时抛 Error
   */
  async scanQRCode(): Promise<string> {
    try {
      // 构建扫码选项：识别所有类型条码
      const options: scanBarcode.ScanOptions = {
        scanTypes: [scanBarcode.ScanType.ALL],
      };
      const result = await scanBarcode.scan(options);
      // ScanResult.originalValue 为原始扫码内容
      const value = result.originalValue;
      if (!value) {
        throw new Error('扫码结果为空');
      }
      this.logger.debug(TAG, `扫码成功: ${value.slice(0, 100)}`);
      return value;
    } catch (e) {
      const err = e as Error;
      this.logger.error(TAG, '扫码失败', err);
      this.errors.reportError(
        'platform_scan_failed',
        `扫码失败: ${err.message}`,
        ErrorCategory.UNKNOWN,
        { op: 'scanQRCode' },
      );
      throw new Error(`[PlatformAdapter] scanQRCode 失败: ${err.message}`);
    }
  }

  // ==================== 以下为内部私有方法 ====================

  /**
   * 注册系统网络连接监听
   * 监听 netAvailable / netLost / netCapabilitiesChange 事件，
   * 触发时调用 dispatchNetworkChange 派发给所有订阅者并 emit EventBus
   */
  private registerSystemNetListener(): void {
    try {
      this.netConnection = connection.createNetConnection();

      // 网络可用
      this.netConnection.on('netAvailable', () => {
        this.logger.info(TAG, '系统事件：网络可用');
        this.dispatchNetworkChange(true);
      });
      // 网络丢失
      this.netConnection.on('netLost', () => {
        this.logger.info(TAG, '系统事件：网络丢失');
        this.cachedNetworkType = 'none';
        this.dispatchNetworkChange(false);
      });
      // 网络能力变化（如 WiFi 切到蜂窝）
      this.netConnection.on('netCapabilitiesChange', () => {
        this.logger.info(TAG, '系统事件：网络能力变化');
        this.dispatchNetworkChange(true);
      });

      // 注册到系统，开始接收事件
      this.netConnection.register(() => {
        this.logger.info(TAG, '网络监听已注册到系统');
      });
    } catch (e) {
      const err = e as Error;
      this.logger.error(TAG, '注册系统网络监听失败', err);
      this.errors.reportError(
        'platform_net_register_failed',
        `注册网络监听失败: ${err.message}`,
        ErrorCategory.NETWORK,
        { op: 'registerSystemNetListener' },
      );
    }
  }

  /** 注销系统网络连接监听，释放资源 */
  private unregisterSystemNetListener(): void {
    if (!this.netConnection) {
      return;
    }
    try {
      this.netConnection.unregister(() => {
        this.logger.info(TAG, '网络监听已从系统注销');
      });
    } catch (e) {
      // 注销失败不抛出，仅警告：避免取消订阅路径上抛错影响调用方
      this.logger.warn(TAG, `注销系统网络监听失败: ${(e as Error).message}`);
    }
    this.netConnection = null;
  }

  /**
   * 派发网络变化事件
   * 先异步刷新网络类型缓存，再回调所有订阅者，最后 emit EventBus
   * @param isConnected 当前是否连接
   */
  private async dispatchNetworkChange(isConnected: boolean): Promise<void> {
    let state: NetworkState;
    if (isConnected) {
      // 已连接：异步获取详细状态以填充 type 字段
      state = await this.buildNetworkStateAsync();
    } else {
      // 未连接：直接返回离线状态
      state = { type: 'none', isConnected: false };
    }

    // 调用所有注册的回调（每个回调异常隔离，避免相互影响）
    const snapshot = this.networkCallbacks.slice();
    for (const cb of snapshot) {
      try {
        cb(state);
      } catch (e) {
        this.logger.error(TAG, '网络变化回调执行异常', e as Error);
      }
    }

    // 通过 EventBus 广播，便于非直接订阅方感知
    this.bus.emit('network:status', state as Object);
  }

  /**
   * 异步构建完整网络状态（含类型）
   * 内部调用 getDefaultNet + getNetCapabilities 获取承载类型
   */
  private async buildNetworkStateAsync(): Promise<NetworkState> {
    try {
      const hasNet: boolean = connection.hasDefaultNetSync();
      if (!hasNet) {
        this.cachedNetworkType = 'none';
        return { type: 'none', isConnected: false };
      }
      const netHandle = await connection.getDefaultNet();
      if (!netHandle || !netHandle.netId) {
        // netId 为 0 表示无默认网络
        this.cachedNetworkType = 'none';
        return { type: 'none', isConnected: true };
      }
      const capabilities = await connection.getNetCapabilities(netHandle);
      const type = this.mapBearerType(capabilities);
      this.cachedNetworkType = type;
      return { type, isConnected: true };
    } catch (e) {
      const err = e as Error;
      this.logger.warn(TAG, `异步构建网络状态失败: ${err.message}`);
      this.cachedNetworkType = 'none';
      return { type: 'none', isConnected: true };
    }
  }

  /**
   * 异步刷新网络类型缓存（不返回值，仅更新 cachedNetworkType）
   * 用于 getNetworkState() 首次调用时后台预热缓存
   */
  private async refreshNetworkType(): Promise<void> {
    await this.buildNetworkStateAsync();
  }

  /**
   * 将 NetCapabilities.bearerTypes 映射为简化类型字符串
   * 优先匹配 wifi > cellular > ethernet；无匹配返回 'none'
   * @param capabilities 网络能力对象
   */
  private mapBearerType(capabilities: connection.NetCapabilities): NetworkType {
    try {
      const bearerTypes = capabilities.bearerTypes;
      if (!bearerTypes || bearerTypes.length === 0) {
        return 'none';
      }
      for (const t of bearerTypes) {
        if (t === connection.NetBearType.BEAR_WIFI) {
          return 'wifi';
        }
      }
      for (const t of bearerTypes) {
        if (t === connection.NetBearType.BEAR_CELLULAR) {
          return 'cellular';
        }
      }
      for (const t of bearerTypes) {
        if (t === connection.NetBearType.BEAR_ETHERNET) {
          return 'ethernet';
        }
      }
      return 'none';
    } catch (e) {
      this.logger.warn(TAG, `映射网络承载类型失败: ${(e as Error).message}`);
      return 'none';
    }
  }
}

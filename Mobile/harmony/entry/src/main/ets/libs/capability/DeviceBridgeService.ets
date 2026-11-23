/**
 * 设备桥服务——鸿蒙端装配（2026-11-23 计划卡 H1/H2/H3）。
 *
 * 应用级常驻：监听总线上的 device:execute / device:cancel 帧 → 派发器执行 →
 * 经 WebSocketAdapter 同一连接回 device:result；ws:connected 时上报
 * device:hello 能力快照。与聊天页解耦——连接生命周期不再跟随页面栈
 * （H1：ChatPage 离页不再断连，本服务即应用级消费方）。
 */
import { common } from '@kit.AbilityKit';
import { EventBus } from '../bus/EventBus';
import { WebSocketAdapter } from '../adapters/WebSocketAdapter';
import { Logger } from '../logger/Logger';
import { DeviceBridgeDispatcher, DeviceActionExecutor } from './DeviceBridgeDispatcher';
import {
  ClipboardReadExecutor,
  ClipboardWriteExecutor,
  DeviceEnvExecutor,
  OpenUrlExecutor,
} from './DeviceCapabilityExecutors';

const TAG = 'DeviceBridgeService';

/** P0 对外宣称的能力子集（app_list/notification_read 因平台权限不宣称） */
const CLAIMED_CAPABILITIES: string[] =
  ['open_url', 'clipboard_read', 'clipboard_write', 'device_env'];

export class DeviceBridgeService {
  private static instance?: DeviceBridgeService;
  private logger: Logger = Logger.getInstance();
  private bus: EventBus = EventBus.getInstance();
  private ws: WebSocketAdapter = WebSocketAdapter.getInstance();
  private dispatcher?: DeviceBridgeDispatcher;
  private executeHandler?: (data: Object) => void;
  private connectedHandler?: (data: Object) => void;

  private constructor() {
  }

  static getInstance(): DeviceBridgeService {
    if (DeviceBridgeService.instance === undefined) {
      DeviceBridgeService.instance = new DeviceBridgeService();
    }
    return DeviceBridgeService.instance;
  }

  /** EntryAbility 启动时装配一次（传入 UIAbility 上下文供 startAbility 用） */
  init(context: common.UIAbilityContext): void {
    if (this.dispatcher !== undefined) {
      return;
    }
    const executors: DeviceActionExecutor[] = [
      new OpenUrlExecutor(context),
      new ClipboardReadExecutor(),
      new ClipboardWriteExecutor(),
      new DeviceEnvExecutor(),
    ];
    this.dispatcher = new DeviceBridgeDispatcher(executors);

    this.connectedHandler = (_data: Object) => {
      this.sendHello();
    };
    this.executeHandler = (data: Object) => {
      this.handleFrame(data as Record<string, Object>);
    };
    this.bus.on('ws:connected', this.connectedHandler);
    this.bus.on('device:execute', this.executeHandler);
    this.logger.info(TAG, '设备桥服务已装配');
  }

  private handleFrame(frame: Record<string, Object>): void {
    const dispatcher = this.dispatcher;
    if (dispatcher === undefined) {
      return;
    }
    dispatcher.handleFrame(frame).then((result) => {
      if (result !== null) {
        this.ws.send(JSON.stringify(result));
      }
    }).catch((e: Error) => {
      this.logger.error(TAG, `设备命令处理失败: ${e.message}`);
    });
  }

  private sendHello(): void {
    const hello: Record<string, Object> = {
      'type': 'device:hello',
      'platform': 'harmony',
      'protocol_version': 1,
      'capabilities': CLAIMED_CAPABILITIES,
      'app_state': 'foreground',
    };
    this.ws.send(JSON.stringify(hello));
    this.logger.info(TAG, 'device:hello 已上报');
  }
}

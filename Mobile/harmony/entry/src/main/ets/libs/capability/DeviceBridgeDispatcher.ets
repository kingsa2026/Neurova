/**
 * 设备桥命令派发器（2026-11-23 计划卡 H3；逻辑与安卓 DeviceCommandDispatcher 同构）。
 *
 * - 动作路由到对应执行器；未登记动作结构化拒绝（unsupported_method）；
 * - 后台闸：app_state != foreground 时 BACKGROUND_UNSAFE 动作直接拒绝
 *   （background_unavailable）——能力协商的端侧运行半边；
 * - 同 command_id 重放不重复执行（断线重连重放防线）：已收敛命令的结果帧
 *   进有界缓存，重放原样回执并附 replayed=true；
 * - 纯逻辑无 Kit 依赖：可在 Node 直跑 harness 里红绿自检。
 */

export interface DeviceExecuteOutcome {
  status: string;                       // 'ok' | 'error'
  data: Record<string, Object>;
  errorCode?: string;
  errorMessage?: string;
}

export interface DeviceActionExecutor {
  action: string;
  execute(payload: Record<string, Object>): Promise<DeviceExecuteOutcome>;
}

/** 后台不可靠动作（对齐后端 router.BACKGROUND_UNSAFE_ACTIONS） */
export const BACKGROUND_UNSAFE_ACTIONS: string[] =
  ['open_url', 'open_app', 'clipboard_read', 'screen_observe', 'screen_gesture'];

export function okOutcome(data?: Record<string, Object>): DeviceExecuteOutcome {
  const payload: Record<string, Object> =
    data !== undefined ? data : ({} as Record<string, Object>);
  return { status: 'ok', data: payload } as DeviceExecuteOutcome;
}

export function errorOutcome(code: string, message: string): DeviceExecuteOutcome {
  const out: DeviceExecuteOutcome = {
    status: 'error',
    data: {} as Record<string, Object>,
  };
  out.errorCode = code;
  out.errorMessage = message;
  return out;
}

/** 设备命令失败回执的 error 段（词表对齐后端 action_result 拒绝码） */
interface DeviceErrorPayload {
  code: string;
  message: string;
}

export class DeviceBridgeDispatcher {
  private executors: Map<string, DeviceActionExecutor> = new Map();
  private appStateProvider: () => string;
  private settled: Map<string, Record<string, Object>> = new Map();
  private readonly dedupCapacity: number;

  constructor(executors: DeviceActionExecutor[],
              appStateProvider: () => string = (): string => 'foreground',
              dedupCapacity: number = 128) {
    this.appStateProvider = appStateProvider;
    this.dedupCapacity = dedupCapacity;
    for (const executor of executors) {
      this.executors.set(executor.action, executor);
    }
  }

  /**
   * 设备桥帧入口：非 device:execute 返回 null（调用方继续走既有分发）；
   * 缺 command_id/action 的坏帧回 missing_params 回执（不猜不吞）。
   */
  async handleFrame(frame: Record<string, Object>): Promise<Record<string, Object> | null> {
    const type = String(frame['type'] ?? '');
    if (type !== 'device:execute') {
      return null;
    }
    const commandId = String(frame['command_id'] ?? '');
    const action = String(frame['action'] ?? '');
    if (commandId.length === 0 || action.length === 0) {
      return this.buildResult(commandId, 'error', {},
        'missing_params', 'device:execute 缺 command_id/action');
    }
    const rawPayload = frame['payload'];
    const payload: Record<string, Object> =
      (rawPayload !== null && rawPayload !== undefined && typeof rawPayload === 'object')
        ? rawPayload as Record<string, Object> : {};
    const intent = String(frame['intent'] ?? '');
    return this.handleExecute(commandId, action, payload, intent);
  }

  async handleExecute(commandId: string, action: string,
                      payload: Record<string, Object>, intent: string = ''):
    Promise<Record<string, Object>> {
    // 重放防线：同 command_id 已收敛 → 原样回执 + replayed 标记，不重复执行
    const previous = this.settled.get(commandId);
    if (previous !== undefined) {
      const replayed: Record<string, Object> = {};
      const keys = Object.keys(previous);
      for (const key of keys) {
        replayed[key] = previous[key];
      }
      replayed['replayed'] = true;
      return replayed;
    }

    const result = await this.executeNow(commandId, action, payload);
    this.remember(commandId, result);
    return result;
  }

  private async executeNow(commandId: string, action: string,
                           payload: Record<string, Object>):
    Promise<Record<string, Object>> {
    const appState = this.appStateProvider().length > 0 ? this.appStateProvider() : 'foreground';
    if (appState !== 'foreground' && BACKGROUND_UNSAFE_ACTIONS.indexOf(action) >= 0) {
      return this.buildResult(commandId, 'error', {},
        'background_unavailable', '该动作在设备后台不可靠，需要回到前台执行');
    }
    const executor = this.executors.get(action);
    if (executor === undefined) {
      return this.buildResult(commandId, 'error', {},
        'unsupported_method', `端上未实现该能力：${action}`);
    }
    let outcome: DeviceExecuteOutcome;
    try {
      outcome = await executor.execute(payload);
    } catch (e) {
      const err = e as Error;
      return this.buildResult(commandId, 'error', {},
        'executor_error', err.message ?? '执行失败');
    }
    if (outcome.status === 'ok') {
      return this.buildResult(commandId, 'ok', outcome.data, '', '');
    }
    return this.buildResult(commandId, 'error', outcome.data,
      outcome.errorCode ?? 'executor_error', outcome.errorMessage ?? '执行失败');
  }

  private remember(commandId: string, result: Record<string, Object>): void {
    this.settled.set(commandId, result);
    if (this.settled.size > this.dedupCapacity) {
      // 有界 FIFO：删最早写入的一条（重放窗口按命令数计）
      const first = this.settled.keys().next();
      if (!first.done) {
        this.settled.delete(first.value);
      }
    }
  }

  private buildResult(commandId: string, status: string,
                      data: Record<string, Object>,
                      errorCode: string, errorMessage: string): Record<string, Object> {
    const result: Record<string, Object> = {
      'type': 'device:result',
      'command_id': commandId,
      'status': status,
      'data': data,
    };
    if (errorCode.length > 0) {
      const error: DeviceErrorPayload = { 'code': errorCode, 'message': errorMessage };
      result['error'] = error;
    }
    return result;
  }
}

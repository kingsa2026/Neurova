/**
 * 设备桥能力执行器——鸿蒙端实现（2026-11-23 计划卡 H3）。
 *
 * P0 快路径子集：open_url / clipboard_read / clipboard_write / device_env。
 * app_list 依赖 bundleManager 对三方应用的可见性收口（GET_BUNDLE_INFO_PRIVILEGED
 * 拿不到），P0 不宣称；notification_read 需 system_basic 级权限（平台硬约束），
 * 鸿蒙端不做——两端能力分工见计划 §3.4。
 */
import { common } from '@kit.AbilityKit';
import { connection } from '@kit.NetworkKit';
import { deviceInfo } from '@kit.BasicServicesKit';
import batteryInfo from '@ohos.batteryInfo';
import { DeviceActionExecutor, DeviceExecuteOutcome, errorOutcome, okOutcome } from './DeviceBridgeDispatcher';
import { PlatformAdapter } from '../adapters/PlatformAdapter';

function textOf(payload: Record<string, Object>, key: string): string {
  const raw = payload[key];
  if (raw === null || raw === undefined) {
    return '';
  }
  return String(raw);
}

/** open_url：startAbility 拉起浏览器/默认打开方式（前台态才可靠，后台闸在派发器） */
export class OpenUrlExecutor implements DeviceActionExecutor {
  readonly action = 'open_url';
  private context: common.UIAbilityContext;

  constructor(context: common.UIAbilityContext) {
    this.context = context;
  }

  async execute(payload: Record<string, Object>): Promise<DeviceExecuteOutcome> {
    const url = textOf(payload, 'url').trim();
    const lowered = url.toLowerCase();
    if (!lowered.startsWith('http://') && !lowered.startsWith('https://')) {
      return errorOutcome('missing_params', 'url 必须是 http/https 地址');
    }
    const want: Record<string, Object> = {
      'uri': url,
      'action': 'ohos.want.action.viewData',
    };
    await this.context.startAbility(want);
    const data: Record<string, Object> = { 'url': url };
    return okOutcome(data);
  }
}

/** clipboard_read：系统剪贴板文本（PlatformAdapter 单源封装） */
export class ClipboardReadExecutor implements DeviceActionExecutor {
  readonly action = 'clipboard_read';

  async execute(payload: Record<string, Object>): Promise<DeviceExecuteOutcome> {
    const text = await PlatformAdapter.getInstance().getClipboardText();
    const data: Record<string, Object> = { 'text': text };
    return okOutcome(data);
  }
}

/** clipboard_write：写系统剪贴板文本 */
export class ClipboardWriteExecutor implements DeviceActionExecutor {
  readonly action = 'clipboard_write';

  async execute(payload: Record<string, Object>): Promise<DeviceExecuteOutcome> {
    const text = textOf(payload, 'text');
    if (text.length === 0) {
      return errorOutcome('missing_params', 'text 必须是非空字符串');
    }
    await PlatformAdapter.getInstance().copyToClipboard(text);
    return okOutcome();
  }
}

/** device_env：系统版本/机型/电量/充电态/网络连通性快照 */
export class DeviceEnvExecutor implements DeviceActionExecutor {
  readonly action = 'device_env';

  async execute(payload: Record<string, Object>): Promise<DeviceExecuteOutcome> {
    // hasDefaultNetSync 与 PlatformAdapter 网络读数同一口径（同步 API）
    let online = false;
    try {
      online = connection.hasDefaultNetSync();
    } catch (e) {
      online = false;
    }
    const data: Record<string, Object> = {
      'os_version': deviceInfo.osFullName,
      'model': deviceInfo.productModel,
      'battery': batteryPercent(),
      'network_online': online,
    };
    return okOutcome(data);
  }
}

function batteryPercent(): number {
  try {
    const soc = Number(batteryInfo.batterySOC ?? -1);
    return soc >= 0 && soc <= 100 ? soc / 100.0 : -1.0;
  } catch (e) {
    return -1.0;
  }
}

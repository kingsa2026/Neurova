/**
 * PairingProtocol - 配对与通道状态字面量（三处单源之一）
 *
 * 权威侧是后端 `neurova/tunnel/protocol.py`；Web 侧同名契约在
 * `NeurUI/src/api/contracts/pairingStates.ts`。三份集合相等由
 * `tests/unit/test_tunnelStateEnumSingleSource.py` 逐条咬合。
 *
 * 为什么 App 也要持一份：徽标与文案按状态取词。若只在前端硬写字符串，
 * 服务端漂出一个新态时 App 会把它画成「等待扫码」这类看着正常、其实是错的读数。
 * 不生成代码、不加同步脚本（教义第 6 条）。
 */

/** M1 · 配对码生命周期（一次性凭据） */
export const PAIRING_CODE_STATES: string[] = [
  'pending', 'scanned', 'confirmed', 'used', 'expired', 'revoked', 'aborted',
];

/** M1b · 在册设备生命周期（长期设备；与一次性配对码分开） */
export const DEVICE_REGISTRY_STATES: string[] = [
  'unpaired', 'paired', 'online', 'offline', 'dormant', 'revoked',
];

/** M2 · 通道/隧道 */
export const TUNNEL_STATES: string[] = ['disabled', 'probing', 'via_relay', 'relay_down', 'evicted'];

/** 地址来源（与隧道态可并存：局域网内 direct 与 via_relay 同时成立是常态） */
export const ADDRESS_SOURCES: string[] = ['direct', 'via_relay'];

/** M3 · 设备连接会话 */
export const DEVICE_CONNECTION_STATES: string[] = [
  'idle', 'reauthing', 'connecting', 'authed', 'streaming', 'reconnecting', 'failed', 'closed',
];

/** 会话失败分型原因（两端文案按这些取词，不各自意译） */
export const CONNECTION_FAILURE_REASONS: string[] = [
  'auth_credential_mismatch',
  'device_deregistered',
  'network_unreachable',
  'relay_not_registered',
  'tunnel_not_ready',
  'max_reconnect_exhausted',
];

/**
 * 解析二维码载荷。
 *
 * 载荷形状在 `protocol.pairingQrPayload()` 定义：`neurova://pair?ref=<高熵一次性引用>`，
 * **刻意不含任何 host**——「谁」与「在哪」分开，地址漂移不得让已发的码作废。
 * 旧形（裸 `ws://…?code=XXXXXX`）靠子串巧合对得上，那是一条 nobody owns 的约定，
 * 本页不再自己抦正则，解析面只在这一处。
 */
export interface PairingPayload {
  ref: string;
  shortCode: string;
}

/** 从扫描结果取出 ref / 短码；两者都取不到时返回 null（调用方负责分型报错） */
export function parsePairingPayload(scanned: string): PairingPayload | null {
  const refMatch = scanned.match(/[?&]ref=([0-9a-zA-Z]{22})/);
  if (refMatch) {
    return { ref: refMatch[1], shortCode: '' };
  }
  const codeMatch = scanned.match(/[?&]code=([0-9]{6})/);
  if (codeMatch) {
    return { ref: '', shortCode: codeMatch[1] };
  }
  return null;
}

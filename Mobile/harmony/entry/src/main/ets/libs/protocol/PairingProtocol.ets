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
 * 二维码载荷解析不在这里：真单源是 `libs/protocol/PairingPayload.ets` 的
 * `PairingPayload.parse()`（PairingPage 在用）。本文件曾并存一份重复的
 * 解析函数 + 同名 interface（全仓零调用），属同功能第二实现，
 * 按先比后合退役（审计 3.8-8；存活判据见 R2 台账）。
 */

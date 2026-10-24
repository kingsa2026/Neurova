/**
 * 配对与通道状态字面量——三处单源之一（另两处：`neurova/tunnel/protocol.py` 为权威侧，
 * `NeurovaHarmony/.../libs/protocol/PairingProtocol.ets`）。
 *
 * 为什么在 TS 里再抄一份同名字面量：徽标与文案要按状态取词，而前端不能等服务端
 * 漂出某个词再发现画不出（本卷形态 403：判据读的对象与真装配点不同形）。
 * 三份的一致性由 `tests/unit/test_tunnelStateEnumSingleSource.py` 逐条咬合，
 * 不生成代码、不加同步脚本（教义第 6 条点名的「两边都留着、加个同步脚本」）。
 */

/** M1 · 配对码生命周期（一次性凭据） */
export const PAIRING_CODE_STATES = [
  'pending',
  'scanned',
  'confirmed',
  'used',
  'expired',
  'revoked',
  'aborted',
] as const
export type PairingCodeState = (typeof PAIRING_CODE_STATES)[number]

/** M1b · 在册设备生命周期（长期设备；与配对码分开，两套寿命不混一台机） */
export const DEVICE_REGISTRY_STATES = [
  'unpaired',
  'paired',
  'online',
  'offline',
  'dormant',
  'revoked',
] as const
export type DeviceRegistryState = (typeof DEVICE_REGISTRY_STATES)[number]

/** M2 · 通道/隧道（`direct` 是地址来源，不是这里的态，见 ADDRESS_SOURCES） */
export const TUNNEL_STATES = ['disabled', 'probing', 'via_relay', 'relay_down', 'evicted'] as const
export type TunnelState = (typeof TUNNEL_STATES)[number]

/** 地址来源与隧道态可并存：本次发码用哪个来源才是投影对象 */
export const ADDRESS_SOURCES = ['direct', 'via_relay'] as const
export type AddressSource = (typeof ADDRESS_SOURCES)[number]

/** M3 · 设备连接会话（App 侧口径，服务端回话也用它，故在此对齐） */
export const DEVICE_CONNECTION_STATES = [
  'idle',
  'reauthing',
  'connecting',
  'authed',
  'streaming',
  'reconnecting',
  'failed',
  'closed',
] as const
export type DeviceConnectionState = (typeof DEVICE_CONNECTION_STATES)[number]

/**
 * MobilePairingApi - 移动端配对 API 模块
 *
 * 对应后端 neurova/api/endpoints/mobile_pairing.py
 *
 * 真机实测（2026-11-16，OpenHarmony-7.0.0.111）：confirm/resolve/refresh 返回的是
 * **裸对象**（snake_case，无 code/data 信封，与 /auth/login 同族），例如 confirm：
 * `{success, connect_ticket, ws_url, device_secret, pairing_id, message, expires_in}`。
 * 直接透传会让页面判 `res.code === 0 && res.data` 恒假——后端明明配对成功，
 * 页面却进失败分支（错误文案还 displaying 后端的「配对成功」）。与 AuthApi 同法：
 * 在模块边界归一为 ApiResponse，并把 snake_case 映射为前端 camelCase 契约。
 */
import { HttpClient } from '../HttpClient';
import { ApiResponse, PairingInfo, PairingConfirm, PairingConfirmed, PairingResolved, PairingRefresh, PairingRefreshed } from '../../types';

/** 生成配对码请求体 */
export interface PairingGenerateRequest {
  device_name: string;
  device_type: string;
}

/** 凭一次性 ref 换取回连地址请求体 */
export interface PairingResolveRequest {
  ref: string;
}

/** 接入凭证续签请求体（后端 RefreshPairingRequest 为 snake_case） */
export interface PairingRefreshRequest {
  pairing_id: string;
  device_secret: string;
  challenge: string;
}

/** 配对状态查询响应 */
export interface PairingStatus {
  status: string;
  wsToken?: string;
  wsUrl?: string;
}

/** 裸对象判定：无信封字段（code/data），且携带目标类型的全部探针字段 */
function isBareShape(res: Object, probeKeys: string[]): boolean {
  const keys: string[] = Object.keys(res);
  if (keys.indexOf('code') !== -1 || keys.indexOf('data') !== -1) {
    return false;
  }
  for (const k of probeKeys) {
    if (keys.indexOf(k) === -1) {
      return false;
    }
  }
  return true;
}

/** 信封 message：裸对象的 message 存在则透传，否则 'ok' */
function envelopeMessage(rec: Record<string, Object>): string {
  const msg = rec['message'] as string;
  return msg ?? 'ok';
}

/** confirm 裸响应 → ApiResponse<PairingConfirmed>（connect_ticket→wsToken、ws_url→wsUrl） */
function asConfirmed(res: ApiResponse<Object>): ApiResponse<PairingConfirmed> {
  if (!isBareShape(res, ['connect_ticket', 'ws_url'])) {
    return res as Object as ApiResponse<PairingConfirmed>;
  }
  const rec = res as Object as Record<string, Object>;
  const keys: string[] = Object.keys(rec);
  const data: PairingConfirmed = {
    wsToken: rec['connect_ticket'] as string,
    wsUrl: rec['ws_url'] as string,
    expiresIn: rec['expires_in'] as number,
  };
  if (keys.indexOf('device_secret') !== -1) {
    data.deviceSecret = rec['device_secret'] as string;
  }
  if (keys.indexOf('pairing_id') !== -1) {
    data.pairingId = rec['pairing_id'] as string;
  }
  const wrapped: ApiResponse<PairingConfirmed> = { code: 0, message: envelopeMessage(rec), data: data };
  return wrapped;
}

/** resolve 裸响应 → ApiResponse<PairingResolved>（ws_url→wsUrl） */
function asResolved(res: ApiResponse<Object>): ApiResponse<PairingResolved> {
  if (!isBareShape(res, ['ws_url', 'pairing_id'])) {
    return res as Object as ApiResponse<PairingResolved>;
  }
  const rec = res as Object as Record<string, Object>;
  const data: PairingResolved = {
    wsUrl: rec['ws_url'] as string,
    pairingId: rec['pairing_id'] as string,
    expiresIn: rec['expires_in'] as number,
    status: rec['status'] as string,
  };
  const wrapped: ApiResponse<PairingResolved> = { code: 0, message: envelopeMessage(rec), data: data };
  return wrapped;
}

/** refresh 裸响应 → ApiResponse<PairingRefreshed>（connect_ticket→connectTicket） */
function asRefreshed(res: ApiResponse<Object>): ApiResponse<PairingRefreshed> {
  if (!isBareShape(res, ['connect_ticket', 'pairing_id'])) {
    return res as Object as ApiResponse<PairingRefreshed>;
  }
  const rec = res as Object as Record<string, Object>;
  const data: PairingRefreshed = {
    connectTicket: rec['connect_ticket'] as string,
    pairingId: rec['pairing_id'] as string,
    expiresIn: rec['expires_in'] as number,
  };
  const wrapped: ApiResponse<PairingRefreshed> = { code: 0, message: envelopeMessage(rec), data: data };
  return wrapped;
}

export class MobilePairingApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  /** 生成配对码（POST /mobile/pairing/generate；baseUrl 已含 /api/v1，路径禁再写 /v1） */
  async generate(deviceName: string, deviceType: string = 'mobile'): Promise<ApiResponse<PairingInfo>> {
    const body: PairingGenerateRequest = {
      device_name: deviceName,
      device_type: deviceType,
    };
    return this.client.post<PairingInfo>('/mobile/pairing/generate', body);
  }

  /** 确认配对（POST /mobile/pairing/confirm）：裸响应在边界归一 */
  async confirm(form: PairingConfirm): Promise<ApiResponse<PairingConfirmed>> {
    const res = await this.client.post<Object>('/mobile/pairing/confirm', form);
    return asConfirmed(res);
  }

  /** 扫码后凭一次性 ref 换取回连地址（POST /mobile/pairing/resolve，匿名口）：裸响应在边界归一 */
  async resolve(ref: string): Promise<ApiResponse<PairingResolved>> {
    const body: PairingResolveRequest = { ref };
    const res = await this.client.post<Object>('/mobile/pairing/resolve', body);
    return asResolved(res);
  }

  /** 接入凭证续签（POST /mobile/pairing/refresh，免回屏重扫）：裸响应在边界归一 */
  async refresh(form: PairingRefresh): Promise<ApiResponse<PairingRefreshed>> {
    // 后端 RefreshPairingRequest 只认 snake_case（pairing_id/device_secret）；
    // 2026-11-18 模拟器实测：camelCase 直传 422，续签恒被拒（误报「设备已解除」）
    const body: PairingRefreshRequest = {
      pairing_id: form.pairingId,
      device_secret: form.deviceSecret,
      challenge: form.challenge,
    };
    const res = await this.client.post<Object>('/mobile/pairing/refresh', body);
    return asRefreshed(res);
  }

  /** 检查配对状态（GET /mobile/pairing/status/:code） */
  async status(code: string): Promise<ApiResponse<PairingStatus>> {
    return this.client.get(`/mobile/pairing/status/${code}`);
  }
}

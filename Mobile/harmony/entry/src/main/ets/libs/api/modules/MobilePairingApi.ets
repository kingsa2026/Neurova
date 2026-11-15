/**
 * MobilePairingApi - 移动端配对 API 模块
 *
 * 对应后端 neurova/api/endpoints/mobile_pairing.py
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

/** 配对状态查询响应 */
export interface PairingStatus {
  status: string;
  wsToken?: string;
  wsUrl?: string;
}

export class MobilePairingApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  /** 生成配对码（POST /v1/mobile/pairing/generate） */
  async generate(deviceName: string, deviceType: string = 'mobile'): Promise<ApiResponse<PairingInfo>> {
    const body: PairingGenerateRequest = {
      device_name: deviceName,
      device_type: deviceType,
    };
    return this.client.post<PairingInfo>('/v1/mobile/pairing/generate', body);
  }

  /** 确认配对（POST /v1/mobile/pairing/confirm） */
  async confirm(form: PairingConfirm): Promise<ApiResponse<PairingConfirmed>> {
    return this.client.post<PairingConfirmed>('/v1/mobile/pairing/confirm', form);
  }

  /** 扫码后凭一次性 ref 换取回连地址（POST /v1/mobile/pairing/resolve，匿名口） */
  async resolve(ref: string): Promise<ApiResponse<PairingResolved>> {
    const body: PairingResolveRequest = { ref };
    return this.client.post<PairingResolved>('/v1/mobile/pairing/resolve', body);
  }

  /** 接入凭证续签（POST /v1/mobile/pairing/refresh，免回屏重扫） */
  async refresh(form: PairingRefresh): Promise<ApiResponse<PairingRefreshed>> {
    return this.client.post<PairingRefreshed>('/v1/mobile/pairing/refresh', form);
  }

  /** 检查配对状态（GET /v1/mobile/pairing/status/:code） */
  async status(code: string): Promise<ApiResponse<PairingStatus>> {
    return this.client.get(`/v1/mobile/pairing/status/${code}`);
  }
}

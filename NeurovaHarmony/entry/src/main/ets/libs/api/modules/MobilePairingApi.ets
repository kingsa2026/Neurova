/**
 * MobilePairingApi - 移动端配对 API 模块
 *
 * 对应后端 neurova/api/endpoints/mobile_pairing.py
 */
import { HttpClient } from '../HttpClient';
import { ApiResponse, PairingInfo, PairingConfirm, PairingConfirmed, PairingResolved, PairingRefresh, PairingRefreshed } from '../../types';

export class MobilePairingApi {
  constructor(private client: HttpClient) {}

  /** 生成配对码（POST /v1/mobile/pairing/generate） */
  async generate(deviceName: string, deviceType: string = 'mobile'): Promise<ApiResponse<PairingInfo>> {
    return this.client.post<PairingInfo>('/v1/mobile/pairing/generate', {
      device_name: deviceName,
      device_type: deviceType,
    });
  }

  /** 确认配对（POST /v1/mobile/pairing/confirm） */
  async confirm(form: PairingConfirm): Promise<ApiResponse<PairingConfirmed>> {
    return this.client.post<PairingConfirmed>('/v1/mobile/pairing/confirm', form);
  }

  /** 扫码后凭一次性 ref 换取回连地址（POST /v1/mobile/pairing/resolve，匿名口） */
  async resolve(ref: string): Promise<ApiResponse<PairingResolved>> {
    return this.client.post<PairingResolved>('/v1/mobile/pairing/resolve', { ref });
  }

  /** 接入凭证续签（POST /v1/mobile/pairing/refresh，免回屏重扫） */
  async refresh(form: PairingRefresh): Promise<ApiResponse<PairingRefreshed>> {
    return this.client.post<PairingRefreshed>('/v1/mobile/pairing/refresh', form);
  }

  /** 检查配对状态（GET /v1/mobile/pairing/status/:code） */
  async status(code: string): Promise<ApiResponse<{ status: string; wsToken?: string; wsUrl?: string }>> {
    return this.client.get(`/v1/mobile/pairing/status/${code}`);
  }
}

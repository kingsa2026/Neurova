/**
 * MobilePairingApi - 移动端配对 API 模块
 *
 * 对应后端 neurova/api/endpoints/mobile_pairing.py
 */
import { HttpClient } from '../HttpClient';
import { ApiResponse, PairingInfo, PairingConfirm, PairingConfirmed } from '../../types';

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

  /** 检查配对状态（GET /v1/mobile/pairing/status/:code） */
  async status(code: string): Promise<ApiResponse<{ status: string; wsToken?: string; wsUrl?: string }>> {
    return this.client.get(`/v1/mobile/pairing/status/${code}`);
  }
}

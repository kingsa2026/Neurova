/**
 * PushApi - 移动端推送令牌 API 模块
 *
 * 对应后端 neurova/api/endpoints/mobile_push.py（设计方案 §8.4 S-3）。
 * 推送只发信令（notificationId/type），正文由 App 拉取通知接口。
 */
import { HttpClient } from '../HttpClient';
import { ApiResponse } from '../../types';

/** 推送令牌上报请求体 */
export interface PushTokenUpsertRequest {
  platform: string;
  push_token: string;
  device_id: string;
}

export class PushApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  /** 上报/更新设备推送令牌（PUT /v1/mobile/push/push-tokens，登录态） */
  async upsert(platform: string, pushToken: string, deviceId: string): Promise<ApiResponse<Object>> {
    const body: PushTokenUpsertRequest = {
      platform: platform,
      push_token: pushToken,
      device_id: deviceId,
    };
    return this.client.put<Object>('/mobile/push/push-tokens', body);
  }

  /** 注销设备推送令牌（DELETE /mobile/push/push-tokens/{deviceId}，登出时调用；baseUrl 已含 /api/v1，勿再写 /v1——P1-30） */
  async remove(deviceId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/mobile/push/push-tokens/${deviceId}`);
  }
}

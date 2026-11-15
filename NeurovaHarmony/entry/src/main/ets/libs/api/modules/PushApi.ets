/**
 * PushApi - 移动端推送令牌 API 模块
 *
 * 对应后端 neurova/api/endpoints/mobile_push.py（设计方案 §8.4 S-3）。
 * 推送只发信令（notificationId/type），正文由 App 拉取通知接口。
 */
import { HttpClient } from '../HttpClient';
import { ApiResponse } from '../../types';

export class PushApi {
  constructor(private client: HttpClient) {}

  /** 上报/更新设备推送令牌（PUT /v1/mobile/push/push-tokens，登录态） */
  async upsert(platform: string, pushToken: string, deviceId: string): Promise<ApiResponse<Object>> {
    return this.client.put<Object>('/v1/mobile/push/push-tokens', {
      platform: platform,
      push_token: pushToken,
      device_id: deviceId,
    });
  }

  /** 注销设备推送令牌（DELETE /v1/mobile/push/push-tokens/{deviceId}，登出时调用） */
  async remove(deviceId: string): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/v1/mobile/push/push-tokens/${deviceId}`);
  }
}

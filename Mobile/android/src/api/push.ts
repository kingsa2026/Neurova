/** 推送令牌上报/注销（设计方案 §8.4 S-3；后端 /api/v1/mobile/push/*） */
import { apiPost, http } from '@/utils/http'

export type PushPlatform = 'android' | 'harmony'

export async function upsertPushToken(
  platform: PushPlatform,
  pushToken: string,
  deviceId: string,
): Promise<void> {
  await apiPost('/mobile/push/push-tokens', {
    platform,
    push_token: pushToken,
    device_id: deviceId,
  })
}

export async function deletePushToken(deviceId: string): Promise<void> {
  await http.delete(`/mobile/push/push-tokens/${encodeURIComponent(deviceId)}`)
}

/**
 * 登录后/登出时的推送令牌注册与注销（fail-soft：推送失败不影响登录/登出主流程）。
 */
import { upsertPushToken, deletePushToken } from '@/api/push'
import { getDeviceId, getLocalPushToken } from '@/utils/device'
export async function registerPushTokenAfterLogin(): Promise<void> {
  try {
    const [deviceId, pushToken] = await Promise.all([getDeviceId(), getLocalPushToken()])
    await upsertPushToken('android', pushToken, deviceId)
  } catch (e) {
    console.warn('push token 上报失败（不影响登录）', e)
  }
}

export async function unregisterPushTokenOnLogout(): Promise<void> {
  try {
    const deviceId = await getDeviceId()
    await deletePushToken(deviceId)
  } catch (e) {
    console.warn('push token 注销失败（不影响登出）', e)
  }
}

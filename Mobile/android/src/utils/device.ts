/**
 * 设备标识与推送令牌。
 * 当前形态（M1）：push_token 用本地生成的稳定 UUID 占位——服务端推送桥按
 * 平台扇出（FCM/Push Kit），真实厂商 token 待对应 SDK 接入批替换本值；
 * 上报链路（登录后 PUT、登出 DELETE）已按最终契约接好，替换即可生效。
 */
import { Preferences } from '@capacitor/preferences'
import { STORAGE_KEYS } from '@/utils/session'

const KEY_DEVICE_ID = 'neurova.device.id'
const KEY_PUSH_TOKEN = 'neurova.device.push_token'

export async function getDeviceId(): Promise<string> {
  const { value } = await Preferences.get({ key: KEY_DEVICE_ID })
  if (value) return value
  const id = `dev-${crypto.randomUUID()}`
  await Preferences.set({ key: KEY_DEVICE_ID, value: id })
  return id
}

export async function getLocalPushToken(): Promise<string> {
  const { value } = await Preferences.get({ key: KEY_PUSH_TOKEN })
  if (value) return value
  const token = `local-${crypto.randomUUID()}`
  await Preferences.set({ key: KEY_PUSH_TOKEN, value: token })
  return token
}

export { STORAGE_KEYS }

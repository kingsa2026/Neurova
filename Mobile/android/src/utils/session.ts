/**
 * 本地持久化：Capacitor Preferences（原生 Keychain/Keystore 体系的首选轻量封装）。
 * Web/开发环境回退 localStorage。凭证分仓：token 与服务器档案分开存（设计方案 §9.2）。
 */
import { Preferences } from '@capacitor/preferences'

export async function storageGet(key: string): Promise<string | null> {
  const { value } = await Preferences.get({ key })
  return value ?? null
}

export async function storageSet(key: string, value: string): Promise<void> {
  await Preferences.set({ key, value })
}

export async function storageRemove(key: string): Promise<void> {
  await Preferences.remove({ key })
}

export async function storageGetJson<T>(key: string): Promise<T | null> {
  const raw = await storageGet(key)
  if (!raw) return null
  try {
    return JSON.parse(raw) as T
  } catch {
    return null
  }
}

export async function storageSetJson(key: string, value: unknown): Promise<void> {
  await storageSet(key, JSON.stringify(value))
}

export const STORAGE_KEYS = {
  accessToken: 'neurova.auth.access_token',
  refreshToken: 'neurova.auth.refresh_token',
  user: 'neurova.auth.user',
  serverProfiles: 'neurova.servers.profiles',
  activeServerId: 'neurova.servers.active_id',
} as const

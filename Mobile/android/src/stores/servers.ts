/**
 * 服务器档案（多服务器，设计方案 §4.5，已裁 D4）：
 * 每台服务器一条档案；切换档案不串账号、不串 token。
 */
import { defineStore } from 'pinia'
import { DEFAULT_SERVER_PROFILE } from '@/config'
import { STORAGE_KEYS, storageGetJson, storageSetJson } from '@/utils/session'
import type { ServerProfile } from '@/types'

interface ServersState {
  profiles: ServerProfile[]
  activeId: string
}

function normalizeBaseUrl(url: string): string {
  return (url || '').trim().replace(/\/+$/, '')
}

export const useServersStore = defineStore('servers', {
  state: (): ServersState => ({
    profiles: [
      { ...DEFAULT_SERVER_PROFILE, baseUrl: normalizeBaseUrl(DEFAULT_SERVER_PROFILE.baseUrl) },
    ],
    activeId: DEFAULT_SERVER_PROFILE.id,
  }),
  getters: {
    active(state): ServerProfile {
      return state.profiles.find((p) => p.id === state.activeId) ?? state.profiles[0]
    },
    /** API 根：{baseUrl}/api/v1（中继形态时 baseUrl 已含 /t/<routeId> 前缀） */
    apiBase(state): string {
      const p = state.profiles.find((x) => x.id === state.activeId) ?? state.profiles[0]
      return `${normalizeBaseUrl(p.baseUrl)}/api/v1`
    },
  },
  actions: {
    async load() {
      const saved = await storageGetJson<ServersState>(STORAGE_KEYS.serverProfiles)
      if (saved && Array.isArray(saved.profiles) && saved.profiles.length) {
        this.profiles = saved.profiles.map((p) => ({ ...p, baseUrl: normalizeBaseUrl(p.baseUrl) }))
        this.activeId = saved.activeId
      }
    },
    async persist() {
      await storageSetJson(STORAGE_KEYS.serverProfiles, {
        profiles: this.profiles,
        activeId: this.activeId,
      } satisfies ServersState)
    },
    async addProfile(p: Omit<ServerProfile, 'id'>) {
      const id = `srv-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`
      this.profiles.push({ ...p, id, baseUrl: normalizeBaseUrl(p.baseUrl) })
      this.activeId = id
      await this.persist()
      return id
    },
    async updateProfile(id: string, patch: Partial<ServerProfile>) {
      const idx = this.profiles.findIndex((x) => x.id === id)
      if (idx >= 0) {
        this.profiles[idx] = { ...this.profiles[idx], ...patch }
        if (patch.baseUrl) this.profiles[idx].baseUrl = normalizeBaseUrl(patch.baseUrl)
        await this.persist()
      }
    },
    async removeProfile(id: string) {
      if (this.profiles.length <= 1) return
      this.profiles = this.profiles.filter((x) => x.id !== id)
      if (this.activeId === id) this.activeId = this.profiles[0].id
      await this.persist()
    },
    async switchTo(id: string) {
      if (this.profiles.some((x) => x.id === id)) {
        this.activeId = id
        await this.persist()
      }
    },
    async markConnected(account?: string) {
      const p = this.active
      p.lastConnectedAt = Date.now()
      if (account) p.lastAccount = account
      await this.persist()
    },
  },
})

/**
 * 认证与租户上下文（设计方案 §5）：
 * 登录 → JWT（access 60m / refresh 7d）→ /auth/me 取用户与租户（部门根）。
 * 租户只读展示，边界由服务端裁定；租户切换 = 退出后换账号（已裁 D3）。
 */
import { defineStore } from 'pinia'
import { useServersStore } from '@/stores/servers'
import { STORAGE_KEYS, storageGet, storageGetJson, storageRemove, storageSet, storageSetJson } from '@/utils/session'
import type { CurrentUser } from '@/types'

interface AuthState {
  user: CurrentUser | null
  loading: boolean
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({ user: null, loading: false }),
  getters: {
    isLoggedIn: (s) => !!s.user,
    tenantLabel: (s) => s.user?.tenant?.tenantName || s.user?.tenant?.tenantId || '',
  },
  actions: {
    async restore(): Promise<boolean> {
      const user = await storageGetJson<CurrentUser>(STORAGE_KEYS.user)
      const token = await storageGet('neurova.auth.access_token')
      if (user && token) {
        this.user = user
        return true
      }
      return false
    },
    async login(username: string, password: string): Promise<void> {
      const servers = useServersStore()
      this.loading = true
      try {
        const r = await fetch(`${servers.apiBase}/auth/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password }),
        })
        const body = await r.json().catch(() => null)
        if (!r.ok || !body?.access_token) {
          const msg = body?.detail || body?.message || `登录失败（${r.status}）`
          throw new Error(typeof msg === 'string' ? msg : '登录失败')
        }
        await storageSet('neurova.auth.access_token', body.access_token)
        if (body.refresh_token) await storageSet('neurova.auth.refresh_token', body.refresh_token)
        // 取用户信息（含租户展示字段）
        const me = await fetch(`${servers.apiBase}/auth/me`, {
          headers: { Authorization: `Bearer ${body.access_token}` },
        }).then((x) => x.json())
        const user: CurrentUser = {
          id: String(me?.id ?? me?.sub ?? ''),
          username: me?.username ?? username,
          email: me?.email,
          role: me?.role ?? 'user',
          tenant: { tenantId: me?.tenant_id || 'default', tenantName: me?.tenant_name || me?.tenant_id || 'default' },
        }
        this.user = user
        await storageSetJson(STORAGE_KEYS.user, user)
        await servers.markConnected(user.username)
      } finally {
        this.loading = false
      }
    },
    async logout(): Promise<void> {
      const servers = useServersStore()
      const token = (await storageGetJson<string>(STORAGE_KEYS.accessToken)) ?? ''
      try {
        // 服务端黑名单登出；失败不阻塞本地清理
        await fetch(`${servers.apiBase}/auth/logout`, {
          method: 'POST',
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        }).catch(() => undefined)
      } finally {
        this.user = null
        await storageRemove('neurova.auth.access_token')
        await storageRemove('neurova.auth.refresh_token')
        await storageRemove(STORAGE_KEYS.user)
      }
    },
  },
})

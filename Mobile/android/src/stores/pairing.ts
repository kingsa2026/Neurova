/**
 * 配对凭证仓（设计方案 §5.3/§4.7）：
 * 长期设备身份（pairingId+deviceSecret）持久化；一次性 connect_ticket 内存态。
 * WS 通道用 ticket 握手；过期用设备身份走 /pairing/refresh 续签（免回屏重扫）。
 */
import { defineStore } from 'pinia'
import { STORAGE_KEYS, storageGetJson, storageRemove, storageSetJson } from '@/utils/session'
import type { PairingConfirmed, PairingResolved } from '@/api/pairing'

interface PairingState {
  paired: boolean
  pairingId: string
  deviceSecret: string
  wsUrl: string
  ticket: string
  ticketExpiresAt: number
}

export const usePairingStore = defineStore('pairing', {
  state: (): PairingState => ({
    paired: false,
    pairingId: '',
    deviceSecret: '',
    wsUrl: '',
    ticket: '',
    ticketExpiresAt: 0,
  }),
  actions: {
    async load(): Promise<boolean> {
      const saved = await storageGetJson<PairingState>(STORAGE_KEYS.user + '.pairing')
      if (saved && saved.paired && saved.pairingId && saved.deviceSecret) {
        Object.assign(this, saved)
        return true
      }
      return false
    },
    async persist() {
      await storageSetJson(STORAGE_KEYS.user + '.pairing', {
        paired: this.paired,
        pairingId: this.pairingId,
        deviceSecret: this.deviceSecret,
        wsUrl: this.wsUrl,
      } satisfies Partial<PairingState>)
    },
    /** resolve+confirm 成功后写入 */
    async applyConfirmed(resolved: PairingResolved | null, confirmed: PairingConfirmed) {
      this.paired = true
      this.pairingId = confirmed.pairingId ?? resolved?.pairingId ?? ''
      this.deviceSecret = confirmed.deviceSecret ?? ''
      this.wsUrl = confirmed.wsUrl || resolved?.wsUrl || this.wsUrl
      this.ticket = confirmed.wsToken
      this.ticketExpiresAt = Date.now() + confirmed.expiresIn * 1000
      await this.persist()
    },
    /** refresh 续签成功后只换 ticket（不改设备身份，设计方案 §5.1b） */
    async applyRefreshed(ticket: string, expiresIn: number) {
      this.ticket = ticket
      this.ticketExpiresAt = Date.now() + expiresIn * 1000
    },
    async clear() {
      this.paired = false
      this.pairingId = ''
      this.deviceSecret = ''
      this.wsUrl = ''
      this.ticket = ''
      this.ticketExpiresAt = 0
      await storageRemove(STORAGE_KEYS.user + '.pairing')
    },
  },
})

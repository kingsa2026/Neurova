/**
 * 渠道扫码授权 composable（对齐 QwenPaw useChannelQrcode.ts 的 Vue 移植）
 *
 * 流程：取二维码 → 展示 → 递归 setTimeout 轮询（不重叠请求）→ 成功回填凭据/
 * 过期/失败回调。任意 QRCODE_AUTH_HANDLERS 注册的渠道通用。
 */
import { ref, onUnmounted } from 'vue'
import {
  getChannelQrcode,
  getChannelQrcodeStatus,
} from '@/api/modules/channel-configs'

export interface ChannelQrcodeConfig {
  /** 后端 handler 键（feishu/dingtalk/qq/wecom/wechat） */
  channel: string
  /** 判定授权成功的 status 值（多数渠道 success，wechat 为 confirmed） */
  successStatus: string
  /** 成功时凭据映射中必须非空的键 */
  successCredentialKey: string
  /** 轮询间隔 ms（默认 2000） */
  pollInterval?: number
  /** 墙钟超时 ms（到期视为过期） */
  pollTimeout?: number
  /** 最大轮询次数兜底 */
  maxPollCount?: number
  /** 额外查询参数（如 feishu domain） */
  params?: Record<string, string>
  /** 授权成功（凭据待回填表单） */
  onSuccess: (credentials: Record<string, string>) => void
  /** 取码失败/二维码过期/后端失败 */
  onError: (type: 'fetch' | 'expired' | 'fail') => void
}

const unwrap = (r: any) => (r && r.data !== undefined ? r.data : r)

export function useChannelQrcode(cfg: ChannelQrcodeConfig) {
  const qrcodeImg = ref('')
  const loading = ref(false)
  let pollTimer: ReturnType<typeof setTimeout> | null = null
  let confirmed = false
  let pollCount = 0
  let startTime = 0

  const stopPoll = () => {
    if (pollTimer) {
      clearTimeout(pollTimer)
      pollTimer = null
    }
  }

  const reset = () => {
    stopPoll()
    qrcodeImg.value = ''
    confirmed = false
    pollCount = 0
    startTime = 0
  }

  const fetchQrcode = async () => {
    reset()
    loading.value = true
    try {
      const raw = unwrap(await getChannelQrcode(cfg.channel, cfg.params))
      if (!raw?.qrcode_img) {
        cfg.onError('fetch')
        return
      }
      qrcodeImg.value = raw.qrcode_img
      pollCount = 0
      startTime = Date.now()

      const schedulePoll = () => {
        pollTimer = setTimeout(async () => {
          if (cfg.pollTimeout && Date.now() - startTime >= cfg.pollTimeout) {
            qrcodeImg.value = ''
            cfg.onError('expired')
            return
          }
          if (cfg.maxPollCount && pollCount >= cfg.maxPollCount) {
            qrcodeImg.value = ''
            cfg.onError('expired')
            return
          }
          pollCount++
          try {
            const result = unwrap(await getChannelQrcodeStatus(cfg.channel, raw.poll_token, cfg.params))
            if (result?.status === cfg.successStatus && result?.credentials?.[cfg.successCredentialKey]) {
              if (confirmed) return
              confirmed = true
              qrcodeImg.value = ''
              cfg.onSuccess(result.credentials)
              return
            } else if (result?.status === 'expired') {
              qrcodeImg.value = ''
              cfg.onError('expired')
              return
            } else if (result?.status === 'fail') {
              qrcodeImg.value = ''
              cfg.onError('fail')
              return
            }
          } catch {
            /* 单次轮询失败忽略，继续下一轮 */
          }
          schedulePoll()
        }, cfg.pollInterval ?? 2000)
      }
      schedulePoll()
    } catch {
      cfg.onError('fetch')
    } finally {
      loading.value = false
    }
  }

  onUnmounted(stopPoll)

  return { qrcodeImg, loading, fetchQrcode, stopPoll, reset }
}

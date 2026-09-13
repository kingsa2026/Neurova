/**
 * SSE audio 事件 / done payload 的 audio_url → 可播放 URL 解析（F-4 配套，2026-09-11）。
 *
 * 后端 chat.py 现输出 `/api/v1/chat/tts-audio/{agent_id}/{filename}` 鉴权内容端点 URL；
 * `<audio>` 直链无法携带 Authorization 头（项目既有直链 401 教训），必须凭证据
 * fetch 转 objectURL。其余形态（服务端直链/历史数据）原样透传。
 *
 * 取流失败返回 null——调用方不设 audioUrl，气泡回落"生成语音"手动合成链路；
 * 成功创建的 blob URL 由 stores/chat.ts 丢弃路径的 revokeMessageBlobUrls 统一回收。
 */
import { requireNonEmptyAudioBlob } from '@/composables/useStreamTTS'
import { secureStorage } from '@/utils/security'

/**
 * @returns 可播放 URL；非 `/api/` 形态原样返回（含空串，保持旧行为）；
 *          `/api/` 取流失败返回 null。
 * fetchImpl 为结构化窄类型（真实 fetch 可传入），便于测试注入。
 */
export type FetchLike = (
  input: string,
  init?: { headers?: Record<string, string> },
) => Promise<{ ok: boolean; blob(): Promise<Blob> }>

export async function resolveAudioUrl(url: string, fetchImpl: FetchLike = fetch): Promise<string | null> {
  if (!url.startsWith('/api/')) return url
  try {
    const token = secureStorage.get('auth_token')
    const resp = await fetchImpl(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    if (!resp.ok) return null
    return URL.createObjectURL(requireNonEmptyAudioBlob(await resp.blob()))
  } catch {
    return null
  }
}

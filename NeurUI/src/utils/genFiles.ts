import { secureStorage } from '@/utils/security'

/**
 * 批次3：AIGC 产物文件访问凭证。
 *
 * 产物端点（GET /api/v1/generation/files/{name}）已从匿名 StaticFiles 收口为
 * 鉴权路由；<img>/<audio>/<a download> 等资源标签无法携带 Authorization 头，
 * 后端 get_current_user 支持 ?access_token= 查询凭证回退，此处统一追加。
 * 已是绝对 http(s) 外链（远端临时 URL 兜底）原样返回。
 */
export function withFileToken(url: string): string {
  if (!url) return url
  if (/^https?:\/\//i.test(url)) return url
  if (url.includes('access_token=')) return url
  const token = secureStorage.get('auth_token') || ''
  if (!token) return url
  return `${url}${url.includes('?') ? '&' : '?'}access_token=${encodeURIComponent(token)}`
}

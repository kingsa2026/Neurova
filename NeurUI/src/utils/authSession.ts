/**
 * 会话在 storage 里的三把键与唯一读取口。
 *
 * 收口前是 12 处各写各的：4 份 `const TOKEN_KEY = 'auth_token'`（api/index、
 * api/modules/collaboration、api/modules/notifications、stores/auth）＋ 8 处裸
 * `secureStorage.get('auth_token')`（useSessionSync、ChatPage×5、audioUrl、genFiles）。
 * 写侧只有一处，读侧散在八处——键名一旦在某一份里分家，那几处就安静地发出空头，
 * 而这正是记忆面（§6-429 起一律要凭证）必 401 的那几条腿。
 *
 * 改名等于把现存登录态一次性作废，所以键名只允许这一处定义，由
 * `src/utils/__tests__/sessionKeysSingleSource.test.ts` 常驻钉住。
 */
import { secureStorage } from '@/utils/security'

export const AUTH_TOKEN_KEY = 'auth_token'
export const AUTH_REFRESH_TOKEN_KEY = 'refresh_token'
export const AUTH_USER_KEY = 'user'

/** 无凭证给空串而不是 null：调用方拼 `Bearer ${…}` 不会拼出字面 "Bearer null"。 */
export function readAccessToken(): string {
  return secureStorage.get(AUTH_TOKEN_KEY) ?? ''
}

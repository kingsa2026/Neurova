/**
 * 语言面客户端（台账 §6-145 裁定乙：UI 拉覆盖层 + 本人语言偏好）。
 *
 * 后端侧事实源：`neurova/api/endpoints/language_api.py`（挂在 `/api/v1/language`）。
 * 这里只登记三件事，且都**没有**在本文件重抄语言码归一或状态判定——
 * 那些口径留在后端单点（`Language.normalizeTag` / `Translation.is_approved`）。
 */
import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types（与后端投影逐键对齐，见 tests/unit/api/test_languageFaceReadSurface.py
// ::testResponseEnvelopeKeysAreTheRealModelKeys）
// ---------------------------------------------------------------------------

/** 本人语言偏好读数。`configured=false` 时给的是数据类自己的默认值，不是用户做过的决定。 */
export interface LanguagePreferenceView {
  user_id: string
  configured: boolean
  source: 'user' | 'default'
  primary_language: string
  secondary_languages: string[]
  fallback_language: string
  auto_detect: boolean
  updated_at: number | null
  /** 仅 PUT 响应带回：调用方原样递来的标签（`zh-CN` 那一族），便于 UI 回显来路 */
  requested_tag?: string
}

export interface PreferenceUpdatePayload {
  primary_language: string
  secondary_languages?: string[]
  fallback_language?: string
  auto_detect?: boolean
}

/** 覆盖层单条文案。`approved` 是**状态事实**，不是本客户端的推断。 */
export interface OverlayEntry {
  key: string
  value: string
  approved: boolean
  translator: string
}

export interface OverlayView {
  namespace: string
  requested_tag: string
  resolved_language: string
  entries: OverlayEntry[]
  unapproved_count: number
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/language'

/**
 * UI 自己那一层覆盖文案所在的命名空间。
 *
 * 刻意不用后端的 `default`/`ui`：那两个是包内置译文库的示例内容（greeting/login…），
 * 拉进前端会把与界面无关的键并进口袋。运营/用户给界面补的文案写在这里，
 * 读也只读这里——一个键名，一处定义。
 */
export const UI_OVERLAY_NAMESPACE = 'ui-overlay'

/** 读取本人语言偏好（只读；后端不会替没设过的人建一条偏好）。 */
export function getMyLanguagePreference() {
  return api.get<ApiResponse<LanguagePreferenceView>>(`${BASE}/preferences/mine`)
}

/** 写入本人语言偏好（属主只从登录态取，请求体里没有 user_id 这个口）。 */
export function setMyLanguagePreference(payload: PreferenceUpdatePayload) {
  return api.put<ApiResponse<LanguagePreferenceView>>(`${BASE}/preferences/mine`, payload)
}

/** 拉取某门语言的覆盖层。不识别的语言码后端回 400 并点名，不会给一份空覆盖层。 */
export function getTranslationOverlay(language: string, namespace: string = UI_OVERLAY_NAMESPACE) {
  return api.get<ApiResponse<OverlayView>>(`${BASE}/overlay`, {
    params: { language, namespace },
  })
}

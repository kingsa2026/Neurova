/**
 * 语言面客户端（台账 §6-145 裁定乙：UI 拉覆盖层 + 本人语言偏好；§6-167 再加开箱默认）。
 *
 * 后端侧事实源：`neurova/api/endpoints/language_api.py`（挂在 `/api/v1/language`）。
 * 这里登记四件事（本人偏好读/写、开箱默认读/写、覆盖层读），且都**没有**在本文件重抄
 * 语言码归一或状态判定——那些口径留在后端单点（`Language.normalizeTag` /
 * `Translation.is_approved`）。唯一例外是 `LANGUAGE_SOURCE` 那三个值：跨语言无法共享定义，
 * 所以本文件是它们在 UI 侧的唯一落点，别处一律取用常量。
 */
import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types（与后端投影逐键对齐，见 tests/unit/api/test_languageFaceReadSurface.py
// ::testResponseEnvelopeKeysAreTheRealModelKeys）
// ---------------------------------------------------------------------------

/**
 * 这条读数是谁给的（§6-167 起三值，定义处一份）。
 *
 * 后端的事实源是 `LanguageManager.EFFECTIVE_SOURCES`；这里抄一份**类型**是跨语言无法避免的
 * 一步，但字面量在本 UI 只许出现在这一个文件里——其余地方一律取 `LANGUAGE_SOURCE`。
 * 判据 `language.ts 是 out_of_box 字面量的唯一落点` 钉这件事：两处各写一遍时，
 * 先漂移的一定是没人对着读的那一份。
 */
export const LANGUAGE_SOURCE = {
  user: 'user',
  outOfBox: 'out_of_box',
  builtin: 'builtin',
} as const

export type LanguageSource = (typeof LANGUAGE_SOURCE)[keyof typeof LANGUAGE_SOURCE]

/** 本人语言偏好读数。`configured=false` 时给的是默认值，不是用户做过的决定。 */
export interface LanguagePreferenceView {
  user_id: string
  configured: boolean
  source: LanguageSource
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

/**
 * 读「开箱默认」：管理员替**还没选过语言的人**定的起点。登录即可读——
 * 每个人都会看到它作用于自己的效果，把读面也关进管理员门里，
 * 普通用户就只剩"我的界面不知道为什么是这个语言"这一种读数。
 */
export function getOutOfBoxLanguageDefault() {
  return api.get<ApiResponse<LanguagePreferenceView>>(`${BASE}/preferences/default`)
}

/**
 * 写「开箱默认」——**后端仅管理员放行**（与覆盖层写面同一档）：
 * 这一格影响的是所有还没选过语言的人，不该由任意一个登录用户替所有人定。
 */
export function setOutOfBoxLanguageDefault(payload: PreferenceUpdatePayload) {
  return api.put<ApiResponse<LanguagePreferenceView>>(`${BASE}/preferences/default`, payload)
}

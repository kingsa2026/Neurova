import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Composer } from 'vue-i18n'
import { secureStorage } from '@/utils/security'
import i18n, {
  LOCALE_STORAGE_KEY,
  isSupportedLocale,
  overlayTreeFromEntries,
  readStoredLocaleCode,
  uiCodeForLanguageTag,
} from '@/i18n'
import { getMyLanguagePreference, getTranslationOverlay, setMyLanguagePreference } from '@/api/modules/language'

const THEME_KEY = 'app_theme'
const SKIN_KEY = 'app_skin'
const SIDEBAR_KEY = 'sidebar_collapsed'

/** RTL locale codes that require document.dir = 'rtl'. */
const RTL_LOCALES = ['ar-SA', 'he-IL', 'fa-IR', 'ur-PK']

export type AppSkin = 'cosmic' | 'ios'

export const useAppStore = defineStore('app', () => {
  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  const theme = ref<'light' | 'dark'>(
    (secureStorage.get(THEME_KEY) as 'light' | 'dark') || 'dark',
  )
  const skin = ref<AppSkin>((secureStorage.get(SKIN_KEY) as AppSkin) || 'cosmic')
  const locale = ref<string>(readStoredLocaleCode())
  const sidebarCollapsed = ref<boolean>(secureStorage.getObject<boolean>(SIDEBAR_KEY, false))
  const currentAgentId = ref<string | null>(null)
  const globalLoading = ref<boolean>(false)
  const loadingText = ref<string>('')

  // ---------------------------------------------------------------------------
  // Computed
  // ---------------------------------------------------------------------------
  const isDark = computed(() => theme.value === 'dark')
  const isRtl = computed(() => RTL_LOCALES.includes(locale.value))

  // ---------------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------------

  /**
   * Apply the current theme to the document root.
   */
  function applyTheme(): void {
    document.documentElement.setAttribute('data-theme', theme.value)
    document.documentElement.classList.toggle('dark', theme.value === 'dark')
    document.documentElement.classList.toggle('light', theme.value === 'light')
  }

  /**
   * Apply the current skin to the document root.
   */
  function applySkin(): void {
    document.documentElement.setAttribute('data-skin', skin.value)
  }

  /**
   * Apply the current locale direction (LTR/RTL) to the document.
   */
  function applyDirection(): void {
    document.dir = isRtl.value ? 'rtl' : 'ltr'
  }

  /**
   * Set theme explicitly and persist.
   */
  function setTheme(newTheme: 'light' | 'dark'): void {
    theme.value = newTheme
    secureStorage.set(THEME_KEY, newTheme)
    applyTheme()
  }

  /**
   * Toggle between light and dark themes.
   */
  function toggleTheme(): void {
    setTheme(theme.value === 'dark' ? 'light' : 'dark')
  }

  /**
   * Set skin explicitly and persist.
   */
  function setSkin(newSkin: AppSkin): void {
    skin.value = newSkin
    secureStorage.set(SKIN_KEY, newSkin)
    applySkin()
  }

  /**
   * Toggle between the two skins (cosmic 原版 ⇄ ios Liquid Glass).
   */
  function toggleSkin(): void {
    setSkin(skin.value === 'cosmic' ? 'ios' : 'cosmic')
  }

  /** 已拉过覆盖层的语言，避免每次切回来都打一次后端。 */
  const overlayLoaded = ref<string[]>([])

  /**
   * `i18n.global` 在 `legacy:false` 下就是 Composer，但库把它声明成 union 类型。
   * 这里收一个带类型的取用点，免得每处都写一遍 cast——那正是"同一件事写 N 遍"的形态。
   */
  function composer(): Composer {
    return i18n.global as unknown as Composer
  }

  /**
   * The single place that changes the UI language.
   *
   * Before this, the caller had to remember to set `i18n.global.locale` — two components did,
   * in their own words, and a third caller that forgot would silently keep the old language.
   * The store is now the only owner: ref + i18n instance + direction + overlay + persistence.
   *
   * @param persist  `false` when the change comes **from** the server (re-POSTing what we just
   *                 read back would let a stale device overwrite the newest choice).
   */
  function setLocale(newLocale: string, persist = true): void {
    if (!isSupportedLocale(newLocale)) return
    locale.value = newLocale
    secureStorage.set(LOCALE_STORAGE_KEY, newLocale)
    composer().locale.value = newLocale
    applyDirection()
    void loadOverlay(newLocale)
    if (persist) void persistLocaleToServer(newLocale)
  }

  /**
   * Pull this language's overlay (operator/user-contributed copy) and merge it in.
   *
   * Failure is deliberately quiet: the overlay is an extra layer, and if it cannot be fetched
   * the interface still has its shipped strings. What must **not** happen is falling back to
   * another language or showing an error — the user asked to see this language.
   */
  async function loadOverlay(code: string): Promise<void> {
    if (overlayLoaded.value.includes(code)) return
    try {
      const response = await getTranslationOverlay(code)
      const entries = response?.data?.entries ?? []
      composer().mergeLocaleMessage(code, overlayTreeFromEntries(entries))
      overlayLoaded.value.push(code)
    } catch {
      // 覆盖层拉不到就用站内既有文案；不换语言、不弹错
    }
  }

  /**
   * Tell the backend the user picked this language, so it survives a restart or another device.
   * Quiet on failure: the local choice stands either way, and a retry happens on the next pick.
   */
  async function persistLocaleToServer(code: string): Promise<boolean> {
    try {
      await setMyLanguagePreference({ primary_language: code, auto_detect: false })
      return true
    } catch {
      return false
    }
  }

  /** 覆盖层在启动与切换语言时都要**重取**一次：缓存只是为了不让同一次会话里反复打后端。 */
  function refreshOverlay(code: string): void {
    overlayLoaded.value = overlayLoaded.value.filter((x) => x !== code)
    void loadOverlay(code)
  }

  /**
   * Boot-time read: the server preference wins over the locally cached one (台账 §6-145 乙案，
   * 「UI 拉覆盖层」的另一半——先拉**这个人的**语言，再拉那门语言的文案层)。
   *
   * 读数分五类，每一类都留得下来（`outcome` 是给判据与日志用的，不是给用户看的弹窗）：
   * - `applied`   —— 服务端有偏好且能映射到本 UI 的语言，界面已切过去；
   * - `same`      —— 服务端偏好与本地一致，什么都不动；
   * - `unmapped`  —— 服务端给的语言本 UI 没有语言包（如 `pt`），**保持本地选择**，
   *                  不把某人切到他根本没选的语言；
   * - `default` / `failed` —— 没设过偏好 / 请求没成，同样保持本地。
   */
  async function syncLocaleFromServer(): Promise<{ outcome: string; from?: string; to?: string }> {
    const from = locale.value
    let view
    try {
      view = (await getMyLanguagePreference()).data
    } catch {
      return { outcome: 'failed', from }
    }
    if (!view?.configured) {
      refreshOverlay(from)
      return { outcome: 'default', from }
    }

    const code = uiCodeForLanguageTag(view.primary_language)
    if (!code) return { outcome: 'unmapped', from, to: view.primary_language }
    if (code === from) {
      refreshOverlay(code)
      return { outcome: 'same', from, to: code }
    }

    setLocale(code, false)
    return { outcome: 'applied', from, to: code }
  }

  /**
   * Toggle sidebar collapsed state and persist.
   */
  function toggleSidebar(): void {
    sidebarCollapsed.value = !sidebarCollapsed.value
    secureStorage.setObject(SIDEBAR_KEY, sidebarCollapsed.value)
  }

  /**
   * Set the currently active agent ID (used across agent-scoped pages).
   */
  function setCurrentAgentId(agentId: string | null): void {
    currentAgentId.value = agentId
  }

  /**
   * Show / hide the global loading overlay with optional text.
   */
  function setGlobalLoading(loading: boolean, text = ''): void {
    globalLoading.value = loading
    loadingText.value = text
  }

  /**
   * Initialise the store on app mount (apply persisted settings).
   */
  function init(): void {
    applyTheme()
    applySkin()
    applyDirection()
  }

  return {
    // state
    theme,
    skin,
    locale,
    sidebarCollapsed,
    currentAgentId,
    globalLoading,
    loadingText,
    overlayLoaded,
    // computed
    isDark,
    isRtl,
    // actions
    setTheme,
    toggleTheme,
    setSkin,
    toggleSkin,
    setLocale,
    loadOverlay,
    syncLocaleFromServer,
    persistLocaleToServer,
    toggleSidebar,
    setCurrentAgentId,
    setGlobalLoading,
    init,
  }
})

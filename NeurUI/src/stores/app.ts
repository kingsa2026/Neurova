import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { secureStorage } from '@/utils/security'

const THEME_KEY = 'app_theme'
const LOCALE_KEY = 'locale'
const SIDEBAR_KEY = 'sidebar_collapsed'

/** RTL locale codes that require document.dir = 'rtl'. */
const RTL_LOCALES = ['ar-SA', 'he-IL', 'fa-IR', 'ur-PK']

export const useAppStore = defineStore('app', () => {
  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  const theme = ref<'light' | 'dark'>(
    (secureStorage.get(THEME_KEY) as 'light' | 'dark') || 'dark',
  )
  const locale = ref<string>(secureStorage.get(LOCALE_KEY) || 'zh-CN')
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
   * Set locale, persist it, and update i18n + document direction.
   * Must be called with the i18n instance available; the caller should
   * also update `i18n.global.locale` after calling this.
   */
  function setLocale(newLocale: string): void {
    locale.value = newLocale
    secureStorage.set(LOCALE_KEY, newLocale)
    applyDirection()
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
    applyDirection()
  }

  return {
    // state
    theme,
    locale,
    sidebarCollapsed,
    currentAgentId,
    globalLoading,
    loadingText,
    // computed
    isDark,
    isRtl,
    // actions
    setTheme,
    toggleTheme,
    setLocale,
    toggleSidebar,
    setCurrentAgentId,
    setGlobalLoading,
    init,
  }
})

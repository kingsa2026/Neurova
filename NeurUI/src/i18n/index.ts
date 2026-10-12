import { createI18n } from 'vue-i18n'
import { secureStorage } from '@/utils/security'
import zhCN from './locales/zh-CN'
import enUS from './locales/en-US'
import ruRU from './locales/ru-RU'
import jaJP from './locales/ja-JP'
import frFR from './locales/fr-FR'
import arSA from './locales/ar-SA'
import koKR from './locales/ko-KR'
import esES from './locales/es-ES'
import deDE from './locales/de-DE'
import hiIN from './locales/hi-IN'
import itIT from './locales/it-IT'

export const LOCALE_STORAGE_KEY = 'locale'
export const DEFAULT_LOCALE = 'zh-CN'

/**
 * The **only** place that reads the persisted UI locale.
 *
 * It used to be read twice — here with a bare `localStorage.getItem('locale')` and again in
 * `stores/app.ts` through `secureStorage` — so the boot locale and the store's locale could
 * disagree, and any change to the storage channel had to be remembered in two places.
 * Both readers now go through this function (AGENTS.md 教义第 6 条).
 */
export function readStoredLocaleCode(): string {
  const stored = secureStorage.get(LOCALE_STORAGE_KEY)
  return stored && isSupportedLocale(stored) ? stored : DEFAULT_LOCALE
}

export const supportedLocales = [
  { code: 'zh-CN', name: '\u7B80\u4F53\u4E2D\u6587', flag: '\uD83C\uDDE8\uD83C\uDDF3' },
  { code: 'en-US', name: 'English', flag: '\uD83C\uDDFA\uD83C\uDDF8' },
  { code: 'ru-RU', name: '\u0420\u0443\u0441\u0441\u043A\u0438\u0439', flag: '\uD83C\uDDF7\uD83C\uDDFA' },
  { code: 'ja-JP', name: '\u65E5\u672C\u8A9E', flag: '\uD83C\uDDEF\uD83C\uDDF5' },
  { code: 'fr-FR', name: 'Fran\u00E7ais', flag: '\uD83C\uDDEB\uD83C\uDDF7' },
  { code: 'ar-SA', name: '\u0627\u0644\u0639\u0631\u0628\u064A\u0629', flag: '\uD83C\uDDF8\uD83C\uDDE6', rtl: true },
  { code: 'ko-KR', name: '\uD55C\uAD6D\uC5B4', flag: '\uD83C\uDDF0\uD83C\uDDF7' },
  { code: 'es-ES', name: 'Espa\u00F1ol', flag: '\uD83C\uDDEA\uD83C\uDDF8' },
  { code: 'de-DE', name: 'Deutsch', flag: '\uD83C\uDDE9\uD83C\uDDEA' },
  { code: 'hi-IN', name: '\u0939\u093F\u0928\u094D\u0926\u0940', flag: '\uD83C\uDDEE\uD83C\uDDF3' },
  { code: 'it-IT', name: 'Italiano', flag: '\uD83C\uDDEE\uD83C\uDDF9' },
]

export function isSupportedLocale(code: string): boolean {
  return supportedLocales.some((item) => item.code === code)
}

/**
 * Backend language tag → UI locale code, in **one** place.
 *
 * The backend speaks the normalized enum tags (`zh`, `en`, `ja`), the UI ships region codes
 * (`zh-CN`, `en-US`). Comparing them ad hoc is how §6-145 got written: the same normalization
 * existed twice, and the wrong copy won. Matching on the primary subtag means an unmapped tag
 * (`pt`, `he`) returns `null` — the caller must then keep the local choice rather than
 * silently landing somebody on a language they never picked.
 */
export function uiCodeForLanguageTag(tag: string | null | undefined): string | null {
  if (!tag) return null
  const primary = String(tag).toLowerCase().split('-')[0]
  const match = supportedLocales.find((item) => item.code.toLowerCase().split('-')[0] === primary)
  return match ? match.code : null
}

/**
 * Turn overlay entries into a vue-i18n message tree.
 *
 * Overlay keys are dotted paths (`nav.home.title`) so one entry can address one nested string;
 * a key without a dot lands at the top level. Values are taken verbatim — this is copy, not markup.
 */
export function overlayTreeFromEntries(
  entries: Array<{ key: string; value: string }>,
): Record<string, unknown> {
  const tree: Record<string, unknown> = {}
  for (const entry of entries) {
    if (!entry || typeof entry.key !== 'string' || typeof entry.value !== 'string') continue
    const segments = entry.key.split('.')
    let cursor: Record<string, unknown> = tree
    for (const segment of segments.slice(0, -1)) {
      const next = cursor[segment]
      if (typeof next !== 'object' || next === null) cursor[segment] = {}
      cursor = cursor[segment] as Record<string, unknown>
    }
    cursor[segments[segments.length - 1]] = entry.value
  }
  return tree
}

const savedLocale = readStoredLocaleCode()

const i18n = createI18n({
  legacy: false,
  locale: savedLocale,
  fallbackLocale: DEFAULT_LOCALE,
  messages: {
    'zh-CN': zhCN,
    'en-US': enUS,
    'ru-RU': ruRU,
    'ja-JP': jaJP,
    'fr-FR': frFR,
    'ar-SA': arSA,
    'ko-KR': koKR,
    'es-ES': esES,
    'de-DE': deDE,
    'hi-IN': hiIN,
    'it-IT': itIT,
  },
  globalInjection: true,
})

export default i18n

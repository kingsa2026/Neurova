import { createI18n } from 'vue-i18n'
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

const savedLocale = localStorage.getItem('locale') || 'zh-CN'

const i18n = createI18n({
  legacy: false,
  locale: savedLocale,
  fallbackLocale: 'zh-CN',
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

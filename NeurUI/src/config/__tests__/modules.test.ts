/**
 * 功能模块目录（用户组菜单权限的唯一事实源）测试
 *
 * 契约:
 *  1. 模块 key 唯一，且每个 key 都是真实存在的路由（替换 :id 占位后 router.resolve 可命中）。
 *  2. 顶部 4 组的模块清单必须与 config/navigation.ts 的 TOP_NAV_CATEGORIES 一致（防两处漂移）。
 *  3. 每个模块的 labelKey 在全部 11 个语言包 nav.* 下存在（缺失即渲染原始键名）。
 *  4. /dashboard 是兜底主页，不属于可勾选模块（恒可见）。
 */
import { describe, it, expect } from 'vitest'
import router from '@/router'
import { TOP_NAV_CATEGORIES } from '@/config/navigation'
import { MODULE_SECTIONS, MODULE_ZONE_LABEL_KEYS, ALL_MODULE_KEYS } from '@/config/modules'
import zhCN from '@/i18n/locales/zh-CN'
import enUS from '@/i18n/locales/en-US'
import jaJP from '@/i18n/locales/ja-JP'
import koKR from '@/i18n/locales/ko-KR'
import deDE from '@/i18n/locales/de-DE'
import frFR from '@/i18n/locales/fr-FR'
import esES from '@/i18n/locales/es-ES'
import itIT from '@/i18n/locales/it-IT'
import ruRU from '@/i18n/locales/ru-RU'
import hiIN from '@/i18n/locales/hi-IN'
import arSA from '@/i18n/locales/ar-SA'

const ALL_LOCALES: Record<string, any> = {
  'zh-CN': zhCN, 'en-US': enUS, 'ja-JP': jaJP, 'ko-KR': koKR,
  'de-DE': deDE, 'fr-FR': frFR, 'es-ES': esES, 'it-IT': itIT,
  'ru-RU': ruRU, 'hi-IN': hiIN, 'ar-SA': arSA,
}

describe('功能模块目录', () => {
  it('模块 key 全局唯一且非空', () => {
    const keys = ALL_MODULE_KEYS
    expect(keys.length).toBeGreaterThan(0)
    expect(new Set(keys).size).toBe(keys.length)
  })

  it('每个模块 key 都能命中真实路由（:id 占位替换后 resolve）', () => {
    for (const key of ALL_MODULE_KEYS) {
      const concrete = key.replace(':id', 'probe-agent')
      expect(router.resolve(concrete).matched.length, `路由不存在: ${key}`).toBeGreaterThan(0)
    }
  })

  it('/dashboard 是兜底主页，不在可勾选模块中', () => {
    expect(ALL_MODULE_KEYS).not.toContain('/dashboard')
  })

  it('顶部导航区模块与 TOP_NAV_CATEGORIES 逐项一致', () => {
    const topFromNav = TOP_NAV_CATEGORIES.flatMap(c => c.items.map(i => i.to))
    const topKeys = MODULE_SECTIONS.filter(s => s.zone === 'topNav').flatMap(s => s.items.map(i => i.key))
    expect(topKeys).toEqual(topFromNav)
  })

  it('三个分区标签 key 存在', () => {
    expect(MODULE_ZONE_LABEL_KEYS.sort()).toEqual(['agentZone', 'userZone', 'topNav'].sort())
  })

  it('全部模块 labelKey 在 11 个语言包 nav.* 下存在', () => {
    const items = MODULE_SECTIONS.flatMap(s => s.items)
    for (const [locale, msgs] of Object.entries(ALL_LOCALES)) {
      for (const item of items) {
        expect(msgs?.nav?.[item.labelKey], `${locale}.nav.${item.labelKey} 缺失`).toBeTruthy()
      }
    }
  })

  it('分组勾选页专用键在 11 个语言包存在（nav.topNav / system.allowedModules×2）', () => {
    for (const [locale, msgs] of Object.entries(ALL_LOCALES)) {
      expect(msgs?.nav?.topNav, `${locale}.nav.topNav 缺失`).toBeTruthy()
      expect(msgs?.system?.allowedModules, `${locale}.system.allowedModules 缺失`).toBeTruthy()
      expect(msgs?.system?.allowedModulesHint, `${locale}.system.allowedModulesHint 缺失`).toBeTruthy()
    }
  })
})

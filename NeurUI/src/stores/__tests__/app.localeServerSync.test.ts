/**
 * 「UI 拉覆盖层 + 本人语言偏好」的前端接缝（台账 §6-145 裁定乙）。
 *
 * 这档判据要抓住的不是"函数被调了"，而是**读数落到哪儿**：
 * - 服务端偏好必须真的改变界面语言（不是只回一个读数），而本地那份 localStorage 只是
 *   启动瞬间的兜底；
 * - 认不出的语言码**不许就近落到别的语言**（那等于替用户选了他没说过的东西）；
 * - 覆盖层合并要能被 `t()` 读出来（合不上就是"写了没人读"的前端版本）；
 * - 覆盖层拉失败要安静地用站内文案，而不是把界面语言换掉或弹错。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api/modules/language', () => ({
  UI_OVERLAY_NAMESPACE: 'ui-overlay',
  getMyLanguagePreference: vi.fn(),
  setMyLanguagePreference: vi.fn(),
  getTranslationOverlay: vi.fn(),
}))

import {
  getMyLanguagePreference,
  getTranslationOverlay,
  setMyLanguagePreference,
} from '@/api/modules/language'
import { useAppStore } from '@/stores/app'
import i18n from '@/i18n'

const globalComposer = () => i18n.global as any
const preferencePayload = (over: Record<string, unknown> = {}) => ({
  data: {
    user_id: 'u-1', configured: true, source: 'user',
    primary_language: 'en', secondary_languages: [], fallback_language: 'en',
    auto_detect: false, updated_at: 1, ...over,
  },
})

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  vi.clearAllMocks()
  globalComposer().locale.value = 'zh-CN'
  vi.mocked(getTranslationOverlay).mockResolvedValue({ data: { entries: [] } } as any)
  vi.mocked(getMyLanguagePreference).mockResolvedValue(preferencePayload({ configured: false }) as any)
})

describe('启动时按服务端的本人偏好定语言', () => {
  it('switches the interface to the language the server has on file', async () => {
    vi.mocked(getMyLanguagePreference).mockResolvedValue(preferencePayload() as any)
    const store = useAppStore()

    const result = await store.syncLocaleFromServer()

    expect(result.outcome).toBe('applied')
    expect(store.locale).toBe('en-US')
    expect(globalComposer().locale.value).toBe('en-US')
  })

  it('does not echo the read back as a write', async () => {
    vi.mocked(getMyLanguagePreference).mockResolvedValue(preferencePayload() as any)
    const store = useAppStore()

    await store.syncLocaleFromServer()

    expect(setMyLanguagePreference).not.toHaveBeenCalled()
  })

  it('keeps the local choice when the server speaks a language the UI does not ship', async () => {
    // `pt` 在本 UI 没有语言包。就近落到 zh-CN 会让这个人看到他没选过的语言，
    // 而这个读数此后每次启动都会自己复现——比"没生效"更难发现。
    vi.mocked(getMyLanguagePreference).mockResolvedValue(
      preferencePayload({ primary_language: 'pt' }) as any)
    const store = useAppStore()

    const result = await store.syncLocaleFromServer()

    expect(result.outcome).toBe('unmapped')
    expect(store.locale).toBe('zh-CN')
    expect(globalComposer().locale.value).toBe('zh-CN')
  })

  it('stays on the local choice and reports default when nothing was ever saved', async () => {
    const store = useAppStore()

    const result = await store.syncLocaleFromServer()

    expect(result.outcome).toBe('default')
    expect(store.locale).toBe('zh-CN')
    // 没有偏好也要把这一门语言的覆盖层拉一次：文案层与"谁选了哪门语言"是两件事
    await vi.waitFor(() => expect(getTranslationOverlay).toHaveBeenCalled())
  })

  it('is quiet when the request fails — the interface keeps working with shipped copy', async () => {
    vi.mocked(getMyLanguagePreference).mockRejectedValue(new Error('offline'))
    const store = useAppStore()

    const result = await store.syncLocaleFromServer()

    expect(result.outcome).toBe('failed')
    expect(store.locale).toBe('zh-CN')
  })
})

describe('用户改语言这条路上写侧与读侧同源', () => {
  it('persists the pick, moves i18n, and remembers it for the next boot', async () => {
    vi.mocked(setMyLanguagePreference).mockResolvedValue(preferencePayload() as any)
    const store = useAppStore()

    store.setLocale('ja-JP')

    expect(store.locale).toBe('ja-JP')
    expect(globalComposer().locale.value).toBe('ja-JP')
    expect(localStorage.getItem('locale')).toBe('ja-JP')
    await vi.waitFor(() => expect(setMyLanguagePreference).toHaveBeenCalledWith(
      { primary_language: 'ja-JP', auto_detect: false }))
  })

  it('ignores a language code the UI has no bundle for instead of half-switching', () => {
    const store = useAppStore()

    store.setLocale('pt-PT')

    expect(store.locale).toBe('zh-CN')
    expect(globalComposer().locale.value).toBe('zh-CN')
    expect(localStorage.getItem('locale')).toBeNull()
  })

  it('a code the user never chose must not be persisted as their preference', async () => {
    const store = useAppStore()
    store.setLocale('pt-PT')
    await Promise.resolve()

    expect(setMyLanguagePreference).not.toHaveBeenCalled()
  })
})

describe('覆盖层真的并进消息树', () => {
  it('merges an overlay entry so t() reads the contributed copy', async () => {
    vi.mocked(getTranslationOverlay).mockResolvedValue({
      data: { entries: [{ key: 'overlayProbeTitle', value: '覆盖层文案', approved: false, translator: 'user' }] },
    } as any)
    const store = useAppStore()

    await store.loadOverlay('zh-CN')

    expect(globalComposer().t('overlayProbeTitle')).toBe('覆盖层文案')
  })

  it('expands a dotted key onto the existing nested path', async () => {
    const before = globalComposer().t('nav.settings')
    vi.mocked(getTranslationOverlay).mockResolvedValue({
      data: { entries: [{ key: 'nav.settings', value: `${before}·覆盖`, approved: false, translator: 'external' }] },
    } as any)
    const store = useAppStore()

    await store.loadOverlay('zh-CN')

    expect(globalComposer().t('nav.settings')).toBe(`${before}·覆盖`)
  })

  it('pulls the overlay for the language the user switched to', async () => {
    // 命名空间不在这里给——它由 api 层那一份默认值决定（`UI_OVERLAY_NAMESPACE`，
    // 契约在 api/__tests__/language.test.ts 钉），store 只负责"切到哪门语言就拉哪一门"。
    const store = useAppStore()

    store.setLocale('ko-KR')

    await vi.waitFor(() => expect(getTranslationOverlay).toHaveBeenCalledWith('ko-KR'))
  })

  it('keeps working copy when the overlay cannot be fetched', async () => {
    vi.mocked(getTranslationOverlay).mockRejectedValue(new Error('offline'))
    const store = useAppStore()

    await expect(store.loadOverlay('zh-CN')).resolves.toBeUndefined()

    expect(store.locale).toBe('zh-CN')
  })

  it('asks the backend once per language, not once per call', async () => {
    const store = useAppStore()

    await store.loadOverlay('zh-CN')
    await store.loadOverlay('zh-CN')

    expect(getTranslationOverlay).toHaveBeenCalledTimes(1)
  })
})

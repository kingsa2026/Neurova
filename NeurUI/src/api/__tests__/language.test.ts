/**
 * 语言面客户端契约（路径与载荷必须命中 `neurova/api/endpoints/language_api.py` 的真路由）。
 *
 * 与 `media.test.ts` 同一形态：`vi.mock('@/api')` 捕获请求，不发网络。
 * 后端路由清单由 `scripts/generate_api_inventory.py` 与判据
 * `tests/unit/api/test_route_mount_contract_guard.py` 交叉核——这一档补的是**客户端侧**
 * 的键名与载荷形状（写错一个键名后端只会 422，而 422 在前端表现为"保存失败"，
 * 没人会去读响应体里的字段名）。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api', () => {
  const api = { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() }
  return { default: api, api, request: { get: vi.fn(), post: vi.fn() } }
})

import { api } from '@/api'
import * as languageApi from '../modules/language'

const apiGet = vi.mocked(api.get)
const apiPut = vi.mocked(api.put)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('GET /language/preferences/mine', () => {
  it('requests the caller own preference at the registered path', async () => {
    apiGet.mockResolvedValue({ data: {} } as any)

    await languageApi.getMyLanguagePreference()

    expect(apiGet).toHaveBeenCalledWith('/language/preferences/mine')
  })
})

describe('PUT /language/preferences/mine', () => {
  it('sends the payload as given and adds no identity field of its own', async () => {
    apiPut.mockResolvedValue({ data: {} } as any)

    await languageApi.setMyLanguagePreference({
      primary_language: 'zh-CN', secondary_languages: ['en'], auto_detect: false,
    })

    expect(apiPut).toHaveBeenCalledWith('/language/preferences/mine', {
      primary_language: 'zh-CN', secondary_languages: ['en'], auto_detect: false,
    })
    const body = apiPut.mock.calls[0][1] as Record<string, unknown>
    // 属主只从登录态取（后端 `extra="forbid"` 也会拒多余的 user_id）——
    // 客户端不许在这里替调用方补一个"我以谁的身份写"
    expect(body).not.toHaveProperty('user_id')
    expect(body).not.toHaveProperty('neuser_id')
  })
})

describe('GET /language/overlay', () => {
  it('defaults to the UI overlay namespace held in one place', async () => {
    apiGet.mockResolvedValue({ data: { entries: [] } } as any)

    await languageApi.getTranslationOverlay('zh-CN')

    expect(apiGet).toHaveBeenCalledWith('/language/overlay', {
      params: { language: 'zh-CN', namespace: languageApi.UI_OVERLAY_NAMESPACE },
    })
    expect(languageApi.UI_OVERLAY_NAMESPACE).toBe('ui-overlay')
  })

  it('lets a caller read another namespace without changing the default', async () => {
    apiGet.mockResolvedValue({ data: { entries: [] } } as any)

    await languageApi.getTranslationOverlay('en', 'default')

    const config = apiGet.mock.calls[0][1] as { params: Record<string, string> }
    expect(config.params).toEqual({ language: 'en', namespace: 'default' })

    apiGet.mockClear()
    await languageApi.getTranslationOverlay('en')
    expect((apiGet.mock.calls[0][1] as { params: Record<string, string> }).params.namespace)
      .toBe(languageApi.UI_OVERLAY_NAMESPACE)
  })

  it('carries the approved flag through, so the UI can tell contributed copy from shipped copy', async () => {
    apiGet.mockResolvedValue({
      data: { entries: [{ key: 'k', value: 'v', approved: false, translator: 'user' }] },
    } as any)

    const response = await languageApi.getTranslationOverlay('zh-CN')

    expect(response.data.entries[0]).toEqual({
      key: 'k', value: 'v', approved: false, translator: 'user',
    })
  })
})

describe('GET/PUT /language/preferences/default（§6-167 开箱默认）', () => {
  it('reads the out-of-box default at the registered path', async () => {
    apiGet.mockResolvedValue({ data: {} } as any)

    await languageApi.getOutOfBoxLanguageDefault()

    expect(apiGet).toHaveBeenCalledWith('/language/preferences/default')
  })

  it('writes it as a language payload and never with an owner field of its own', async () => {
    apiPut.mockResolvedValue({ data: {} } as any)

    await languageApi.setOutOfBoxLanguageDefault({
      primary_language: 'zh-CN', auto_detect: false,
    })

    expect(apiPut).toHaveBeenCalledWith('/language/preferences/default', {
      primary_language: 'zh-CN', auto_detect: false,
    })
    const body = apiPut.mock.calls[0][1] as Record<string, unknown>
    // 这一格影响的是"所有还没选过的人"，属主由后端那条保留名给；
    // 客户端递 user_id 就会长出第二个"替他人绑"的入口（后端 `extra="forbid"` 也拒）
    expect(body).not.toHaveProperty('user_id')
  })

  it('keeps the source vocabulary in exactly one UI file', async () => {
    // 后端那份定义在 `LanguageManager.EFFECTIVE_SOURCES`；跨语言无法共享定义，
    // 所以 UI 侧允许一份**类型/常量**，但只允许**一个文件**——两处各写一遍时，
    // 先漂移的一定是没人对着读的那一份（教义第 6 条）。
    const fs = await import('node:fs')
    const path = await import('node:path')
    const { fileURLToPath } = await import('node:url')
    const srcRoot = path.resolve(fileURLToPath(import.meta.url), '../../..')

    const hits: string[] = []
    // 名字带上面那件事：仓内已有两只叫 `walk` 的 fs 遍历器（`i18n/__tests__` 与
    // `components/__tests__`），第三只同名会让「跨文件同名函数」台账 +1 而没有任何必要
    // ——同名不总是错，但为省一个名字造一次同名是。
    const collectVocabularyHits = (dir: string) => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (entry.name === 'node_modules' || entry.name.startsWith('.')) continue
        const full = path.join(dir, entry.name)
        if (entry.isDirectory()) {
          // 测试夹具里也写着这三个值（它必须能替身那份常量），但它不是"定义处"；
          // 不排掉就会把判据自己那句搜索字符串算进命中面（§6-162 那枚自我指涉形态）
          if (entry.name !== '__tests__') collectVocabularyHits(full)
          continue
        }
        if (/\.(ts|vue)$/.test(entry.name)
          && !entry.name.includes('.test.') && !entry.name.includes('.spec.')
          && fs.readFileSync(full, 'utf-8').includes("'out_of_box'")) hits.push(full)
      }
    }
    collectVocabularyHits(srcRoot)

    expect(hits.map((p) => path.relative(srcRoot, p).replace(/\\/g, '/'))).toEqual([
      'api/modules/language.ts',
    ])
    expect(Object.values(languageApi.LANGUAGE_SOURCE).sort()).toEqual(
      ['builtin', 'out_of_box', 'user'])
  })
})

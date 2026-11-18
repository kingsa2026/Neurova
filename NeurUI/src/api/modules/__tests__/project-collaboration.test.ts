/**
 * S12 项目协作档案 API 契约测试
 *
 * getProjectCollaboration 挂既有 projects 域（GET /projects/{id}/collaboration，
 * 后端 projects_api.py），不新开端点域；本测试锁定 URL 形态与类型边界。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/api', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ code: 0, message: 'success', data: {} }),
    post: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    put: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    delete: vi.fn().mockResolvedValue({ code: 0, data: {} }),
  },
}))

import api from '@/api'
import { getProjectCollaboration } from '@/api/modules/collaboration'

const mockGet = vi.mocked(api.get)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('getProjectCollaboration 契约', () => {
  it('GET /projects/{id}/collaboration（挂 projects 域，不新开端点域）', async () => {
    await getProjectCollaboration('project_abc123')
    expect(mockGet).toHaveBeenCalledTimes(1)
    expect(mockGet).toHaveBeenCalledWith('/projects/project_abc123/collaboration')
  })

  it('返回信封的 data 即聚合档案（五类记录 + counts + summary）', async () => {
    const dossier = {
      project_id: 'project_abc123',
      generated_at: 1700000000,
      runs: [],
      events: [],
      candidates: [],
      approvals: [],
      room_messages: [],
      counts: { runs: 0, events: 0, candidates: 0, approvals: 0, room_messages: 0 },
      summary: null,
    }
    mockGet.mockResolvedValueOnce({ code: 0, message: 'success', data: dossier })
    const resp: any = await getProjectCollaboration('project_abc123')
    expect(resp.code).toBe(0)
    expect(resp.data).toEqual(dossier)
  })
})

// ─────────────────────────────────────────────────────────────
// S17 请求归档摘要面（源级 + 契约）：后端档案聚合已含 request_archive
// 摘要（request_archive.summarizeSessionArchives 单源），前端类型面与
// 档案面板必须接住——次数/token/时延/最近错误四件都上屏。
// ─────────────────────────────────────────────────────────────
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const apiModule = readFileSync(resolve(process.cwd(), 'src/api/modules/collaboration.ts'), 'utf-8')
const collabPage = readFileSync(resolve(process.cwd(), 'src/pages/CollaborationPage.vue'), 'utf-8')

const DOSSIER_LOCALES = [
  'zh-CN', 'en-US', 'ja-JP', 'ko-KR', 'de-DE', 'es-ES',
  'fr-FR', 'it-IT', 'ru-RU', 'ar-SA', 'hi-IN',
]

const ARCHIVE_KEYS = [
  'dossierRequestArchive',
  'dossierArchiveRequests',
  'dossierArchiveSuccess',
  'dossierArchiveFailures',
  'dossierArchiveTokens',
  'dossierArchiveLatency',
  'dossierArchiveRecentErrors',
]

describe('S17 请求归档摘要面', () => {
  it('类型面：ProjectCollaboration 含 request_archive 摘要与 counts 计数', () => {
    expect(apiModule).toContain('RequestArchiveSummary')
    expect(apiModule).toContain('request_archive')
    expect(apiModule).toContain('requestCount')
    expect(apiModule).toContain('latencyMs')
    expect(apiModule).toContain('recentErrors')
  })

  it('档案面板渲染请求归档块（次数/成功失败/token/时延/最近错误）', () => {
    expect(collabPage).toContain('dossierRequestArchive')
    expect(collabPage).toContain('dossierArchiveRequests')
    expect(collabPage).toContain('dossierArchiveSuccess')
    expect(collabPage).toContain('dossierArchiveFailures')
    expect(collabPage).toContain('dossierArchiveTokens')
    expect(collabPage).toContain('dossierArchiveLatency')
    expect(collabPage).toContain('dossierArchiveRecentErrors')
  })

  it('摘要取后端读数（requestCount/latencyMs/recentErrors），不自造', () => {
    expect(collabPage).toContain('request_archive.requestCount')
    expect(collabPage).toContain('latencyMs.avgMs')
    expect(collabPage).toContain('recentErrors')
  })

  it.each(DOSSIER_LOCALES)('%s 请求归档文案七键齐平', (locale) => {
    const file = readFileSync(resolve(process.cwd(), `src/i18n/locales/${locale}.ts`), 'utf-8')
    for (const key of ARCHIVE_KEYS) {
      const line = file.split('\n').find((ln) => ln.includes(`${key}:`)) ?? ''
      expect(line, `${locale} 缺 ${key}`).not.toBe('')
    }
  })
})

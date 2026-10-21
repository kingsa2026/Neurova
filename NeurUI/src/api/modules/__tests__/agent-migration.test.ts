import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/api', () => ({
  default: {
    get: vi.fn().mockResolvedValue(new Blob(['zip'])),
    post: vi.fn().mockResolvedValue({ success: true }),
  },
}))

import api from '@/api'
import {
  downloadMigrationZip,
  exportAgentMigration,
  importAgentMigration,
} from '@/api/modules/agent-migration'

const mockGet = vi.mocked(api.get)
const mockPost = vi.mocked(api.post)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('agent-migration API', () => {
  it('export 调 GET /agents/{id}/export-migration 且 responseType=blob', async () => {
    await exportAgentMigration('kai')
    expect(mockGet).toHaveBeenCalledWith('/agents/kai/export-migration', { responseType: 'blob' })
  })

  it('import 以 multipart 提交目标 ID、覆盖与三个面开关', async () => {
    const file = new File(['zip'], 'pkg.zip', { type: 'application/zip' })
    await importAgentMigration(file, {
      agent_id: 'newkai',
      overwrite: true,
      import_skills: true,
      import_cron: false,
      import_mcp: true,
    })
    expect(mockPost).toHaveBeenCalledTimes(1)
    const [url, form, config] = mockPost.mock.calls[0]
    expect(url).toBe('/agents/import-migration')
    expect((form as FormData).get('agent_id')).toBe('newkai')
    expect((form as FormData).get('overwrite')).toBe('true')
    expect((form as FormData).get('import_skills')).toBe('true')
    expect((form as FormData).get('import_cron')).toBe('false')
    expect((form as FormData).get('import_mcp')).toBe('true')
    expect((config as any)?.headers?.['Content-Type']).toBe('multipart/form-data')
  })

  it('download 生成 .zip 文件名并释放 object URL', () => {
    const create = vi.fn().mockReturnValue('blob:agent')
    const revoke = vi.fn()
    Object.defineProperty(URL, 'createObjectURL', { value: create, configurable: true })
    Object.defineProperty(URL, 'revokeObjectURL', { value: revoke, configurable: true })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    downloadMigrationZip(new Blob(['zip']), 'kai')

    expect(create).toHaveBeenCalled()
    expect(click).toHaveBeenCalled()
    expect(revoke).toHaveBeenCalledWith('blob:agent')
    click.mockRestore()
  })
})

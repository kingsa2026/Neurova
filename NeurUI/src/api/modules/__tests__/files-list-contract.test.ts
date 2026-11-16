import { describe, it, expect } from 'vitest'
import { normalizeFileInfoList } from '../files'

/**
 * P1-22 同根因命中点（审计 2026-11-16）：后端 `GET /files` 回裸 `List[FileInfo]`
 * （files_api.py:471，无信封无分页），键名是 file_id/filename/file_type；
 * FilePage 原按 `{data:{items}}` 信封读 `res?.data` 恒 undefined → 列表恒空。
 * 归一收口在模块边界（与 extractUploadedFileId 同一契约），页面不再各自猜键名。
 */
describe('normalizeFileInfoList — GET /files 契约归一', () => {
  it('把后端 FileInfo 键名映射为 FileItem（file_id→id / filename→name / file_type→type）', () => {
    const rows = normalizeFileInfoList([
      {
        file_id: 'f1', filename: 'a.png', file_type: 'image', mime_type: 'image/png',
        size: 12, version: '1.0.0', created_at: 1700000000, path: '/data/f1',
      },
      { file_id: 'f2', filename: 'b.txt', file_type: 'text', size: 3, created_at: 1700000001 },
    ])
    expect(rows).toHaveLength(2)
    expect(rows[0]).toMatchObject({ id: 'f1', name: 'a.png', type: 'image', size: 12 })
    expect(rows[1]).toMatchObject({ id: 'f2', name: 'b.txt', type: 'text' })
  })

  it('兼容信封/分页包装形状，剔除无 id 行，非数组输入回空数组', () => {
    expect(normalizeFileInfoList({ data: [{ file_id: 'f1', filename: 'x' }] }).map((r) => r.id)).toEqual(['f1'])
    expect(normalizeFileInfoList({ data: { items: [{ file_id: 'f1', filename: 'x' }] } })).toHaveLength(1)
    expect(normalizeFileInfoList({ items: [{ file_id: 'f1', filename: 'x' }] })).toHaveLength(1)
    expect(normalizeFileInfoList([{ filename: 'no-id' }])).toHaveLength(0)
    expect(normalizeFileInfoList(undefined)).toEqual([])
    expect(normalizeFileInfoList('garbage')).toEqual([])
  })
})

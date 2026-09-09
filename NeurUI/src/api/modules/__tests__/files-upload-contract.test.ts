/**
 * /files/upload 响应 → file_ids 提取契约（防回归）
 *
 * 2026-09-09 事故：ChatPage 读 uploadData?.id，而后端 FileInfo 契约字段是
 * file_id → fileIds 恒空 → /console/chat 永不带 file_ids → attachments=0
 * → agent 收不到图片（日志实锤：file_ids=None user_id=1 → attachments=0）。
 *
 * 锁定：
 * 1. 后端真实响应形态（FileInfo 裸 JSON，字段 file_id）必须可提取；
 * 2. axios 信封包装（.data 包一层）仍可提取；
 * 3. 兼容 id 别名；缺字段/空值返回 null（不得静默吞成空串）。
 */
import { describe, expect, it } from 'vitest'
import { extractUploadedFileId } from '@/api/modules/files'

describe('files upload 响应 file_id 提取契约', () => {
  it('后端 FileInfo 裸响应（file_id 字段）可提取', () => {
    // POST /files/upload 真实响应：FileInfo 模型直出，无信封
    const res = {
      file_id: 'a1b2c3d4-1111-2222-3333-444455556666',
      filename: 'dance.gif',
      file_type: 'image',
      mime_type: 'image/gif',
      size: 785200,
      version: '1.0.0',
      status: 'active',
      user_id: '1',
      agent_id: 'default',
      path: 'storage/users/1/agents/default/sessions/s1/image/a1b2c3d4_dance.gif',
      created_at: 1757400000,
      updated_at: 1757400000,
    }
    expect(extractUploadedFileId(res)).toBe('a1b2c3d4-1111-2222-3333-444455556666')
  })

  it('信封包装（.data 包一层）可提取', () => {
    const res = { success: true, data: { file_id: 'fid-env-1', filename: 'x.png' } }
    expect(extractUploadedFileId(res)).toBe('fid-env-1')
  })

  it('id 别名兼容提取', () => {
    expect(extractUploadedFileId({ id: 'fid-alias' })).toBe('fid-alias')
  })

  it('file_id 优先于 id', () => {
    expect(extractUploadedFileId({ file_id: 'real', id: 'alias' })).toBe('real')
  })

  it('缺字段/空值/非字符串返回 null', () => {
    expect(extractUploadedFileId(undefined)).toBeNull()
    expect(extractUploadedFileId(null)).toBeNull()
    expect(extractUploadedFileId({})).toBeNull()
    expect(extractUploadedFileId({ file_id: '' })).toBeNull()
    expect(extractUploadedFileId({ file_id: 123 })).toBeNull()
    expect(extractUploadedFileId('garbage')).toBeNull()
  })
})

/**
 * artifacts 工具契约测试（产物预览 W4）。
 *
 * 锁定：
 * - parseToolResultArtifacts：JSON dict 精确解析 + 截断 JSON 正则兜底 +
 *   output_ref 嵌套 + 去重；
 * - kindForFilename 扩展名映射（与后端 _artifact_kind 对齐）；
 * - shortHash 稳定性。
 */
import { describe, expect, it } from 'vitest'
import { kindForFilename, parseToolResultArtifacts, shortHash } from '../artifacts'

describe('parseToolResultArtifacts', () => {
  it('完整 JSON dict 提取 file_path', () => {
    const raw = JSON.stringify({ success: true, file_path: 'E:\\ws\\report.md' })
    const refs = parseToolResultArtifacts(raw)
    expect(refs).toHaveLength(1)
    expect(refs[0].path).toBe('E:\\ws\\report.md')
    expect(refs[0].field).toBe('file_path')
  })

  it('audio_path 与 output_ref.path 均可提取', () => {
    const raw = JSON.stringify({
      audio_path: 'C:\\Temp\\neurova_tts\\tts_1.wav',
      output_ref: { path: 'E:\\ws\\tool_outputs\\ref_1.json', size_bytes: 99 },
    })
    const paths = parseToolResultArtifacts(raw).map((r) => r.path)
    expect(paths).toContain('C:\\Temp\\neurova_tts\\tts_1.wav')
    expect(paths).toContain('E:\\ws\\tool_outputs\\ref_1.json')
  })

  it('截断 JSON（[:500] 切掉收尾引号）正则兜底', () => {
    const raw = '{"success": true, "file_path": "E:\\\\ws\\\\report.md'
    const refs = parseToolResultArtifacts(raw)
    expect(refs).toHaveLength(1)
    expect(refs[0].path).toBe('E:\\ws\\report.md')
  })

  it('去重：同一路径只出现一次', () => {
    const raw = JSON.stringify({ file_path: 'a.md', output_ref: { path: 'a.md' } })
    expect(parseToolResultArtifacts(raw)).toHaveLength(1)
  })

  it('纯文本/无路径返回空', () => {
    expect(parseToolResultArtifacts('just text')).toEqual([])
    expect(parseToolResultArtifacts(JSON.stringify({ stdout: 'hello' }))).toEqual([])
    expect(parseToolResultArtifacts('')).toEqual([])
  })
})

describe('kindForFilename', () => {
  it('与后端 _artifact_kind 映射对齐', () => {
    expect(kindForFilename('a.md')).toBe('markdown')
    expect(kindForFilename('a.html')).toBe('html')
    expect(kindForFilename('a.png')).toBe('image')
    expect(kindForFilename('a.svg')).toBe('image')
    expect(kindForFilename('a.wav')).toBe('audio')
    expect(kindForFilename('a.json')).toBe('text')
    expect(kindForFilename('noext')).toBe('text')
  })
})

describe('shortHash', () => {
  it('稳定且冲突可辨', () => {
    expect(shortHash('abc')).toBe(shortHash('abc'))
    expect(shortHash('abc')).not.toBe(shortHash('abd'))
  })
})

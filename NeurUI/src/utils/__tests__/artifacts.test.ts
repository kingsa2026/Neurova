/**
 * artifacts 工具契约测试（产物预览 W4）。
 *
 * 锁定：
 * - parseToolResultArtifacts：JSON dict 精确解析 + 截断 JSON 正则兜底 +
 *   output_ref 嵌套 + 去重；
 * - kindForFilename 扩展名映射（与后端 _artifact_kind 对齐）；
 * - shortHash 稳定性；
 * - 消息级产出物收集（2026-09-08 产出物卡片）：读形态过滤（与后端
 *   extract_tool_artifacts 同契约）/ artifactFromEvent / mergeMessageArtifacts 去重。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import {
  fetchContentObjectUrl,
  artifactContentObjectUrl,
  fileContentObjectUrl,
  kindForFilename,
  parseToolResultArtifacts,
  shortHash,
  isReadBackReference,
  artifactFromEvent,
  artifactsFromToolResult,
  mergeMessageArtifacts,
  artifactUiIcon,
  openArtifactTab,
  openMessageArtifact,
  type MessageArtifact,
} from '../artifacts'
import { useRightDockStore } from '@/stores/rightDock'

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
      // output_ref.path 本身仍是合法提取源（2026-11-14 起仅排除内部引用形态：
      // tool_outputs/ 目录与 ref_*.json 命名，见下方专测）
      output_ref: { path: 'E:\\ws\\fetched.json', size_bytes: 99 },
    })
    const paths = parseToolResultArtifacts(raw).map((r) => r.path)
    expect(paths).toContain('C:\\Temp\\neurova_tts\\tts_1.wav')
    expect(paths).toContain('E:\\ws\\fetched.json')
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

  it('OutputRef 内部引用（tool_outputs/、ref_*.json）不提取——与后端注册侧同契约', () => {
    // 2026-11-14 实测残差：后端注册侧排除后 SSE artifact 事件不再发，
    // 但 tool_result 文本仍带 output_ref.path——前端兜底通道若不同步排除，
    // ref_*.json 依旧顶进产出物卡片，且因无 artifactId 点开必报"产物内容不可用"。
    const raw = JSON.stringify({
      success: true,
      output_ref: {
        path: 'E:\\ws\\tool_outputs\\ref_1794595742_run_code_22a5.json',
        size_bytes: 14296,
        truncated: true,
        preview: '{}',
      },
      note: '工具 run_code 输出超阈值，完整内容已落盘',
    })
    expect(parseToolResultArtifacts(raw)).toEqual([])
    expect(artifactsFromToolResult(raw)).toEqual([])
    // 正则兜底通道（半截 JSON）同样排除
    const truncated = '{"output_ref": {"path": "E:\\\\ws\\\\tool_outputs\\\\ref_1_x.json"'
    expect(parseToolResultArtifacts(truncated)).toEqual([])
  })

  it('混合结果：真实文件保留，OutputRef 引用剔除', () => {
    const mixed = JSON.stringify({
      success: true,
      file_path: 'E:\\ws\\报告.md',
      output_ref: { path: 'E:\\ws\\tool_outputs\\ref_1.json' },
    })
    const refs = parseToolResultArtifacts(mixed)
    expect(refs).toHaveLength(1)
    expect(refs[0].path).toBe('E:\\ws\\报告.md')
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

describe('消息级产出物收集（产出物卡片契约）', () => {
  it('isReadBackReference：读形态 {content, file_path} 判真，写形态判假', () => {
    expect(isReadBackReference(JSON.stringify({ content: '# md', file_path: 'a.md' }))).toBe(true)
    expect(isReadBackReference(JSON.stringify({ success: true, file_path: 'a.md' }))).toBe(false)
    expect(isReadBackReference('just text')).toBe(false)
    expect(isReadBackReference('')).toBe(false)
  })

  it('artifactsFromToolResult：写形态提取产出，读形态返回空', () => {
    const write = artifactsFromToolResult(JSON.stringify({ success: true, file_path: 'E:\\ws\\calc.html' }))
    expect(write).toHaveLength(1)
    expect(write[0]).toMatchObject({ name: 'calc.html', kind: 'html', path: 'E:\\ws\\calc.html' })

    const read = artifactsFromToolResult(JSON.stringify({ content: '...', file_path: 'E:\\ws\\calc.html' }))
    expect(read).toEqual([])
  })

  it('artifactFromEvent：SSE 事件转产出物项；name 缺省从 path 取 basename', () => {
    const a = artifactFromEvent({ artifact_id: 'ar1', kind: 'markdown', name: 'report.md', size: 120 })
    expect(a).toMatchObject({ artifactId: 'ar1', name: 'report.md', kind: 'markdown', size: 120 })
    const b = artifactFromEvent({ artifact_id: 'ar2', kind: 'text', name: '', path: 'E:\\ws\\x.json' })
    expect(b?.name).toBe('x.json')
    expect(artifactFromEvent({ artifact_id: '', kind: '', name: '' })).toBeNull()
  })

  it('mergeMessageArtifacts：按 name 去重，先到先得保住富信息（artifactId/size）', () => {
    const existing: MessageArtifact[] = [
      { artifactId: 'ar1', name: 'calc.html', kind: 'html', size: 2048 },
    ]
    const merged = mergeMessageArtifacts(existing, [
      { name: 'calc.html', kind: 'html' }, // 兜底通道重复——丢弃保住 artifactId
      { name: 'note.md', kind: 'markdown' },
    ])
    expect(merged).toHaveLength(2)
    expect(merged[0].artifactId).toBe('ar1')
    expect(merged[1].name).toBe('note.md')
    expect(mergeMessageArtifacts(undefined, [])).toEqual([])
  })

  it('mergeMessageArtifacts：兜底通道先到（无 artifactId）时，后到的主通道事件补全 id', () => {
    // 真实时序（2026-11-14 kai 增量版报告实测缺陷）：SSE 事件表里 tool_result
    // 恒先于 artifact（console.py 同一 events 列表顺序吐出）——兜底通道的
    // 无 id 项先占位，主通道富信息项被"先到先得"丢掉 → 产出物卡片的
    // 审验/打开 永远拿不到 artifactId → "产物内容不可用"。
    const existing: MessageArtifact[] = [
      { name: 'Neurova探索报告_2026-11-14增量版.md', kind: 'markdown' },
    ]
    const merged = mergeMessageArtifacts(existing, [
      {
        artifactId: 'ar9',
        name: 'Neurova探索报告_2026-11-14增量版.md',
        kind: 'markdown',
        size: 3697,
      },
    ])
    expect(merged).toHaveLength(1)
    expect(merged[0].artifactId).toBe('ar9')
    expect(merged[0].size).toBe(3697)
  })

  it('openMessageArtifact：同名 dock tab 已有富信息时，不得被无 id 项的 undefined 反向覆盖', () => {
    setActivePinia(createPinia())
    const dock = useRightDockStore()
    // 主通道先开好带 artifactId 的 tab
    openArtifactTab({
      artifact_id: 'ar9',
      kind: 'markdown',
      name: '报告.md',
      size: 10,
      path: 'E:\\ws\\报告.md',
    })
    // 产出物卡片按钮（修复前中间态的无 id 项）再开同一 tab：
    // data 展开合并不得把已得的 artifactId 冲成 undefined
    openMessageArtifact({ name: '报告.md', kind: 'markdown' })
    const tab = dock.tabs.find((t) => t.id === `doc:p${shortHash('报告.md')}`)
    expect(tab).toBeDefined()
    expect(tab?.data.artifactId).toBe('ar9')
  })

  it('artifactUiIcon：kind → UiIcon 图标名，未知 kind 落 file', () => {
    expect(artifactUiIcon('markdown')).toBe('fileText')
    expect(artifactUiIcon('html')).toBe('browser')
    expect(artifactUiIcon('mystery')).toBe('file')
  })
})

// ─────── fetchContentObjectUrl（2026-09-11 直链 401 根治） ───────
// 内容端点（/artifacts/{id}/content、/files/{id}/download）有 JWT+属主鉴权，
// img/audio/iframe 直链必 401；助手必须经 axios(Bearer) 取 blob 转 object URL。
import { api } from '@/api'

vi.mock('@/api', () => ({
  api: { get: vi.fn() },
}))

describe('fetchContentObjectUrl（Bearer-blob 助手）', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset()
    Object.defineProperty(URL, 'createObjectURL', {
      value: vi.fn(() => 'blob:mock-1'),
      writable: true,
      configurable: true,
    })
  })

  it('请求带 responseType blob 且透传端点路径，返回 object URL', async () => {
    vi.mocked(api.get).mockResolvedValue(new Blob(['x']))
    const url = await fetchContentObjectUrl('/files/f1/download')
    expect(api.get).toHaveBeenCalledWith('/files/f1/download', { responseType: 'blob' })
    expect(url).toBe('blob:mock-1')
  })

  it('artifactContentObjectUrl / fileContentObjectUrl 走各自鉴权端点（同源相对路径）', async () => {
    vi.mocked(api.get).mockResolvedValue(new Blob(['x']))
    await artifactContentObjectUrl('a1')
    await fileContentObjectUrl('f2')
    const paths = vi.mocked(api.get).mock.calls.map((c) => c[0])
    expect(paths).toEqual(['/artifacts/a1/content', '/files/f2/download'])
    for (const p of paths) {
      expect(String(p).startsWith('/api/')).toBe(false) // axios 实例已带 /api/v1 baseURL，避免双前缀
    }
  })

  it('端点失败时异常上抛（调用方进入错误态，不落地假 URL）', async () => {
    vi.mocked(api.get).mockRejectedValue(new Error('401'))
    await expect(fileContentObjectUrl('f3')).rejects.toThrow('401')
  })
})

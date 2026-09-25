/**
 * dock PDF 预览面板契约（工单 007）。
 *
 * 修的现实问题：PDF 既不在后端 artifacts_api._KIND_BY_EXT 也不在前端 KIND_BY_EXT，
 * 于是产物卡点开 PDF 掉进 text 面板，把二进制按文本渲染。
 *
 * 两条既有纪律在本面板的延伸：
 * - object URL 所有权（台账 #11/#12）：面板只 revoke 自己创建的；
 * - 资源标签带不了 Authorization 头 → 直链必须经 withFileToken 追加 ?access_token=。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import PdfPreviewPanel from '@/components/chat/dock/panels/PdfPreviewPanel.vue'
import { kindForFilename } from '@/utils/artifacts'
import type { DockTab } from '@/stores/rightDock'

vi.mock('@/utils/artifacts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/utils/artifacts')>()
  return {
    ...actual,
    artifactContentObjectUrl: vi.fn(async (id: string) => `blob:pdf-artifact-${id}`),
    fileContentObjectUrl: vi.fn(async (id: string) => `blob:pdf-file-${id}`),
  }
})

const revokeMock = vi.fn()
;(URL as unknown as Record<string, unknown>).revokeObjectURL = revokeMock

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': {} } })

function makeTab(data: DockTab['data'], id = 'p1'): DockTab {
  return { id, kind: 'pdf', title: '月报.pdf', icon: 'file', data, openedAt: 0 }
}

function mountPanel(tab: DockTab) {
  return mount(PdfPreviewPanel, { props: { tab }, global: { plugins: [i18n] } })
}

describe('dock PDF 面板', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    localStorage.setItem('auth_token', 'TOK123')
  })

  it('.pdf 文件名分派到 pdf kind 而非退化成 text', () => {
    expect(kindForFilename('月报.pdf')).toBe('pdf')
  })

  it('直链经鉴权凭证追加后交给原生查看器', async () => {
    const wrapper = mountPanel(makeTab({ url: '/api/v1/generation/files/a.pdf' }))
    await flushPromises()
    const embed = wrapper.find('embed')
    expect(embed.exists()).toBe(true)
    expect(embed.attributes('src')).toContain('access_token=TOK123')
  })

  it('直链不是面板创建的，卸载时不得 revoke', async () => {
    const wrapper = mountPanel(makeTab({ url: '/api/v1/generation/files/a.pdf' }))
    await flushPromises()
    wrapper.unmount()
    expect(revokeMock).not.toHaveBeenCalled()
  })

  it('artifactId 走 Bearer 取流并由面板释放', async () => {
    const { artifactContentObjectUrl } = await import('@/utils/artifacts')
    const wrapper = mountPanel(makeTab({ artifactId: 'art7' }))
    await flushPromises()
    expect(artifactContentObjectUrl).toHaveBeenCalledWith('art7')
    expect(wrapper.find('embed').attributes('src')).toBe('blob:pdf-artifact-art7')
    wrapper.unmount()
    expect(revokeMock).toHaveBeenCalledWith('blob:pdf-artifact-art7')
  })

  it('无来源时给出可见空态而不是空白面板', () => {
    const wrapper = mountPanel(makeTab({}))
    expect(wrapper.find('embed').exists()).toBe(false)
    expect(wrapper.text()).toContain('chat.artifactUnavailable')
  })

  it('下载失败进入可见错误态，不静默吞掉', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('network down')
      }),
    )
    const wrapper = mountPanel(makeTab({ url: '/api/v1/generation/files/a.pdf' }))
    await flushPromises()
    await wrapper.find('button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('chat.artifactUnavailable')
    vi.unstubAllGlobals()
  })
})

/**
 * dock 图片/音频预览面板 object URL 所有权契约（台账 #11/#12，2026-09-11）。
 *
 * 根修契约：面板只 revoke 自己负责的 URL，分两类——
 * 1. 面板自建（artifactId/fileId 经 fetch 转 object URL）；
 * 2. 调用方为本面板专属创建并标记 `data.createdBy === 'panel'` 的 url
 *    （ChatPage 附件预览 fetch 自建 blob，所有权随 tab 转移给面板）。
 * 外来 URL（服务端直链 / 消息自有 blob / data URL）一律不 revoke：
 * 消息 blob 由 store.revokeMessageBlobUrls 统一释放（#12 锁存：内联图
 * img.src 走 openImageTab 无标记，将来嵌 blob: 也不会被面板误撤）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import ImagePreviewPanel from '@/components/chat/dock/panels/ImagePreviewPanel.vue'
import AudioPreviewPanel from '@/components/chat/dock/panels/AudioPreviewPanel.vue'
import type { DockTab } from '@/stores/rightDock'

vi.mock('@/utils/artifacts', () => ({
  artifactContentObjectUrl: vi.fn(async (id: string) => `blob:panel-artifact-${id}`),
  fileContentObjectUrl: vi.fn(async (id: string) => `blob:panel-file-${id}`),
}))

const revokeMock = vi.fn()
;(URL as unknown as Record<string, unknown>).revokeObjectURL = revokeMock

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': {} } })

function makeTab(data: DockTab['data'], id = 't1'): DockTab {
  return { id, kind: 'image', title: 't', icon: 'image', data, openedAt: 0 }
}

function revokeCalls(): string[] {
  return revokeMock.mock.calls.map((c) => String(c[0]))
}

function mountPanel(component: typeof ImagePreviewPanel | typeof AudioPreviewPanel, tab: DockTab) {
  return mount(component, { props: { tab }, global: { plugins: [i18n] } })
}

describe.each([
  ['ImagePreviewPanel', ImagePreviewPanel],
  ['AudioPreviewPanel', AudioPreviewPanel],
])('%s object URL 所有权（#11）', (_name, component) => {
  beforeEach(() => {
    revokeMock.mockClear()
  })

  it('外来 blob URL（无 createdBy 标记）卸载时不被 revoke（消息自有 blob 回归点）', async () => {
    const wrapper = mountPanel(component, makeTab({ url: 'blob:message-owned-1' }))
    await flushPromises()
    wrapper.unmount()
    expect(revokeCalls()).not.toContain('blob:message-owned-1')
  })

  it('外来服务端 URL（无 createdBy 标记）卸载时不被 revoke（#12 内联图锁存）', async () => {
    const wrapper = mountPanel(component, makeTab({ url: 'https://srv.example/x.png' }))
    await flushPromises()
    wrapper.unmount()
    expect(revokeMock).not.toHaveBeenCalled()
  })

  it("data.url + createdBy:'panel'（调用方为面板专属创建）卸载时 revoke", async () => {
    const wrapper = mountPanel(component, makeTab({ url: 'blob:caller-made-1', createdBy: 'panel' }))
    await flushPromises()
    wrapper.unmount()
    expect(revokeCalls()).toContain('blob:caller-made-1')
  })

  it('artifactId 路径：面板自建 URL 卸载时 revoke（既有行为锁存）', async () => {
    const wrapper = mountPanel(component, makeTab({ artifactId: 'A1' }))
    await flushPromises()
    expect(wrapper.find('img, audio, .nr-dock-error').exists()).toBe(true)
    wrapper.unmount()
    expect(revokeCalls()).toContain('blob:panel-artifact-A1')
  })

  it('换源：自建 URL 被 revoke，随后换入的外来 URL 不被 revoke', async () => {
    const wrapper = mountPanel(component, makeTab({ artifactId: 'A1' }))
    await flushPromises()
    await wrapper.setProps({ tab: makeTab({ url: 'https://srv.example/y.png' }) })
    await flushPromises()
    wrapper.unmount()
    const calls = revokeCalls()
    expect(calls.filter((u) => u === 'blob:panel-artifact-A1')).toHaveLength(1)
    expect(calls).not.toContain('https://srv.example/y.png')
  })
})

// ── 台账 N5（2026-09-11）：svg 代码块 dock 预览 ──
// openCodeBlockTab 的 svg 走 kind:'image' 但只带 content——旧实现三分支
// 都不命中，视口恒空白。根修：面板自建 SVG blob URL（所有权归面板）。
describe('ImagePreviewPanel svg content 分支（N5）', () => {
  const createMock = vi.fn((blob: Blob) => `blob:svg-${createMock.mock.calls.length}`)
  ;(URL as unknown as Record<string, unknown>).createObjectURL = createMock

  beforeEach(() => {
    revokeMock.mockClear()
    createMock.mockClear()
  })

  it('content+language=svg 的 tab 渲染 <img> 且 src 为面板自建 blob URL', async () => {
    const wrapper = mountPanel(
      ImagePreviewPanel,
      makeTab({ content: '<svg xmlns="http://www.w3.org/2000/svg"></svg>', language: 'svg' }),
    )
    await flushPromises()
    const img = wrapper.find('img')
    expect(img.exists()).toBe(true)
    expect(img.attributes('src')).toMatch(/^blob:svg-/)
    wrapper.unmount()
    expect(revokeCalls()).toContain(img.attributes('src') as string)
  })

  it('非 svg content 不走图片分支（视口无 <img>，不建 URL）', async () => {
    const wrapper = mountPanel(
      ImagePreviewPanel,
      makeTab({ content: 'print(hello)', language: 'python' }),
    )
    await flushPromises()
    expect(wrapper.find('img').exists()).toBe(false)
    expect(createMock).not.toHaveBeenCalled()
    wrapper.unmount()
    expect(revokeMock).not.toHaveBeenCalled()
  })

  it('svg tab 之间切换：旧自建 URL 被 revoke、渲染新图（watch 源含 content）', async () => {
    const wrapper = mountPanel(
      ImagePreviewPanel,
      makeTab({ content: '<svg id="a"></svg>', language: 'svg' }, 'svg-a'),
    )
    await flushPromises()
    const firstSrc = wrapper.find('img').attributes('src')
    await wrapper.setProps({
      tab: makeTab({ content: '<svg id="b"></svg>', language: 'svg' }, 'svg-b'),
    })
    await flushPromises()
    const secondSrc = wrapper.find('img').attributes('src')
    expect(secondSrc).not.toBe(firstSrc)
    wrapper.unmount()
    expect(revokeCalls()).toContain(firstSrc as string)
    expect(revokeCalls()).toContain(secondSrc as string)
  })
})

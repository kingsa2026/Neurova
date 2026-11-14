/**
 * MessageContent — 正文产物文件名可点击（2026-11-14 用户口径）。
 *
 * 契约：props.artifacts 提供本轮产物表时，正文里点名的文件名渲染为
 * nr-artifact-ref 可点击元素；点击 emit openArtifact(artifact)——
 * 由宿主（ChatPage）接 openMessageArtifact 开右侧预览面板。
 */
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia } from 'pinia'
import MessageContent from '../chat/MessageContent.vue'
import type { MessageArtifact } from '@/utils/artifacts'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': { common: { copy: '复制' } } },
})

const ARTS: MessageArtifact[] = [
  { artifactId: 'abc123', name: '报告.md', kind: 'markdown', size: 8290, path: 'E:\\ws\\报告.md' },
]

function mountContent(props: { content: string; artifacts?: MessageArtifact[] }) {
  return mount(MessageContent, {
    props: { ...props },
    global: { plugins: [i18n, createPinia()] },
  })
}

describe('MessageContent — 产物文件名链接', () => {
  it('点名产物渲染为 nr-artifact-ref', () => {
    const w = mountContent({ content: '产物：`报告.md` 已就绪', artifacts: ARTS })
    const btn = w.find('.nr-artifact-ref')
    expect(btn.exists()).toBe(true)
    expect(btn.attributes('data-artifact-id')).toBe('abc123')
  })

  it('点击 → emit openArtifact(产物)', async () => {
    const w = mountContent({ content: '产物：`报告.md` 已就绪', artifacts: ARTS })
    await w.find('.nr-artifact-ref').trigger('click')
    const evts = w.emitted('openArtifact')
    expect(evts).toHaveLength(1)
    expect(evts?.[0]?.[0]).toMatchObject({ name: '报告.md', artifactId: 'abc123' })
  })

  it('无产物表时不渲染链接（旧会话/房间消息零变化）', () => {
    const w = mountContent({ content: '产物：`报告.md` 已就绪' })
    expect(w.find('.nr-artifact-ref').exists()).toBe(false)
    expect(w.html()).toContain('<code>报告.md</code>')
  })
})

/**
 * ArtifactCard — 回答结尾产出物卡片组件测试（2026-09-08）。
 *
 * 对齐 QwenPaw「已更改文件」形态契约：
 * 1. 渲染：头部计数 + 产出物行（图标/文件名/目录/大小/审验/打开）；
 * 2. 收纳展开：点头部切换列表显隐（默认展开）；
 * 3. 审验 → emit review(item)；打开 → emit open(item)。
 */
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import ArtifactCard from '../chat/ArtifactCard.vue'
import type { MessageArtifact } from '@/utils/artifacts'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      chat: {
        artifactCount: '本轮产出物（{n}）',
        artifactReview: '审验',
        artifactOpen: '打开',
        artifactReviewTip: '在右侧面板查看源码（审读形态）',
        artifactOpenTip: '在右侧面板预览渲染效果',
      },
      ui: {
        expand: '展开',
        minimize: '收起',
      },
    },
  },
})

const ITEMS: MessageArtifact[] = [
  { artifactId: 'ar1', name: 'calculator.html', kind: 'html', size: 2048, path: 'E:\\ws\\calculator.html' },
  { name: 'note.md', kind: 'markdown', size: 120 },
]

function mountCard(props: { artifacts: MessageArtifact[]; defaultOpen?: boolean } = { artifacts: ITEMS }) {
  return mount(ArtifactCard, {
    props,
    global: { plugins: [i18n] },
  })
}

describe('ArtifactCard', () => {
  it('头部显示计数，行渲染文件名/大小/审验/打开按钮', () => {
    const w = mountCard()
    expect(w.text()).toContain('本轮产出物（2）')
    expect(w.text()).toContain('calculator.html')
    expect(w.text()).toContain('2.0 KB')
    const btns = w.findAll('button').map((b) => b.text())
    expect(btns.filter((t) => t === '审验')).toHaveLength(2)
    expect(btns.filter((t) => t === '打开')).toHaveLength(2)
  })

  it('默认展开；点头部收纳后再展开', async () => {
    const w = mountCard()
    expect(w.find('.nr-artifact-list').exists()).toBe(true)
    await w.find('.nr-artifact-head').trigger('click')
    expect(w.find('.nr-artifact-list').exists()).toBe(false)
    await w.find('.nr-artifact-head').trigger('click')
    expect(w.find('.nr-artifact-list').exists()).toBe(true)
  })

  it('defaultOpen=false 初始收纳', () => {
    const w = mountCard({ artifacts: ITEMS, defaultOpen: false })
    expect(w.find('.nr-artifact-list').exists()).toBe(false)
  })

  it('点审验 emit review(item)；点打开 emit open(item)——携带完整数据项', async () => {
    const w = mountCard()
    const rows = w.findAll('.nr-artifact-row')
    await rows[0].findAll('button')[0].trigger('click')
    await rows[0].findAll('button')[1].trigger('click')
    expect(w.emitted('review')?.[0]?.[0]).toMatchObject({ name: 'calculator.html', artifactId: 'ar1' })
    expect(w.emitted('open')?.[0]?.[0]).toMatchObject({ name: 'calculator.html' })
  })

  it('空列表不渲染头部计数异常（n=0 也安全）', () => {
    const w = mountCard({ artifacts: [] })
    expect(w.text()).toContain('本轮产出物（0）')
  })
})

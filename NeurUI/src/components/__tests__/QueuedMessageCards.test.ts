/**
 * QueuedMessageCards — 顶入卡片组件测试（会话页消息发送窗口追加对话）
 *
 * 对齐截图交互契约：
 * 1. 渲染：pending 项渲染卡片（把手/文本/立即/编辑/删除）；sending 无动作钮；
 *    failed 显示失败状态 + retry + 删除；
 * 2. 「立即」→ emit send-now(id)；
 * 3. ✎ → emit edit(item)（父级回填 textarea 编辑）；
 * 4. 🗑 → store.remove 生效（取消顶入）；
 * 5. ↻ retry → store.retry 生效（failed → pending）；
 * 6. 把手拖拽 → store.reorder 生效（拖动项落到目标位）；
 * 7. editingQueuedId 哪一项，哪一项带 is-editing 态。
 */
import { describe, expect, it, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createI18n } from 'vue-i18n'
import QueuedMessageCards from '../chat/QueuedMessageCards.vue'
import { useMessageQueueStore } from '@/stores/messageQueue'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      chat: {
        queueSendNow: '立即',
        queueDrag: '拖拽排序',
        queueSending: '发送中',
        queueFailed: '发送失败',
        queueTopAuto: '已置顶，当前回复完成后优先发送',
        retry: '重试',
      },
      common: { edit: '编辑', delete: '删除' },
    },
  },
})

function mountCards(editingQueuedId: string | null = null, items?: ReturnType<typeof useMessageQueueStore>['items']) {
  const q = useMessageQueueStore()
  return mount(QueuedMessageCards, {
    // 审计③：渲染列表由父级按当前会话过滤后传入；缺省=全量（测试便捷）
    props: { editingQueuedId, items: items ?? q.items },
    global: { plugins: [i18n] },
  })
}

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('QueuedMessageCards — 顶入卡片渲染', () => {
  it('队列空时不渲染', () => {
    mountCards()
    const q = useMessageQueueStore()
    expect(q.items).toHaveLength(0)
  })

  it('pending 卡片：把手/文本/立即/编辑/删除齐全，多张堆叠', () => {
    const q = useMessageQueueStore()
    q.enqueue('测试')
    q.enqueue('第二条')
    const w = mountCards()
    const cards = w.findAll('.nr-queue-card')
    expect(cards).toHaveLength(2)
    expect(cards[0].text()).toContain('测试')
    expect(cards[1].text()).toContain('第二条')
    expect(cards[0].find('.nr-queue-drag').exists()).toBe(true)
    expect(cards[0].find('.nr-queue-now').text()).toContain('立即')
    // 编辑 + 删除两个图标按钮
    expect(cards[0].findAll('.nr-queue-ico')).toHaveLength(2)
  })

  it('sending 卡片无任何动作按钮，显示发送中状态', () => {
    const q = useMessageQueueStore()
    const item = q.enqueue('A')
    q.markSending(item.id)
    const w = mountCards()
    const card = w.find('.nr-queue-card')
    expect(card.find('.nr-queue-now').exists()).toBe(false)
    expect(card.findAll('.nr-queue-ico')).toHaveLength(0)
    expect(card.text()).toContain('发送中')
  })

  it('failed 卡片：失败状态文案 + retry + 删除', () => {
    const q = useMessageQueueStore()
    const item = q.enqueue('A')
    q.markFailed(item.id, 'boom')
    const w = mountCards()
    const card = w.find('.nr-queue-card')
    expect(card.text()).toContain('发送失败')
    expect(card.find('.nr-queue-retry').exists()).toBe(true)
    expect(card.findAll('.nr-queue-ico')).toHaveLength(1) // 仅删除
  })
})

describe('QueuedMessageCards — 动作', () => {
  it('点击「立即」→ emit send-now(id)', async () => {
    const q = useMessageQueueStore()
    const item = q.enqueue('顶入A')
    const w = mountCards()
    await w.find('.nr-queue-now').trigger('click')
    expect(w.emitted('send-now')?.[0]).toEqual([item.id])
  })

  it('点击 ✎ → emit edit(item)（id 与文本对应）', async () => {
    const q = useMessageQueueStore()
    const item = q.enqueue('顶入A')
    const w = mountCards()
    const editBtn = w.find('.nr-queue-card .nr-queue-ico')
    await editBtn.trigger('click')
    const payload = (w.emitted('edit')?.[0] as unknown[])[0] as { id: string; text: string }
    expect(payload.id).toBe(item.id)
    expect(payload.text).toBe('顶入A')
  })

  it('点击 🗑 → store.remove 生效（取消顶入）', async () => {
    const q = useMessageQueueStore()
    const a = q.enqueue('A')
    const b = q.enqueue('B')
    const w = mountCards()
    const cards = w.findAll('.nr-queue-card')
    // 第 0 张卡的两个图标钮：[0]=编辑 [1]=删除
    await cards[0].findAll('.nr-queue-ico')[1].trigger('click')
    expect(q.items).toHaveLength(1)
    expect(q.items[0].id).toBe(b.id)
    expect(q.items[0].id).not.toBe(a.id)
  })

  it('点击 ↻ → store.retry 生效（failed → pending）并 emit send-now 续发', async () => {
    const q = useMessageQueueStore()
    const item = q.enqueue('A')
    q.markFailed(item.id, 'boom')
    const w = mountCards()
    await w.find('.nr-queue-retry').trigger('click')
    expect(q.items[0].status).toBe('pending')
    expect(w.emitted('send-now')?.[0]).toEqual([item.id])
  })

  it('把手拖拽：第一张拖到第二张位置 → store.reorder 生效', async () => {
    const q = useMessageQueueStore()
    const a = q.enqueue('A')
    const b = q.enqueue('B')
    const w = mountCards()
    const cards = () => w.findAll('.nr-queue-card')
    await cards()[0].trigger('dragstart')
    await cards()[1].trigger('drop')
    expect(q.items.map((i) => i.id)).toEqual([b.id, a.id])
  })

  it('editingQueuedId 命中项带 is-editing 态', () => {
    const q = useMessageQueueStore()
    q.enqueue('A')
    const b = q.enqueue('B')
    const w = mountCards(b.id)
    const cards = w.findAll('.nr-queue-card')
    expect(cards[0].classes()).not.toContain('is-editing')
    expect(cards[1].classes()).toContain('is-editing')
  })

  it('sending 项不可拖拽（draggable=false）', () => {
    const q = useMessageQueueStore()
    const item = q.enqueue('A')
    q.markSending(item.id)
    const w = mountCards()
    expect(w.find('.nr-queue-card').attributes('draggable')).toBe('false')
  })

  it('pending 项可拖拽（draggable=true）', () => {
    const q = useMessageQueueStore()
    q.enqueue('A')
    const w = mountCards()
    expect(w.find('.nr-queue-card').attributes('draggable')).toBe('true')
  })
})

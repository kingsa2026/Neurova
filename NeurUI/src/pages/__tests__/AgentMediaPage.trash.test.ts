/**
 * AgentMediaPage 回收站面（§6-158，工单 2026-10-12 批 13，裁定乙）。
 *
 * 这里锁的是四件事，全是"后端四件落地后前端最容易被顺手改坏"的形态：
 * 1. 回收站开关换的是**读接口**（GET /media/list ↔ GET /media/trash），不是本地过滤——
 *    本地过滤看不见未加载的条目，正是台账 2026-09-11 ③ 修过的那条老路；
 * 2. 库里的「删除」调用点**不带 mode**（默认硬删）；翻成软删＝把现役页面的既有承诺改掉，
 *    而那是对用户可见的隐私语义变更，不在本批授权内；
 * 3. 回收站里的动作只有「恢复」与「彻底删除」，且彻底删除显式带 `permanent`；
 * 4. 回收站条目不去拉现役内容面（`GET /media/{id}` 对它必 404），否则预览会显示成"还在"。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

const { messageMock, modalMock } = vi.hoisted(() => ({
  messageMock: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
  modalMock: vi.fn(),
}))

vi.mock('ant-design-vue', () => ({
  message: messageMock,
  Modal: { confirm: modalMock },
}))

const {
  listMediaMock, listTrashMock, getMediaMock, deleteMediaMock, moveToTrashMock, restoreMediaMock,
} = vi.hoisted(() => ({
  listMediaMock: vi.fn(),
  listTrashMock: vi.fn(),
  getMediaMock: vi.fn(),
  deleteMediaMock: vi.fn(),
  moveToTrashMock: vi.fn(),
  restoreMediaMock: vi.fn(),
}))

vi.mock('@/api/modules/media', () => ({
  listMedia: listMediaMock,
  listTrash: listTrashMock,
  getMedia: getMediaMock,
  getMediaInfo: vi.fn(),
  downloadMedia: vi.fn(),
  deleteMedia: deleteMediaMock,
  moveToTrash: moveToTrashMock,
  restoreMedia: restoreMediaMock,
  batchDeleteMedia: vi.fn(),
  saveMedia: vi.fn(),
}))

import AgentMediaPage from '@/pages/AgentMediaPage.vue'

const stubs = {
  GlassPanel: { template: '<div class="glass-panel"><slot /></div>' },
  GlassCard: { template: '<div class="glass-card"><slot /></div>' },
  // 必须声明 emits：不声明时父级的 @click 既作为组件监听器、又作为原生 fallthrough
  // 挂在这个 <button> 根上，一次 trigger('click') 会跑两遍处理函数——开关被翻两次，
  // 断言就会对着"回到库里"的 DOM 找回收站按钮（实测就这么假失败过）。
  GlassButton: {
    emits: ['click'],
    template: `<button class="glass-btn" @click="$emit('click')"><slot /></button>`,
  },
  'a-spin': { template: '<div><slot /></div>' },
  'a-empty': { template: '<div class="a-empty"><slot /></div>' },
  'a-input-search': true,
  'a-radio-group': true,
  'a-radio-button': true,
  'a-segmented': true,
  'a-pagination': true,
  'a-modal': true,
  'a-table': true,
  'a-tag': true,
  'a-space': { template: '<div><slot /></div>' },
}

const MESSAGES: Record<string, string> = {
  'media.trash': '回收站',
  'media.exitTrash': '退出回收站',
  'media.moveToTrash': '移入回收站',
  'media.restore': '恢复',
  'media.deleteForever': '彻底删除',
  'common.delete': '删除',
  'media.download': '下载',
  'media.detail': '详情',
}

function envelope(items: { media_id: string; filename: string; is_deleted?: boolean; deleted_at?: number }[]) {
  return {
    code: 0,
    message: 'ok',
    data: {
      media: items.map((m) => ({
        media_id: m.media_id,
        filename: m.filename,
        media_type: 'image',
        mime_type: 'image/png',
        size: 10,
        agent_id: 'a1',
        user_id: null,
        memory_id: null,
        storage_path: `media_storage/a1/image/${m.media_id}_${m.filename}`,
        created_at: 1760000000,
        metadata: {},
        is_deleted: m.is_deleted ?? false,
        deleted_at: m.deleted_at,
      })),
      total: items.length,
      offset: 0,
      limit: 50,
    },
  }
}

function mountPage() {
  const nested = { media: {}, common: {} } as Record<string, Record<string, string>>
  for (const [key, value] of Object.entries(MESSAGES)) {
    const [section, name] = key.split('.')
    nested[section][name] = value
  }
  const i18n = createI18n({
    legacy: false,
    locale: 'zh-CN',
    missingWarn: false,
    fallbackWarn: false,
    messages: { 'zh-CN': nested },
  })
  return mount(AgentMediaPage, { props: { agentId: 'a1' }, global: { plugins: [i18n], stubs } })
}

function buttonsOf(wrapper: ReturnType<typeof mountPage>) {
  return wrapper.findAll('button.glass-btn').map((b) => ({
    label: b.text().trim(),
    click: () => b.trigger('click'),
  }))
}

/** 把 Modal.confirm 做成"点确认即执行 onOk"，否则前端这层只证了弹窗被调用过。 */
function autoConfirm() {
  modalMock.mockImplementation((options: { onOk?: () => Promise<void> | void }) => {
    void options.onOk?.()
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  autoConfirm()
  listMediaMock.mockResolvedValue(envelope([{ media_id: 'media-1', filename: 'a.png' }]))
  listTrashMock.mockResolvedValue(
    envelope([{ media_id: 'media-9', filename: 'gone.png', is_deleted: true, deleted_at: 1760000500 }]),
  )
  getMediaMock.mockResolvedValue(new Blob(['x']))
  deleteMediaMock.mockResolvedValue({ code: 0 })
  moveToTrashMock.mockResolvedValue({ code: 0 })
  restoreMediaMock.mockResolvedValue({ code: 0 })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('AgentMediaPage 回收站', () => {
  it('首屏读的是媒体库；回收站接口一次都没被调', async () => {
    const wrapper = mountPage()
    await flushPromises()

    expect(listMediaMock).toHaveBeenCalledWith(expect.objectContaining({ agent_id: 'a1' }))
    expect(listTrashMock).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('开关切到回收站走 GET /media/trash（不是把 /list 的结果本地过滤）', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const toggle = buttonsOf(wrapper).find((b) => b.label === MESSAGES['media.trash'])
    expect(toggle, '工具栏上没有「回收站」开关').toBeTruthy()
    await toggle!.click()
    await flushPromises()

    expect(listTrashMock).toHaveBeenCalledWith(expect.objectContaining({ agent_id: 'a1' }))
    expect(wrapper.text()).toContain('gone.png')
    wrapper.unmount()
  })

  it('回收站视图不提供现役内容面的取物调用（GET /media/{id} 对它必 404）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    getMediaMock.mockClear()

    const toggle = buttonsOf(wrapper).find((b) => b.label === MESSAGES['media.trash'])
    await toggle!.click()
    await flushPromises()

    expect(getMediaMock).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('回收站里的动作只有「恢复」与「彻底删除」，没有第 3 个按钮', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const toggle = buttonsOf(wrapper).find((b) => b.label === MESSAGES['media.trash'])
    await toggle!.click()
    await flushPromises()

    const labels = buttonsOf(wrapper).map((b) => b.label)
    expect(labels.filter((l) => l === MESSAGES['media.restore'])).toHaveLength(1)
    expect(labels.filter((l) => l === MESSAGES['media.deleteForever'])).toHaveLength(1)
    expect(labels).not.toContain(MESSAGES['media.moveToTrash'])
    expect(labels).not.toContain(MESSAGES['common.delete'])
    wrapper.unmount()
  })

  it('「恢复」打的是 POST /media/{id}/restore，成功后重拉回收站', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const toggle = buttonsOf(wrapper).find((b) => b.label === MESSAGES['media.trash'])
    await toggle!.click()
    await flushPromises()
    listTrashMock.mockClear()

    const restore = buttonsOf(wrapper).find((b) => b.label === MESSAGES['media.restore'])
    await restore!.click()
    await flushPromises()

    expect(restoreMediaMock).toHaveBeenCalledWith('media-9')
    expect(listTrashMock).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('「彻底删除」显式带 permanent——不依赖后端的缺省档', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const toggle = buttonsOf(wrapper).find((b) => b.label === MESSAGES['media.trash'])
    await toggle!.click()
    await flushPromises()

    const forever = buttonsOf(wrapper).find((b) => b.label === MESSAGES['media.deleteForever'])
    await forever!.click()
    await flushPromises()

    expect(deleteMediaMock).toHaveBeenCalledWith('media-9', 'permanent')
    wrapper.unmount()
  })

  it('库里的「删除」不带 mode：默认档仍是硬删（既有承诺没被 UI 翻成软删）', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const del = buttonsOf(wrapper).find((b) => b.label === MESSAGES['common.delete'])
    await del!.click()
    await flushPromises()

    expect(deleteMediaMock).toHaveBeenCalledTimes(1)
    const args = deleteMediaMock.mock.calls[0]
    expect(args[0]).toBe('media-1')
    expect(args[1]).not.toBe('trash')
    wrapper.unmount()
  })

  it('库里另有「移入回收站」这一档，且它不改默认删除的调用点', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const trash = buttonsOf(wrapper).find((b) => b.label === MESSAGES['media.moveToTrash'])
    expect(trash, '库里没有「移入回收站」入口').toBeTruthy()
    await trash!.click()
    await flushPromises()

    expect(moveToTrashMock).toHaveBeenCalledWith('media-1')
    expect(deleteMediaMock).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})

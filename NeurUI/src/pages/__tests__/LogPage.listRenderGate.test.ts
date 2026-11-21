/**
 * 关键列表渲染回归门（追平计划 E3）—— 系统日志表格
 *
 * 抽查结论（组件 → 策略 → 本文件用例）：
 * - LogPage.vue（日志表格；数据量随运行时间无上限增长）：
 *   服务端分页——前端每次只请求 page/page_size=50，a-table 仅拿到当前页数据，
 *   pagination 携带 total 供翻页。回归门钉住：大数据集（total=1000）下前端
 *   不整表拉取、不整表渲染，翻页重发分页请求。
 *   → 用例 1：首屏只请求 page=1&page_size=50，表格只渲染 50 行，分页控件存在；
 *   → 用例 2：翻到第 2 页重发 page=2 请求，仍只渲染 50 行。
 * - 同域登记：AuditPage.vue 审计轨迹表以 slice(0, 20) 截断（有界，另一会话在途
 *   改造中，本轮不动）；ChatSessionSidebar.vue 会话列表为无界渲染（已登记未修）。
 *
 * 门径：谁把 page_size 改成全量、或把表格改成整表直挂，本文件即红。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

const listLogsMock = vi.fn()
const clearLogsMock = vi.fn()

vi.mock('@/api/modules/system-logs', () => ({
  listLogs: (...args: unknown[]) => listLogsMock(...args),
  clearLogs: (...args: unknown[]) => clearLogsMock(...args),
}))

vi.mock('ant-design-vue', async () => {
  const actual = await vi.importActual<any>('ant-design-vue')
  return {
    ...actual,
    message: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
  }
})

import Antd from 'ant-design-vue'
import LogPage from '@/pages/LogPage.vue'
import zhCN from '@/i18n/locales/zh-CN'

const PAGE_SIZE = 50
const TOTAL = 1000

function makeLogs(n: number, offset = 0) {
  return Array.from({ length: n }, (_, i) => ({
    id: `log-${offset + i}`,
    timestamp: '2026-11-01T00:00:00Z',
    level: 'info',
    message: `log message ${offset + i}`,
    source: 'test',
  }))
}

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as any } })

function mountLogPage() {
  // antd 组件在 main.ts 全局注册，测试须同径挂载，a-table/a-pagination 才会渲染
  return mount(LogPage, { global: { plugins: [i18n, Antd] } })
}

describe('LogPage 关键列表渲染回归门（服务端分页不退化为整表渲染）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    listLogsMock.mockResolvedValue({ data: { items: makeLogs(PAGE_SIZE), total: TOTAL } })
  })

  it('首屏只请求一页 50 条，表格只渲染 50 行，分页控件标称全量', async () => {
    const wrapper = mountLogPage()
    await flushPromises()

    expect(listLogsMock).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1, page_size: PAGE_SIZE }),
    )

    const rows = wrapper.findAll('.ant-table-tbody tr.ant-table-row')
    expect(rows.length, `total=${TOTAL} 时表格只应渲染当前页 ${PAGE_SIZE} 行`).toBe(PAGE_SIZE)

    expect(wrapper.find('.ant-pagination').exists(), '分页控件必须存在').toBe(true)
    expect(wrapper.find('.ant-pagination-item-2').exists(), 'total=1000/每页 50 须有第 2 页').toBe(true)

    wrapper.unmount()
  })

  it('翻页重发分页请求（page=2），仍只渲染一页', async () => {
    const wrapper = mountLogPage()
    await flushPromises()

    listLogsMock.mockClear()
    listLogsMock.mockResolvedValue({ data: { items: makeLogs(PAGE_SIZE, PAGE_SIZE), total: TOTAL } })

    await wrapper.find('.ant-pagination-item-2').trigger('click')
    await flushPromises()

    expect(listLogsMock).toHaveBeenCalledWith(
      expect.objectContaining({ page: 2, page_size: PAGE_SIZE }),
    )
    expect(wrapper.findAll('.ant-table-tbody tr.ant-table-row').length, '翻页后仍只渲染一页').toBe(PAGE_SIZE)

    wrapper.unmount()
  })
})

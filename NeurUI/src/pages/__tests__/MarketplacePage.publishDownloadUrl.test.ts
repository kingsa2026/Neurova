/**
 * 管理端上架/编辑表单必须能提交「下载地址」，且安装被拒时把拒因原样出声（甲批）。
 *
 * 根因背景：本仓把「零字节安装」改成显式拒绝之后（395c2dca），管理员通过这个弹窗上架的条目
 * 一律装不上——弹窗只有 技能 ID/名称/版本/分类/作者/描述 六个字段，`publishForm.download_url`
 * 恒以空串提交。旧代码里它能"装成功"，是因为那条"跳过下载照样 COMPLETED"的尾巴在替它兜假成功。
 * 所以补字段不是加功能，是把新闸要求的输入接回生产者；同一屏里另一处同类断链：`installItem`
 * 的 catch 只回 `t('common.error')`，把后端逐字点名的「无可取件地址…」折成一句"操作失败"，
 * 管理员看不出自己少填了什么。
 *
 * 三格方向不同：
 * 1. 上架：填了下载地址 ⇒ 提交体带这个词（不是被静默丢掉）。
 * 2. 编辑：条目原有地址要**回填**到输入框并提交回去 ⇒ 编辑一次不会把来源抹成空。
 * 3. 拒因出声：安装被拒时 toast 用后端 detail 原文，不用泛化文案。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

vi.mock('@/api', () => {
  const request = { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() }
  return { request, default: request }
})
vi.mock('@/stores/auth', () => ({ useAuthStore: vi.fn() }))
vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

import MarketplacePage from '@/pages/MarketplacePage.vue'
import zhCN from '@/i18n/locales/zh-CN'
import enUS from '@/i18n/locales/en-US'
import { request } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { message } from 'ant-design-vue'

const REASON = '无可取件地址：条目既无内置技能包（bundle_zip），download_url 也不属已注册远端源'

const messages = {
  marketplace: {
    publishSkill: '上架技能',
    skillId: '技能 ID',
    version: '版本',
    category: '分类',
    author: '作者',
    formCreateTitle: '上架新技能',
    formUpdateTitle: '编辑技能',
    editSkill: '编辑',
    removeSkill: '下架',
    installed: '已安装',
    tabNeuMarket: 'Neu 市场',
    tabInstalled: '已安装',
    syncSources: '同步远端源',
    updateAvailable: '可更新',
    doUpdate: '更新',
    updateSuccess: '已更新',
    updateError: '更新失败',
    uninstall: '卸载',
    installSuccess: '已安装',
    installError: '安装失败',
    removeSuccess: '已下架',
    removeError: '下架失败',
    emptyMarket: '暂无条目',
    detail: '详情',
  },
  market: { submitUrl: '下载地址', submitUrlPh: 'ZIP 包下载链接（可选）' },
  common: {
    name: '名称',
    description: '描述',
    success: '操作成功',
    error: '操作失败',
    open: '打开',
    search: '搜索',
    noData: '暂无数据',
    confirm: '确定',
    cancel: '取消',
  },
  skill: { install: '安装' },
}

const stubs = {
  GlassPanel: { props: ['variant'], template: '<div class="glass-panel"><slot/></div>' },
  GlassCard: {
    props: ['title', 'subtitle'],
    template: '<div class="glass-card">{{ title }}<slot name="header"/><slot/><slot name="footer"/></div>',
  },
  GlassButton: {
    props: ['variant', 'size', 'loading', 'disabled'],
    emits: ['click'],
    template: '<button class="glass-btn" @click="$emit(\'click\')"><slot/></button>',
  },
  'a-button': { props: ['type', 'danger', 'size'], emits: ['click'], template: '<button @click="$emit(\'click\')"><slot/></button>' },
  'a-input-search': { props: ['value', 'placeholder'], emits: ['update:value', 'search'], template: '<input class="search-box" :value="value" />' },
  'a-tabs': { props: ['activeKey'], emits: ['update:activeKey', 'change'], template: '<div class="a-tabs"><slot/></div>' },
  'a-tab-pane': { props: ['key', 'tab'], template: '<div class="a-tab-pane"><slot/></div>' },
  'a-tag': { props: ['color'], template: '<span><slot/></span>' },
  'a-spin': { props: ['spinning'], template: '<div><slot/></div>' },
  'a-empty': { props: ['description'], template: '<div class="a-empty">{{ description }}</div>' },
  'a-rate': { props: ['value', 'disabled', 'allowHalf', 'size'], template: '<span class="a-rate"/>' },
  'a-pagination': { props: ['current', 'pageSize', 'total'], template: '<div class="a-pagination"/>' },
  'a-modal': {
    props: ['open', 'title', 'okText', 'confirmLoading'],
    emits: ['ok', 'update:open'],
    template: '<div v-if="open" class="ant-modal"><h3>{{ title }}</h3><slot/><button class="modal-ok" @click="$emit(\'ok\')">确 定</button></div>',
  },
  'a-form': { props: ['layout', 'model'], template: '<form><slot/></form>' },
  'a-form-item': { props: ['label'], template: '<div class="form-item" :data-label="label"><span class="fi-label">{{ label }}</span><slot/></div>' },
  'a-input': {
    props: ['value', 'placeholder', 'disabled'],
    emits: ['update:value'],
    template: '<input class="ant-input" :value="value" @input="$emit(\'update:value\', $event.target.value)" />',
  },
  'a-textarea': {
    props: ['value', 'rows', 'placeholder'],
    emits: ['update:value'],
    template: '<textarea class="ant-textarea" :value="value" @input="$emit(\'update:value\', $event.target.value)" />',
  },
}

function mountPage() {
  vi.mocked(useAuthStore).mockReturnValue({ user: { role: 'admin', username: 'kingsa' } } as any)
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
  return mount(MarketplacePage, { global: { plugins: [i18n], stubs } })
}

/** 按 a-form-item 的 label 找它内部的输入框（不靠字段顺序，顺序变了也不会假绿）。 */
function fieldByLabel(wrapper: any, label: string) {
  const item = wrapper.findAll('.form-item').find((n: any) => n.attributes('data-label') === label)
  return item ? item.find('input, textarea') : null
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(request.get).mockResolvedValue({ items: [], total: 0 } as any)
  vi.mocked(request.post).mockResolvedValue({ code: 0 } as any)
  vi.mocked(request.put).mockResolvedValue({ code: 0 } as any)
  vi.mocked(request.delete).mockResolvedValue({ code: 0 } as any)
})

describe('管理端上架表单 — 下载地址是提交体的一等字段', () => {
  it('上架弹窗里有「下载地址」输入，提交时随 body 一起出去', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const publishBtn = wrapper.findAll('button').find((b) => b.text().includes('上架技能'))
    expect(publishBtn, '管理员应能看到上架入口').toBeTruthy()
    await publishBtn!.trigger('click')
    await flushPromises()

    const urlField = fieldByLabel(wrapper, '下载地址')
    expect(urlField, '上架弹窗没有「下载地址」输入：新闸要求条目必须有可取件来源，这个输入就是生产者那一段').toBeTruthy()

    await fieldByLabel(wrapper, '技能 ID')!.setValue('probe-skill')
    await fieldByLabel(wrapper, '名称')!.setValue('Probe')
    await urlField!.setValue('https://skills.aliyun.com/probe.zip')
    await wrapper.find('.modal-ok').trigger('click')
    await flushPromises()

    const posted = vi.mocked(request.post).mock.calls.find(([u]) => u === '/marketplace/skills')
    expect(posted, '没走创建提交').toBeTruthy()
    expect((posted![1] as any).download_url).toBe('https://skills.aliyun.com/probe.zip')
  })

  it('编辑既有条目时回填原地址，提交回去不被抹成空串', async () => {
    const original = 'https://skills.aliyun.com/existing.zip'
    vi.mocked(request.get).mockResolvedValue({
      items: [{ skill_id: 'ex1', name: 'Ex', version: '1.0.0', description: 'd', installed: false, download_url: original }],
      total: 1,
    } as any)
    const wrapper = mountPage()
    await flushPromises()

    const editBtn = wrapper.findAll('button').find((b) => b.text().includes('编辑'))
    expect(editBtn, '管理员行内应有编辑入口').toBeTruthy()
    await editBtn!.trigger('click')
    await flushPromises()

    const urlField = fieldByLabel(wrapper, '下载地址')
    expect(urlField, '编辑弹窗同样得有「下载地址」').toBeTruthy()
    expect((urlField as any).element.value).toBe(original)

    await wrapper.find('.modal-ok').trigger('click')
    await flushPromises()

    const put = vi.mocked(request.put).mock.calls.find(([u]) => String(u).includes('/marketplace/skills/ex1'))
    expect(put, '没走更新提交').toBeTruthy()
    expect((put![1] as any).download_url).toBe(original)
  })

  it('安装被拒时 toast 用后端点名的拒因，不折成一句「操作失败」', async () => {
    vi.mocked(request.get).mockResolvedValue({
      items: [{ skill_id: 'zz-probe-no-source', name: 'Ghost', version: '1.0.0', description: 'd', installed: false, download_url: '' }],
      total: 1,
    } as any)
    vi.mocked(request.post).mockImplementation((async (url: string) => {
      if (String(url).endsWith('/install')) {
        throw { response: { data: { detail: REASON } } }
      }
      return { code: 0 }
    }) as any)
    const wrapper = mountPage()
    await flushPromises()

    const installBtn = wrapper.findAll('button').find((b) => b.text().trim() === '安装')
    expect(installBtn, '未装条目应有安装入口').toBeTruthy()
    await installBtn!.trigger('click')
    await flushPromises()

    const shown = vi.mocked(message.error).mock.calls.map((c) => String(c[0]))
    expect(shown.some((s) => s.includes('无可取件地址')),
      `拒因没出声，管理员只能看到：${JSON.stringify(shown)}`).toBe(true)
  })

  it('同页九个失败出口都先取拒因——泛化文案不许再当唯一出处（教义第 5 条扫荡）', () => {
    // 本格只断"形态"：这一页里不得再有直接拿 t('common.error') 当唯一出处的 message.error，
    // 且 errText 的落点数不得低于现算的 9 处——少一处就说明有一处被改回或整段被删。
    const src = readFileSync(resolve(process.cwd(), 'src/pages/MarketplacePage.vue'), 'utf-8')
    expect(src).not.toMatch(/message\.error\(t\('common\.error'\)\)/)
    const wired = (src.match(/errText\(err, t\('common\.error'\)\)/g) ?? []).length
    expect(wired).toBeGreaterThanOrEqual(9)
  })

  it('管理端 placeholder 说的是规则本身，不再借用「可选」那条共享文案', () => {
    // `market.submitUrlPh`（"ZIP 链接（可选）"）在**提交技能**那条路径下确实是可选的——
    // 审核物化可走 pool_skill_id 血缘，不需要 zip。但管理端上架留空，条目就装不上。
    // 两种语义共用一条文案 = 其中一边永远在说谎，所以管理端另起一键，共享键原样留着。
    const src = readFileSync(resolve(process.cwd(), 'src/pages/MarketplacePage.vue'), 'utf-8')
    expect(src).toContain("t('marketplace.downloadUrlPh')")
    expect(src, '管理端仍在借用提交路径的"可选"文案').not.toContain("t('market.submitUrlPh')")

    const zh = String((zhCN as any).marketplace.downloadUrlPh)
    const en = String((enUS as any).marketplace.downloadUrlPh)
    expect(zh).toContain('无法安装')
    expect(en.toLowerCase()).toContain('cannot be installed')
    // 提交路径那一条不许被顺手改掉（它语义正确，动它就是把一边修好把另一边弄坏）
    expect(String((zhCN as any).market.submitUrlPh)).toContain('可选')
  })
})

/**
 * AgentListPage — Agent 应用包导出/导入（P2-16）前端防回归测试。
 *
 * 锁定行为：
 * 1. 导出：exportAgentPackage 被调用 + downloadManifest 触发 Blob 下载
 * 2. 导入：合法 manifest → importAgentPackage 带 provenance.agent_id
 * 3. 导入：非法文件（非 JSON / 非 agent-package kind）→ 拒绝且不调 API
 * 4. 冲突 409 → packageConflict 提示
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

const exportAgentPackage = vi.fn()
const importAgentPackage = vi.fn()
const downloadManifest = vi.fn()

vi.mock('@/api/modules/agent-package', () => ({
  exportAgentPackage: (...args: unknown[]) => exportAgentPackage(...args),
  importAgentPackage: (...args: unknown[]) => importAgentPackage(...args),
  downloadManifest: (...args: unknown[]) => downloadManifest(...args),
}))

vi.mock('@/api/modules/providers', () => ({ listProviders: vi.fn().mockResolvedValue([]) }))
vi.mock('@/api/modules/models', () => ({ listModels: vi.fn().mockResolvedValue([]) }))

vi.mock('ant-design-vue', async () => {
  const actual = await vi.importActual<any>('ant-design-vue')
  return {
    ...actual,
    message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  }
})

import AgentListPage from '@/pages/AgentListPage.vue'
import { message } from 'ant-design-vue'
import { useAgentStore } from '@/stores/agents'
import zhCN from '@/i18n/locales/zh-CN'

const MANIFEST = {
  kind: 'neurova.agent-package',
  manifest_version: 1,
  agent: { name: 'PackAgent', model: 'm', provider: 'p' },
  skills: [],
  cron: [],
  mcp: [],
  provenance: { exported_at: '2026-09-04T00:00:00Z', source: 'neurova', package_version: 1, agent_id: 'packa' },
}

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': zhCN as any },
})

function mountPage() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useAgentStore()
  store.agents.push({
    id: 'default',
    name: 'Neurova',
    description: '',
    model: 'm',
    provider: 'p',
    status: 'active',
    avatar: null,
    createdAt: '',
    updatedAt: '',
    config: {
      systemPrompt: '',
      temperature: 0.7,
      maxTokens: 4096,
      topP: 1.0,
      ttsEnabled: false,
      ttsVoice: '',
      ttsSpeed: 1.0,
      ttsPitch: 1.0,
      tools: [],
      skills: [],
    },
  } as any)
  return mount(AgentListPage, { global: { plugins: [i18n, pinia] } })
}

describe('AgentListPage agent package (P2-16)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
  })

  it('导出成功：调 API 且触发下载', async () => {
    exportAgentPackage.mockResolvedValue({ data: MANIFEST })
    const wrapper = mountPage()
    await flushPromises()

    exportAgentPackage.mockClear()
    downloadManifest.mockClear()

    // 找导出按钮（卡片内第一个 packageExport 文案的按钮）
    const btn = wrapper.findAll('button').find((b) => b.text().includes('导出包'))
    expect(btn).toBeTruthy()
    await btn!.trigger('click')
    await flushPromises()

    expect(exportAgentPackage).toHaveBeenCalledWith('default')
    expect(downloadManifest).toHaveBeenCalledWith(MANIFEST, 'default')
    expect(message.success).toHaveBeenCalled()
  })

  it('导出契约错位（kind 不符）→ 报错不下载', async () => {
    exportAgentPackage.mockResolvedValue({ data: { kind: 'other' } })
    const wrapper = mountPage()
    await flushPromises()

    const btn = wrapper.findAll('button').find((b) => b.text().includes('导出包'))
    await btn!.trigger('click')
    await flushPromises()

    expect(downloadManifest).not.toHaveBeenCalled()
    expect(message.error).toHaveBeenCalled()
  })

  it('导入：非法 manifest 被拒且不调 API', async () => {
    importAgentPackage.mockResolvedValue({ data: { success: true } })
    const wrapper = mountPage()
    await flushPromises()

    const input = wrapper.find('input[type="file"]')
    expect(input.exists()).toBe(true)

    const badFile = new File([JSON.stringify({ kind: 'nope' })], 'bad.json', { type: 'application/json' })
    Object.defineProperty(input.element, 'files', { value: [badFile] })
    await input.trigger('change')
    await flushPromises()

    expect(importAgentPackage).not.toHaveBeenCalled()
    expect(message.error).toHaveBeenCalled()
  })

  it('导入：合法 manifest → importAgentPackage 带 provenance.agent_id，store 刷新', async () => {
    importAgentPackage.mockResolvedValue({
      data: { success: true, agent_id: 'packa', imported: { skills: [], cron: 0, mcp: 0 }, manifest_version: 1 },
    })
    const wrapper = mountPage()
    await flushPromises()

    const store = useAgentStore()
    const loadSpy = vi.spyOn(store, 'loadAgents').mockResolvedValue()

    const input = wrapper.find('input[type="file"]')
    const goodFile = new File([JSON.stringify(MANIFEST)], 'pack.json', { type: 'application/json' })
    Object.defineProperty(input.element, 'files', { value: [goodFile] })
    await input.trigger('change')
    await flushPromises()

    expect(importAgentPackage).toHaveBeenCalledWith(
      expect.objectContaining({ agent_id: 'packa', manifest: MANIFEST }),
    )
    expect(message.success).toHaveBeenCalled()
    expect(loadSpy).toHaveBeenCalled()
  })

  it('导入冲突（already exists）→ packageConflict 提示', async () => {
    importAgentPackage.mockRejectedValue({
      response: { data: { detail: "Agent 'packa' already exists." } },
    })
    const wrapper = mountPage()
    await flushPromises()

    const input = wrapper.find('input[type="file"]')
    const goodFile = new File([JSON.stringify(MANIFEST)], 'pack.json', { type: 'application/json' })
    Object.defineProperty(input.element, 'files', { value: [goodFile] })
    await input.trigger('change')
    await flushPromises()

    expect(message.error).toHaveBeenCalledWith(expect.stringContaining('已存在'))
  })
})

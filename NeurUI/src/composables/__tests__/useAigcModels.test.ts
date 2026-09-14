/**
 * useAigcModels 契约（2026-09-14 AIGC 能力过滤 R2）：
 * 仅显示已配置(connectable)+对应能力模型、auto 置顶、providerOf 反查、
 * 标签带服务商名。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { defineComponent } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'

const listModelsMock = vi.fn()
const listProvidersMock = vi.fn()
vi.mock('@/api/modules/models', () => ({ listModels: () => listModelsMock() }))
vi.mock('@/api/modules/providers', () => ({ listProviders: () => listProvidersMock() }))

import { makeAigcI18n } from '@/pages/aigc/__tests__/testUtils'
import { useAigcModels } from '@/composables/useAigcModels'

const Host = defineComponent({
  setup() {
    return useAigcModels()
  },
  render: () => null,
})

async function setupHost() {
  const wrapper = mount(Host, { global: { plugins: [makeAigcI18n()] } })
  await flushPromises()
  return wrapper.vm as unknown as {
    imageModelOptions: { label: string; value: string; provider_id: string }[]
    videoModelOptions: { value: string }[]
    textModelOptions: { value: string }[]
    providerOf: (id: string) => string
  }
}

describe('useAigcModels 能力过滤', () => {
  beforeEach(() => {
    listModelsMock.mockReset()
    listProvidersMock.mockReset()
    listProvidersMock.mockResolvedValue([
      { provider_id: 'prov-b', name: 'B 服务商' },
      { provider_id: 'ark', name: '火山方舟' },
    ])
    listModelsMock.mockResolvedValue([
      { model_id: 'flux.1', name: 'FLUX', provider: 'prov-b', capabilities: ['image_generation'], connectable: true },
      // 未配置服务商（connectable=false）→ 必须被过滤
      { model_id: 'gpt-image-1', name: 'GPT Image', provider: 'openai', capabilities: ['image_generation'], connectable: false },
      // 缺 connectable 字段（旧缓存）→ 不误伤
      { model_id: 'legacy-image', name: 'Legacy', provider: 'prov-b', capabilities: ['image_generation'] },
      { model_id: 'seedance-2', name: 'Seedance', provider: 'ark', capabilities: ['video_generation'], connectable: true },
      { model_id: 'text-only', name: 'Chat', provider: 'prov-b', capabilities: ['text'], connectable: true },
    ])
  })

  it('图像下拉只含可联通的 image_generation 模型，auto 置顶', async () => {
    const vm = await setupHost()
    const values = vm.imageModelOptions.map((o) => o.value)
    expect(values[0]).toBe('auto')
    expect(values).toContain('flux.1')
    expect(values).toContain('legacy-image')
    expect(values).not.toContain('gpt-image-1') // 未配置服务商被过滤
    expect(values).not.toContain('text-only')
    expect(values).not.toContain('seedance-2') // 视频能力不进图像下拉
  })

  it('选项携带 provider_id 且标签带服务商名', async () => {
    const vm = await setupHost()
    const flux = vm.imageModelOptions.find((o) => o.value === 'flux.1')
    expect(flux?.provider_id).toBe('prov-b')
    expect(flux?.label).toContain('B 服务商')
    expect(flux?.label).toContain('FLUX')
  })

  it('providerOf 反查服务商；auto/未知返回空串', async () => {
    const vm = await setupHost()
    expect(vm.providerOf('seedance-2')).toBe('ark')
    expect(vm.providerOf('auto')).toBe('')
    expect(vm.providerOf('ghost')).toBe('')
  })

  it('视频下拉只含 video_generation 模型', async () => {
    const vm = await setupHost()
    const values = vm.videoModelOptions.map((o) => o.value)
    expect(values).toEqual(['auto', 'seedance-2'])
  })

  it('文本下拉不做能力过滤（文本生成=调用 LLM，非能力标记）', async () => {
    listModelsMock.mockResolvedValue([
      // 无 capabilities 标记但可联通的聊天模型——旧口径会被 text 过滤误伤
      { model_id: 'glm-5', name: 'GLM', provider: 'prov-b', connectable: true },
      { model_id: 'reasoning-only', name: 'R1', provider: 'prov-b', capabilities: ['reasoning'], connectable: true },
      { model_id: 'text-only', name: 'Chat', provider: 'prov-b', capabilities: ['text'], connectable: true },
      { model_id: 'kimi-vision', name: 'K2', provider: 'prov-b', capabilities: ['vision'], connectable: true },
      // 未配置 → 仍被过滤（文本生成也要有凭据才能调通）
      { model_id: 'no-creds', name: 'NC', provider: 'x', capabilities: ['text'], connectable: false },
      // 纯生成模型不出现在文本下拉（用户拍板口径）
      { model_id: 'flux.1', name: 'FLUX', provider: 'prov-b', capabilities: ['image_generation'], connectable: true },
      { model_id: 'seedance-2', name: 'Seedance', provider: 'ark', capabilities: ['video_generation'], connectable: true },
    ])
    const vm = await setupHost()
    const values = vm.textModelOptions.map((o) => o.value)
    expect(values[0]).toBe('auto')
    expect(values.slice(1).sort()).toEqual(['glm-5', 'kimi-vision', 'reasoning-only', 'text-only'].sort())
    expect(values).not.toContain('no-creds')
    expect(values).not.toContain('flux.1')
    expect(values).not.toContain('seedance-2')
  })
})

/**
 * 能力感知模型下拉（自 AIGCPage 拆分，2026-09-14 页面重构 R1；
 * 2026-09-14 AIGC 能力过滤 R2）。
 *
 * 需求：图/视频页模型选择仅显示「已配置且可联通」且具备对应能力的模型
 * （图像页只出 image_generation、视频页只出 video_generation），并携带
 * provider_id 供页面上报。标签 `服务商 / 模型名` 与聊天页级联分组同源语义
 * （服务商优先、可联通优先），auto 固定置顶。
 * 文本生成两调用点（文本生成页/创作专区剧情创作）例外：**不做能力标记过滤**
 * （2026-09-14 用户拍板——chat 模型能力检测常缺 text 标记会误伤），仅排除
 * 纯图/视频生成模型并保留可联通过滤。
 *
 * 数据源 = GET /models（capabilities 后端自动检测并持久化；connectable 为
 * 服务商级连通判定 = provider enabled + key 配置 / 本地 / keyless 且非
 * unhealthy）。connectable 缺字段（旧缓存）按可联通处理（`!== false`），
 * 后端对未配置服务商显式回填 false 即被过滤——不误伤、不放过未配置项。
 *
 * providerOf(modelId) 取服务商 id 随请求下发（resolve_generation_creds
 * 优先按 provider_id 取凭据——Agnes 等未进 host 启发表的网关因此可用）。
 */
import { computed, onMounted, ref, type ComputedRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { listModels } from '@/api/modules/models'
import { listProviders } from '@/api/modules/providers'

export interface CapModel {
  id: string
  name: string
  provider: string
  capabilities: string[]
  connectable: boolean
}

/** a-select 选项（value=模型 id，provider_id 供选中时随请求上报） */
export interface AigcModelOption {
  label: string
  value: string
  provider_id: string
}

function normalizeCapModel(m: any): CapModel {
  return {
    id: m.model_id || m.id || m.name || 'unknown',
    name: m.name || m.model_id || m.id || 'Unknown',
    provider: m.provider || m.provider_id || '',
    capabilities: Array.isArray(m.capabilities) ? m.capabilities.map(String) : [],
    // 仅显式 false 才过滤（未配置服务商后端回填 false）；缺字段不误伤
    connectable: m.connectable !== false,
  }
}

export function useAigcModels() {
  const { t } = useI18n()
  const allCapModels = ref<CapModel[]>([])
  const providerNames = ref<Record<string, string>>({})

  /** 该能力下「已配置且可联通」的模型（按 provider+id 去重）。 */
  function modelsWithCap(cap: string): CapModel[] {
    const seen = new Set<string>()
    return allCapModels.value.filter((m) => {
      const key = `${m.provider}:${m.id}`
      if (!m.capabilities.includes(cap) || !m.connectable || seen.has(key)) return false
      seen.add(key)
      return true
    })
  }

  /**
   * 文本生成两调用点（文本生成页 + 创作专区剧情创作）下拉 = 所有可联通 LLM。
   * 不做 text 能力标记过滤——chat 模型的能力检测常缺 text 标记会误伤（2026-09-14
   * 用户拍板）；仅排除纯图/视频生成模型（文本调用必挂），保留可联通过滤（无凭据调不通）。
   */
  function textModels(): CapModel[] {
    const seen = new Set<string>()
    return allCapModels.value.filter((m) => {
      const key = `${m.provider}:${m.id}`
      if (m.capabilities.includes('image_generation') || m.capabilities.includes('video_generation')) return false
      if (!m.connectable || seen.has(key)) return false
      seen.add(key)
      return true
    })
  }

  /** 下拉选项组装：auto 置顶 + 模型列表（标签带服务商名）。 */
  function toOptions(models: CapModel[]): AigcModelOption[] {
    const auto: AigcModelOption = { label: t('ui.autoRoute'), value: 'auto', provider_id: '' }
    return [
      auto,
      ...models
        .sort(
          (a, b) =>
            `${a.provider}`.localeCompare(`${b.provider}`) || a.name.localeCompare(b.name),
        )
        .map((m) => ({
          label: `${providerNames.value[m.provider] || m.provider || '—'} / ${m.name || m.id}`,
          value: m.id,
          provider_id: m.provider,
        })),
    ]
  }

  /** 能力下拉选项：auto 置顶 + 已配置能力模型。 */
  function capOptions(cap: string): AigcModelOption[] {
    return toOptions(modelsWithCap(cap))
  }

  /** 选中模型 → 其服务商 id（供页面透传；auto/未知返回 ''）。 */
  function providerOf(modelId: string): string {
    if (!modelId || modelId === 'auto') return ''
    return allCapModels.value.find((m) => m.id === modelId)?.provider || ''
  }

  const textModelOptions = computed(() => toOptions(textModels())) as ComputedRef<AigcModelOption[]>
  const imageModelOptions = computed(() =>
    capOptions('image_generation'),
  ) as ComputedRef<AigcModelOption[]>
  const videoModelOptions = computed(() =>
    capOptions('video_generation'),
  ) as ComputedRef<AigcModelOption[]>

  async function loadModels() {
    try {
      const raw = (await listModels()) as any
      const data = raw?.data ?? raw
      const list = Array.isArray(data) ? data : (data?.models ?? data?.data ?? [])
      allCapModels.value = list.map(normalizeCapModel)
    } catch {
      /* 能力数据缺失时下拉保底 auto */
      allCapModels.value = []
    }
    try {
      const praw: any = await listProviders()
      const plist = (Array.isArray(praw) ? praw : praw?.data ?? praw?.providers ?? []) || []
      for (const p of plist as any[]) {
        if (p?.provider_id) providerNames.value[p.provider_id] = p.name || p.provider_id
      }
    } catch {
      /* 服务商名不可得时标签回落 provider id */
    }
  }

  onMounted(loadModels)

  return {
    allCapModels,
    loadModels,
    capOptions,
    providerOf,
    textModelOptions,
    imageModelOptions,
    videoModelOptions,
  }
}

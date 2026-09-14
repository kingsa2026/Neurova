/**
 * 能力感知模型下拉（自 AIGCPage 拆分，2026-09-14 页面重构 R1）。
 *
 * 数据源 = GET /models（capabilities 由后端自动检测并持久化），
 * 各页按 capability 过滤；首选项恒为 auto（LLMRouter 自动路由）。
 */
import { computed, onMounted, ref, type ComputedRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { listModels } from '@/api/modules/models'

export interface CapModel {
  id: string
  name: string
  provider: string
  capabilities: string[]
}

function normalizeCapModel(m: any): CapModel {
  return {
    id: m.model_id || m.id || m.name || 'unknown',
    name: m.name || m.model_id || m.id || 'Unknown',
    provider: m.provider || m.provider_id || '',
    capabilities: Array.isArray(m.capabilities) ? m.capabilities.map(String) : [],
  }
}

export function useAigcModels() {
  const { t } = useI18n()
  const allCapModels = ref<CapModel[]>([])

  function modelsWithCap(cap: string): CapModel[] {
    const seen = new Set<string>()
    return allCapModels.value.filter((m) => {
      if (!m.capabilities.includes(cap) || seen.has(m.id)) return false
      seen.add(m.id)
      return true
    })
  }

  function capOptions(cap: string) {
    return [
      { label: t('ui.autoRoute'), value: 'auto' },
      ...modelsWithCap(cap).map((m) => ({
        label: m.provider ? `${m.provider} / ${m.name}` : m.name,
        value: m.id,
      })),
    ]
  }

  const textModelOptions = computed(() => capOptions('text')) as ComputedRef<{ label: string; value: string }[]>
  const imageModelOptions = computed(() => capOptions('image_generation')) as ComputedRef<{ label: string; value: string }[]>
  const videoModelOptions = computed(() => capOptions('video_generation')) as ComputedRef<{ label: string; value: string }[]>

  async function loadModels() {
    try {
      const raw = (await listModels()) as any
      const data = raw?.data ?? raw
      const list = Array.isArray(data) ? data : (data?.models ?? data?.data ?? [])
      allCapModels.value = list.map(normalizeCapModel)
    } catch { /* 能力数据缺失时下拉保底 auto */ }
  }

  onMounted(loadModels)

  return { allCapModels, loadModels, capOptions, textModelOptions, imageModelOptions, videoModelOptions }
}

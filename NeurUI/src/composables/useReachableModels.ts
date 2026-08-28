import { ref } from 'vue'
import { listModels } from '@/api/modules/models'
import { normalizeModel, type ModelItem } from '@/types/model'

/** 模型下拉选项（label 携带 provider 便于区分同名模型） */
export interface ModelSelectOption {
  label: string
  value: string
  provider_id: string
}

/**
 * 构建模型下拉选项。
 *
 * @param models 模型列表
 * @param providerFilter 可选 provider 过滤（联动 model_provider 字段）
 *
 * 只保留 enabled 的模型——「可联通」的第一道过滤；
 * 联通性深度校验由 provider check-connection 惰性触发（见 verifyProvider）。
 */
export function buildModelOptions(
  models: ModelItem[],
  providerFilter?: string,
): ModelSelectOption[] {
  return models
    .filter((m) => m.enabled !== false)
    .filter((m) => !providerFilter || m.provider_id === providerFilter)
    .map((m) => ({
      label: `${m.name} (${m.provider_id}/${m.id})`,
      value: m.id,
      provider_id: m.provider_id,
    }))
}

/**
 * 可联通模型下拉（画布 builtin:llm 节点的 model-selector 数据源）。
 *
 * - load(): 拉 GET /models，兼容数组与 {models:[...]} 两种响应形状
 * - selectModel(): 选中模型时自动回填其 provider（与 model_provider 字段联动）
 * - 失败静默降级为空列表，不阻断画布编辑
 */
export function useReachableModels() {
  const models = ref<ModelItem[]>([])
  const loading = ref(false)
  const loaded = ref(false)
  const selectedProviderId = ref<string>('auto')

  async function load(): Promise<void> {
    if (loading.value) return
    loading.value = true
    try {
      const res = (await listModels()) as unknown as
        | { data?: ModelItem[] | { models?: ModelItem[] } }
        | ModelItem[]
        | { models?: ModelItem[] }
      const data = (res as { data?: unknown })?.data ?? res
      const list = Array.isArray(data)
        ? (data as unknown[])
        : Array.isArray((data as { models?: unknown[] })?.models)
          ? (data as { models: unknown[] }).models
          : []
      // 后端 GET /models 返回 {model_id, provider,...}，归一化为前端 ModelItem（含 id/provider_id）
      models.value = list.map((item) => normalizeModel(item as Record<string, any>))
      loaded.value = true
    } catch {
      // /models 不可用时降级为空列表（下拉显示"无可用模型"）
      models.value = []
    } finally {
      loading.value = false
    }
  }

  /** 选中模型 → 自动回填 provider（auto 除外） */
  function selectModel(model: ModelItem | null): void {
    selectedProviderId.value =
      model && model.provider_id ? model.provider_id : 'auto'
  }

  return { models, loading, loaded, selectedProviderId, load, selectModel }
}

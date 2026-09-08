import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import i18n from '@/i18n'
import { useAgentStore } from '@/stores/agents'
import { useAgentPage } from '@/composables/useAgentPage'
import { listModels } from '@/api/modules/models'
import { listProviders } from '@/api/modules/providers'
import { normalizeModel } from '@/types/model'
import { uiMessage } from '@/utils/message'

/**
 * 聊天页模型切换器状态机（2026-09-08 ChatPage 拆分产物）。
 *
 * 模块级单例：页面编排层（sendMessage body 携带 selectedModel、SSE
 * handleRateLimit）与 ChatComposerArea 工具条（级联菜单 UI）共享同一状态。
 * 所有逻辑原样迁自 ChatPage（不改写），首次调用须在组件 setup 内
 * （useI18n/useRouter 依赖注入上下文）。
 */

/** 聊天页可切换的模型选项（空串 = 自动路由） */
export interface ChatModelOption {
  label: string
  value: string
  provider_id: string
  context_window?: number | null
  /** 服务商级连通判定：绿点=真实可用，灰点=不可联通 */
  connectable?: boolean
}

export interface ChatModelGroup {
  provider_id: string
  provider_name: string
  models: ChatModelOption[]
}

const chatModelOptions = ref<ChatModelOption[]>([])
const chatModelGroups = ref<ChatModelGroup[]>([])
const selectedModel = ref<string>('')
const chatModelLoading = ref(false)
// 补课 A1：429 限流横幅——当前轮被限流的模型 + 一键切换候选列表
const rateLimitBanner = ref<{ model: string; alternatives: ChatModelOption[] } | null>(null)
// 补课 A2：无已启用模型提示（自动路由将无人可派）——引导去模型管理页
const noModelsHint = ref(false)
// 模型级联菜单开合与当前展开服务商
const modelMenuOpen = ref(false)
const activeProviderId = ref<string>('')

const selectedModelLabel = computed<string>(() => {
  const opt = chatModelOptions.value.find((o) => o.value === selectedModel.value)
  return opt ? opt.label : i18n.global.t('ui.autoRoute')
})

const currentModelContextWindow = computed<number | null>(() => {
  const opt = chatModelOptions.value.find((o) => o.value === selectedModel.value)
  return opt?.context_window ?? null
})

/** 当前展开服务商的模型列表（activeProviderId 为空时回退首个服务商）。 */
const activeGroupModels = computed<ChatModelOption[]>(() => {
  const groups = chatModelGroups.value
  if (groups.length === 0) return []
  const g = groups.find((x) => x.provider_id === activeProviderId.value) ?? groups[0]
  return g.models
})

/** 当前展开服务商名（子菜单标题）。 */
const activeProviderName = computed<string>(() => {
  const groups = chatModelGroups.value
  const g = groups.find((x) => x.provider_id === activeProviderId.value) ?? groups[0]
  return g ? g.provider_name : ''
})

function useI18nSafe() {
  try {
    return useI18n()
  } catch {
    return null
  }
}
void useI18nSafe

// 打开菜单时定位到当前选中模型所属服务商（自动路由则展开首个服务商）
let _menuWatchInstalled = false
function installMenuWatch() {
  if (_menuWatchInstalled) return
  _menuWatchInstalled = true
  watch(modelMenuOpen, (open) => {
    if (!open) return
    if (selectedModel.value) {
      const opt = chatModelOptions.value.find((o) => o.value === selectedModel.value)
      activeProviderId.value = opt?.provider_id || chatModelGroups.value[0]?.provider_id || ''
    } else {
      activeProviderId.value = chatModelGroups.value[0]?.provider_id || ''
    }
  })
}

async function loadChatModels() {
  const { t } = useI18n()
  chatModelLoading.value = true
  try {
    const [modelsRes, providersRes] = await Promise.all([listModels(), listProviders().catch(() => [])])
    const rawModels = Array.isArray(modelsRes) ? modelsRes : modelsRes?.models ?? []
    const normalized = rawModels.map((m) => normalizeModel(m))
    const providers = Array.isArray(providersRes) ? providersRes : (providersRes as any)?.data ?? []

    // 服务商元数据索引：id -> {name, is_active, api_key_configured, status, provider_type}
    const providerMeta = new Map<string, any>()
    for (const p of providers) {
      if (p?.provider_id) providerMeta.set(p.provider_id, p)
    }

    // 全量展示（可联通=绿点 / 不可联通=灰点），不再硬过滤——
    // 连通判定以后端 metadata.connectable 为单一事实源（服务商级）
    // 按服务商分组（保持服务商在 /providers 的返回顺序，组内按模型名）
    const groupMap = new Map<string, ChatModelGroup>()
    for (const m of normalized) {
      if (m.enabled === false) continue
      const pid = m.provider_id || ''
      if (!groupMap.has(pid)) {
        groupMap.set(pid, {
          provider_id: pid,
          provider_name: providerMeta.get(pid)?.name || pid,
          models: [],
        })
      }
      groupMap.get(pid)!.models.push({
        label: m.name || m.id,
        value: m.id || m.name,
        provider_id: pid,
        context_window: m.context_window ?? null,
        connectable: m.connectable ?? false,
      })
    }
    const groups = [...groupMap.values()]
    for (const g of groups) g.models.sort((a, b) => a.label.localeCompare(b.label))
    // 可联通的组在前，灰点组垫底
    groups.sort((a, b) => Number(b.models.some((m) => m.connectable)) - Number(a.models.some((m) => m.connectable)))
    chatModelGroups.value = groups

    // 扁平选项（429 候选 / 标签查找 / 上下文限额查询复用）
    const AUTO_ROUTE_LABEL = t('ui.autoRoute')
    const options: ChatModelOption[] = [
      { label: AUTO_ROUTE_LABEL, value: '', provider_id: '', context_window: null },
      ...groups.flatMap((g) => g.models),
    ]
    chatModelOptions.value = options
    // 补课 A2：零可联通模型 → 自动路由无候选可派，提示去模型管理页配置
    noModelsHint.value = !groups.some((g) => g.models.some((m) => m.connectable))
  } catch (e) {
    // 加载失败不阻塞聊天，保留"自动路由"选项即可
    console.warn('[useChatModels] failed to load model list:', e)
    chatModelOptions.value = []
    chatModelGroups.value = []
  } finally {
    chatModelLoading.value = false
  }
}

/**
 * 切换模型 = 修改该 agent 的默认模型（按 agent 隔离，等同编辑 agent）：
 * PUT /agents/{id} 持久化 model/provider 并重建运行时 llm_client。
 * 自动路由 → model='auto' 且清空 provider；具名模型 → 同时钉住其服务商。
 */
async function pickModel(value: string, providerId?: string): Promise<void> {
  const { t } = useI18n()
  const { agentId } = useAgentPage()
  const agentStore = useAgentStore()
  selectedModel.value = value
  modelMenuOpen.value = false
  if (!agentId.value) return
  const result = await agentStore.updateAgent(agentId.value, {
    model: value || 'auto',
    provider: providerId || '',
  })
  if (result) {
    uiMessage.success(t('chat.modelSavedToAgent'))
  } else {
    uiMessage.error(t('chat.modelSaveFailed'))
  }
}

function gotoModelsManage(): void {
  const router = useRouter()
  modelMenuOpen.value = false
  router.push('/models')
}

/**
 * 429 限流识别与横幅（补课 A1）：错误文本含 429/rate limit 措辞时，
 * 从已启用模型列表（排除当前选中）生成备选候选，弹出横幅一键切换。
 * 非限流错误返回 false 走原有错误路径。
 */
function handleRateLimit(err: any): boolean {
  const msg = String(err?.message || '')
  if (!/429|rate.?limit|too many requests|限流|请求过于频繁/i.test(msg)) return false
  const current = selectedModel.value || ''
  const alternatives = chatModelOptions.value.filter((o) => o.value && o.value !== current)
  rateLimitBanner.value = { model: current, alternatives }
  return true
}

/** 横幅一键切换：选定备选模型后关闭横幅（用户重发即走新模型）。 */
function switchAfterRateLimit(modelValue: string): void {
  const { t } = useI18n()
  selectedModel.value = modelValue
  rateLimitBanner.value = null
  uiMessage.success(t('chat.rateLimitSwitched'))
}

export function useChatModels() {
  installMenuWatch()
  return {
    chatModelOptions,
    chatModelGroups,
    selectedModel,
    chatModelLoading,
    rateLimitBanner,
    noModelsHint,
    modelMenuOpen,
    activeProviderId,
    selectedModelLabel,
    currentModelContextWindow,
    activeGroupModels,
    activeProviderName,
    loadChatModels,
    pickModel,
    gotoModelsManage,
    handleRateLimit,
    switchAfterRateLimit,
  }
}

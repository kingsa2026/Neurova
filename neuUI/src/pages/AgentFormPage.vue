<template>
  <div class="agent-form-page">
    <div class="page-header glass-effect">
      <h2 class="page-title">{{ isEdit ? '编辑 Agent' : '创建 Agent' }}</h2>
      <a-button @click="$router.back()">返回</a-button>
    </div>

    <div class="form-body glass-effect">
      <a-form :model="form" layout="vertical" class="settings-form">
        <a-row :gutter="24">
          <a-col :span="12">
            <a-form-item label="Agent ID" required extra="英文+数字+下划线，创建后不可修改">
              <a-input v-model:value="form.agentId" :disabled="isEdit" placeholder="如 my_agent_01" />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="名称" required extra="不可与已有 Agent 重复">
              <a-input v-model:value="form.name" placeholder="Agent 显示名称" />
            </a-form-item>
          </a-col>
        </a-row>

        <a-form-item label="描述">
          <a-textarea v-model:value="form.description" :rows="3" placeholder="描述 Agent 的功能和用途" />
        </a-form-item>

        <a-row :gutter="24">
          <a-col :span="24">
            <a-form-item label="LLM 模式">
              <a-switch v-model:checked="routeAuto" checked-children="自动路由" un-checked-children="指定服务商" @change="onAutoChange" />
              <span style="margin-left:10px;font-size:.78rem;color:rgba(255,255,255,0.35)">
                {{ routeAuto ? '跨所有已联通服务商，按多模态能力自动匹配模型' : '手动指定服务商及其下的模型' }}
              </span>
            </a-form-item>
            <template v-if="!routeAuto">
              <a-form-item label="服务商" extra="仅显示已联通（已配置 API Key）的服务商">
                <a-select v-model:value="selectedProvider" placeholder="选择服务商" :options="providerOpts" :loading="providerLoading" show-search @change="onProviderChange" style="width:100%" />
              </a-form-item>
              <a-form-item label="模型" extra="该服务商下的可用模型">
                <a-select v-model:value="form.llmModel" @change="(val: string) => console.log('[AgentForm] 模型选择变更:', val)" placeholder="选择模型" :options="modelOptions" :loading="modelLoading" show-search :disabled="!selectedProvider" style="width:100%" />
              </a-form-item>
            </template>
          </a-col>
          <a-col :span="12">
            <a-form-item label="工作目录">
              <a-input v-model:value="form.workingDirectory" :disabled="isEdit" placeholder="工作目录路径" />
            </a-form-item>
          </a-col>
        </a-row>

        <a-divider orientation="left">个性与准则</a-divider>

        <a-form-item label="个性设定">
          <a-textarea v-model:value="form.personality" :rows="3" placeholder="例如：友善、专业、幽默..." />
        </a-form-item>

        <a-form-item label="行为准则（宪法）">
          <a-textarea v-model:value="form.constitution" :rows="4" placeholder="定义 Agent 的核心行为准则..." />
        </a-form-item>

        <a-divider orientation="left">TTS 配置</a-divider>

        <a-row :gutter="24">
          <a-col :span="6">
            <a-form-item label="启用 TTS">
              <a-switch v-model:checked="form.ttsEnabled" />
            </a-form-item>
          </a-col>
          <a-col :span="6">
            <a-form-item label="语音类型">
              <a-select v-model:value="form.ttsVoice" :disabled="!form.ttsEnabled" :options="voiceOptions" />
            </a-form-item>
          </a-col>
          <a-col :span="6">
            <a-form-item label="语速">
              <a-slider v-model:value="form.ttsSpeed" :min="0.5" :max="2" :step="0.1" :disabled="!form.ttsEnabled" />
            </a-form-item>
          </a-col>
          <a-col :span="6">
            <a-form-item label="音调">
              <a-slider v-model:value="form.ttsPitch" :min="0.5" :max="2" :step="0.1" :disabled="!form.ttsEnabled" />
            </a-form-item>
          </a-col>
        </a-row>

        <a-divider orientation="left">对话显示设置</a-divider>
        <a-row :gutter="24">
          <a-col :span="12">
            <a-form-item label="显示思考过程" extra="展示 Agent 内部推理链（如 DeepSeek-R1）">
              <a-switch v-model:checked="form.showThinking" />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="显示工具消息" extra="展示工具调用过程和结果">
              <a-switch v-model:checked="form.showToolMessages" />
            </a-form-item>
          </a-col>
        </a-row>

        <a-divider orientation="left">记忆共享组</a-divider>
        <div class="share-group-section">
          <p class="section-description">
            将此 Agent 添加到共享组，与其他 Agent 共享记忆。同一共享组内的 Agent 可以访问彼此的记忆。
          </p>
          
          <!-- 已加入的共享组 -->
          <div v-if="agentGroups.length > 0" class="agent-groups">
            <h4>已加入的共享组</h4>
            <div v-for="group in agentGroups" :key="group.group_id" class="group-card">
              <div class="group-info">
                <span class="group-name">{{ group.name }}</span>
                <span class="group-desc">{{ group.description || '无描述' }}</span>
                <span class="group-agents">{{ group.agent_ids.length }} 个 Agent</span>
              </div>
              <a-button 
                type="link" 
                danger 
                size="small"
                @click="handleRemoveFromGroup(group.group_id)"
                :loading="removingGroupId === group.group_id"
              >
                退出
              </a-button>
            </div>
          </div>
          
          <div v-else class="no-groups">
            <a-empty description="暂未加入任何共享组" :image-style="{ height: '60px' }">
              <template #image>
                <span style="font-size: 2rem; opacity: 0.3;">🔗</span>
              </template>
            </a-empty>
          </div>
          
          <!-- 创建新共享组 -->
          <a-divider dashed>或创建新共享组</a-divider>
          
          <a-form layout="vertical" class="create-group-form">
            <a-row :gutter="16">
              <a-col :span="12">
                <a-form-item label="组名称" required>
                  <a-input v-model:value="newGroup.name" placeholder="如：项目组A" />
                </a-form-item>
              </a-col>
              <a-col :span="12">
                <a-form-item label="描述">
                  <a-input v-model:value="newGroup.description" placeholder="共享组用途说明" />
                </a-form-item>
              </a-col>
            </a-row>
            
            <a-form-item label="选择要共享记忆的 Agent">
              <a-select
                v-model:value="newGroup.agentIds"
                mode="multiple"
                placeholder="选择 Agent（当前 Agent 会自动加入）"
                :options="agentOptions"
                :loading="agentsLoading"
                show-search
                :filter-option="filterAgentOption"
                style="width: 100%"
              />
            </a-form-item>
            
            <a-button 
              type="primary" 
              @click="handleCreateGroup"
              :loading="creatingGroup"
              :disabled="!newGroup.name || newGroup.agentIds.length === 0"
            >
              创建共享组
            </a-button>
          </a-form>
        </div>

        <a-divider />
        <a-space>
          <a-button type="primary" size="large" :loading="saving" @click="handleSave">保存</a-button>
          <a-button size="large" @click="$router.back()">取消</a-button>
        </a-space>
      </a-form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, watch, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { useAgentStore } from '@/stores/agents'
import { providerAPI } from '@/api/modules/providers'
import { memoryShareGroupsAPI, type ShareGroup } from '@/api/modules/memory-share-groups'
import type { Agent } from '@/types/agent'

const route = useRoute()
const router = useRouter()
const agentStore = useAgentStore()

const isEdit = computed(() => !!route.params.id)
const saving = ref(false)

const form = reactive({
  agentId: '',
  name: '',
  description: '',
  llmModel: 'auto',
  workingDirectory: '',
  personality: '',
  constitution: '',
  ttsEnabled: false,
  ttsVoice: 'female',
  ttsSpeed: 1,
  ttsPitch: 1,
  showThinking: true,
  showToolMessages: true,
})

// 已联通服务商列表（仅 has_api_key + enabled）
interface ConnectedProvider { id:string;name:string;models?:Array<string|{name?:string;model?:string}> }
const connectedProviders = ref<ConnectedProvider[]>([])
const selectedProvider = ref('')
const routeAuto = ref(true)
const providerOpts = ref<{ label: string; value: string }[]>([])
const providerLoading = ref(false)

const modelOptions = ref<{ label: string; value: string }[]>([])
const modelLoading = ref(false)

const voiceOptions = [
  { label: '女声', value: 'female' },
  { label: '男声', value: 'male' },
  { label: '自定义', value: 'custom' },
]

// 共享组相关
const agentGroups = ref<ShareGroup[]>([])
const agentsLoading = ref(false)
const agentOptions = ref<{ label: string; value: string }[]>([])
const creatingGroup = ref(false)
const removingGroupId = ref<string | null>(null)

const newGroup = reactive({
  name: '',
  description: '',
  agentIds: [] as string[],
})

// 共享组相关函数
function filterAgentOption(input: string, option: { label: string; value: string }) {
  return option.label.toLowerCase().includes(input.toLowerCase())
}

async function loadAgentGroups() {
  if (!form.agentId) return
  
  try {
    const res = await memoryShareGroupsAPI.getGroupsForAgent(form.agentId)
    agentGroups.value = res.groups || []
  } catch (e) {
    console.error('[AgentForm] 加载共享组失败:', e)
    agentGroups.value = []
  }
}

async function loadAllAgents() {
  agentsLoading.value = true
  try {
    await agentStore.loadAgents()
    // 排除当前 Agent
    agentOptions.value = agentStore.agents
      .filter(a => (a.agentId || a.id) !== form.agentId)
      .map(a => ({
        label: `${a.name} (${a.agentId || a.id})`,
        value: a.agentId || a.id || '',
      }))
  } catch (e) {
    console.error('[AgentForm] 加载 Agent 列表失败:', e)
  } finally {
    agentsLoading.value = false
  }
}

async function handleCreateGroup() {
  if (!newGroup.name || newGroup.agentIds.length === 0) {
    message.warning('请填写组名称并选择至少一个 Agent')
    return
  }
  
  creatingGroup.value = true
  try {
    // 确保当前 Agent 在组中
    const agentIds = [...new Set([form.agentId, ...newGroup.agentIds])]
    
    await memoryShareGroupsAPI.create({
      name: newGroup.name,
      description: newGroup.description,
      agent_ids: agentIds,
    })
    
    message.success('共享组创建成功')
    
    // 重置表单
    newGroup.name = ''
    newGroup.description = ''
    newGroup.agentIds = []
    
    // 重新加载
    await loadAgentGroups()
  } catch (e) {
    console.error('[AgentForm] 创建共享组失败:', e)
    message.error('创建共享组失败')
  } finally {
    creatingGroup.value = false
  }
}

async function handleRemoveFromGroup(groupId: string) {
  removingGroupId.value = groupId
  try {
    await memoryShareGroupsAPI.removeAgent(groupId, form.agentId)
    message.success('已退出共享组')
    await loadAgentGroups()
  } catch (e) {
    console.error('[AgentForm] 退出共享组失败:', e)
    message.error('退出共享组失败')
  } finally {
    removingGroupId.value = null
  }
}

function onAutoChange(checked: boolean) {
  if (checked) {
    form.llmModel = 'auto'
    selectedProvider.value = ''
    modelOptions.value = []
  } else {
    form.llmModel = ''
    selectedProvider.value = ''
    modelOptions.value = []
  }
}

async function onProviderChange(pid: string) {
  form.llmModel = ''; modelOptions.value = []
  if (!pid) return
  modelLoading.value = true
  try {
    // 从服务端获取该服务商的模型列表
    const res = await providerAPI.get(pid)
    // 响应拦截器已解包 response.data
    // res 结构：{ success, code, data: { id, models, ... } }
    // 所以 res.data = { id, models, ... }
    console.log('[AgentForm] provider get response:', res)
    const p = res?.data || {}
    console.log('[AgentForm] provider data:', p)
    if (p?.models?.length) {
      p.models.forEach((m: string | { name?: string; model?: string }) => {
        const name = typeof m === 'string' ? m : (m.name || m.model || m)
        if (name) modelOptions.value.push({ label: name, value: name })
      })
      console.log('[AgentForm] modelOptions:', modelOptions.value)
    }
  } catch (e) {
    console.error('[AgentForm] load models error:', e)
    // 降级：从本地 connectedProviders 查找
    const p = connectedProviders.value.find(x => x.id === pid)
    if (p?.models?.length) {
      p.models.forEach((m: string | { name?: string; model?: string }) => {
        const name = typeof m === 'string' ? m : (m.name || m.model || m)
        if (name) modelOptions.value.push({ label: name, value: name })
      })
    }
  } finally {
    modelLoading.value = false
  }
}

async function handleSave() {
  if (!form.agentId || !form.name) { message.warning('请填写必填项'); return }
  
  // 验证：关闭自动路由时，必须选择服务商和模型
  if (!routeAuto.value) {
    if (!selectedProvider.value) {
      message.warning('请先选择服务商')
      return
    }
    if (!form.llmModel) {
      message.warning('请先选择模型')
      return
    }
  }
  
  saving.value = true
  try {
    const data: Record<string, unknown> = {
      agent_id: form.agentId,
      name: form.name,
      description: form.description,
      llm_model: form.llmModel,
      workspace_path: form.workingDirectory || undefined,
      // 注意：用 ?? 而不是 ||，确保空字符串能被正确传递
      personality: form.personality ?? '',
      constitution: form.constitution ?? '',
      enable_memory: true,
      // TTS 配置
      tts_enabled: form.ttsEnabled,
      tts_voice: form.ttsVoice,
      tts_speed: form.ttsSpeed,
      tts_pitch: form.ttsPitch,
      // 对话显示配置
      show_thinking: form.showThinking,
      show_tool_messages: form.showToolMessages,
    }
    // 传递 llm_provider（关闭自动路由 + 已选服务商时）
    if (!routeAuto.value && selectedProvider.value && form.llmModel) {
      data.llm_provider = selectedProvider.value
    }
    
    console.log('[AgentForm] 保存数据:', JSON.stringify(data, null, 2))
    console.log('[AgentForm] routeAuto:', routeAuto.value)
    console.log('[AgentForm] selectedProvider:', selectedProvider.value)
    console.log('[AgentForm] form.llmModel:', form.llmModel)
    console.log('[AgentForm] TTS配置:', {
      enabled: form.ttsEnabled,
      voice: form.ttsVoice,
      speed: form.ttsSpeed,
      pitch: form.ttsPitch
    })
    
    // 特别检查 llm_model 是否在数据中
    console.log('[AgentForm] 检查 llm_model 字段:', {
      'data.llm_model': data.llm_model,
      'typeof': typeof data.llm_model,
      'form.llmModel': form.llmModel
    })
    if (isEdit.value) {
      const ok = await agentStore.updateAgent(route.params.id as string, data)
      if (!ok) {
        message.error(agentStore.error || '更新失败')
        return
      }
    } else {
      const created = await agentStore.createAgent(data)
      if (!created) {
        message.error(agentStore.error || '创建失败')
        return
      }
    }
    message.success(isEdit.value ? '更新成功' : '创建成功')
    router.push('/agents')
  } catch (e: unknown) {
    const err = e as { response?: { data?: { message?: string } } }
    message.error(err?.response?.data?.message || '操作失败')
  } finally { saving.value = false }
}

onMounted(async () => {
  console.log('[AgentForm] ========== onMounted 开始 ==========')
  
  // 加载已联通服务商（仅 has_api_key + enabled）
  providerLoading.value = true
  try {
    console.log('[AgentForm] 开始调用 providerAPI.list()...')
    const res = await providerAPI.list()
    // 响应拦截器返回 response.data
    // res 的完整结构：{ success, code, data: { providers, count, ... } }
    // 所以服务商列表在 res.data.providers
    console.log('[AgentForm] API 响应 (res):', res)
    console.log('[AgentForm] res.data:', res?.data)
    console.log('[AgentForm] res.data?.providers:', res?.data?.providers)
    
    const providers = (res?.data?.providers || []) as Array<{ id: string; name: string; has_api_key?: boolean; enabled?: boolean; models?: Array<string | { name?: string; model?: string }> }>
    console.log('[AgentForm] providers 数量:', providers.length)
    
    const connected = providers.filter(p => p.has_api_key && p.enabled !== false)
    console.log('[AgentForm] 已配置服务商 (has_api_key=true):', connected)
    console.log('[AgentForm] 已配置服务商数量:', connected.length)
    
    if (connected.length) {
      connectedProviders.value = connected
      providerOpts.value = connected.map(p => ({
        label: `${p.name} (${p.models?.length || 0}个模型)`,
        value: p.id,
      }))
      console.log('[AgentForm] providerOpts:', providerOpts.value)
      console.log('[AgentForm] providerOpts 长度:', providerOpts.value.length)
    } else {
      console.warn('[AgentForm] 未找到已配置的服务商！')
    }
  } catch (e) { 
    console.error('[AgentForm] 加载服务商失败:', e) 
  }
  finally { 
    providerLoading.value = false 
    console.log('[AgentForm] ========== onMounted 结束 ==========')
  }

  // 新建：默认自动路由
  if (!isEdit.value) {
    routeAuto.value = true
    form.llmModel = 'auto'
  }

  // 编辑模式：加载配置（提取成函数，供 onMounted 和 watch 调用）
  async function loadConfig() {
    if (!isEdit.value) return
    console.log('[AgentForm] 进入编辑模式，准备加载配置...', 'route.params:', route.params)
    const config = await agentStore.getAgentConfig(route.params.id as string)
    if (config) {
      console.log('[AgentForm] 从完整配置加载:', config)
      form.agentId = config.agentId || route.params.id as string
      form.name = config.name || ''
      form.description = config.description || ''
      // 注意：llmModel 暂存，等 modelOptions 加载完成后再赋值
      const tempLlmModel = config.llmModel || 'auto'
      form.workingDirectory = config.workspacePath || ''
      form.personality = config.personality || ''
      form.constitution = config.constitution || ''
      // TTS 配置加载
      form.ttsEnabled = config.ttsEnabled !== undefined ? config.ttsEnabled : false
      form.ttsVoice = config.ttsVoice || 'female'
      form.ttsSpeed = config.ttsSpeed || 1.0
      form.ttsPitch = config.ttsPitch || 1.0
      
      console.log('[AgentForm] 加载TTS配置:', {
        enabled: form.ttsEnabled,
        voice: form.ttsVoice,
        speed: form.ttsSpeed,
        pitch: form.ttsPitch
      })
      
      // 编辑模式：还原路由模式（优先用 llmProvider 直接匹配）
      const savedProvider = config.llmProvider || ''
      if (tempLlmModel === 'auto') {
        routeAuto.value = true
        form.llmModel = 'auto'
      } else if (savedProvider && connectedProviders.value.some(p => p.id === savedProvider)) {
        routeAuto.value = false
        selectedProvider.value = savedProvider
        // 关键：await 等待模型列表加载完成
        await onProviderChange(savedProvider)
        // 确保模型在列表中
        if (!modelOptions.value.find(m => m.value === tempLlmModel)) {
          modelOptions.value.push({ label: tempLlmModel, value: tempLlmModel })
        }
        // 现在再赋值，下拉框能正确匹配
        form.llmModel = tempLlmModel
        console.log('[AgentForm] 模型ID已赋值:', form.llmModel)
      } else {
        // 反查模型所属服务商
        for (const p of connectedProviders.value) {
          const found = (p.models || []).some((m: string | { name?: string; model?: string }) => (typeof m === 'string' ? m : m.name) === tempLlmModel)
          if (found) {
            routeAuto.value = false
            selectedProvider.value = p.id
            // 关键：await 等待模型列表加载完成
            await onProviderChange(p.id)
            // 确保模型在列表中
            if (!modelOptions.value.find(m => m.value === tempLlmModel)) {
              modelOptions.value.push({ label: tempLlmModel, value: tempLlmModel })
            }
            // 现在再赋值
            form.llmModel = tempLlmModel
            console.log('[AgentForm] 模型ID已赋值(反查):', form.llmModel)
            break
          }
        }
        if (!selectedProvider.value) {
          routeAuto.value = true
          form.llmModel = 'auto'
        }
      }
    } else {
      // 降级：从列表加载
      await agentStore.loadAgents()
      const agent = agentStore.agents.find(a => (a.agentId || a.id) === route.params.id) as Record<string,unknown> | undefined
      if (agent) {
        form.agentId = (agent.agentId || agent.id) as string || ''
        form.name = (agent.name as string) || ''
        form.description = (agent.description as string) || ''
        form.llmModel = (agent.llmModel as string) || 'auto'
        form.workingDirectory = (agent.workingDirectory as string) || ''
      }
    }
    
    // 加载共享组和 Agent 列表
    await Promise.all([
      loadAgentGroups(),
      loadAllAgents(),
    ])
  }

  // 初次加载
  await loadConfig()
  
  // 监听路由参数变化（处理同组件不同 ID 的切换）
  watch(() => route.params.id, async () => {
    console.log('[AgentForm] route.params.id 变化:', route.params.id)
    // 重置表单
    form.agentId = ''
    form.name = ''
    form.description = ''
    form.llmModel = 'auto'
    form.workingDirectory = ''
    form.personality = ''
    form.constitution = ''
    form.ttsEnabled = false
    form.ttsVoice = 'female'
    form.ttsSpeed = 1.0
    form.ttsPitch = 1.0
    selectedProvider.value = ''
    modelOptions.value = []
    routeAuto.value = !isEdit.value
    
    // 重置共享组数据
    agentGroups.value = []
    agentOptions.value = []
    newGroup.name = ''
    newGroup.description = ''
    newGroup.agentIds = []
    
    // 重新加载配置
    await loadConfig()
  })
})
</script>

<style scoped>
.agent-form-page { display:flex;flex-direction:column;gap:16px;max-width:860px; }
.page-header { display:flex;justify-content:space-between;align-items:center;padding:20px 24px;border-radius:12px; }
.page-title { font-size:1.25rem;color:#e2e8f0;margin:0; }
.form-body { padding:28px;border-radius:12px; }
:deep(.settings-form .ant-form-item-label>label){ color:rgba(255,255,255,0.6)!important; }
:deep(.settings-form .ant-input),:deep(.settings-form .ant-input-affix-wrapper),:deep(.settings-form textarea.ant-input){ background:rgba(255,255,255,0.05)!important;border:1px solid rgba(255,255,255,0.1)!important;color:#e2e8f0!important; }
:deep(.ant-divider-inner-text){ color:rgba(255,255,255,0.4)!important;font-size:0.85rem; }

.share-group-section { background:rgba(255,255,255,0.03);border-radius:8px;padding:20px;border:1px solid rgba(255,255,255,0.08); }
.section-description { color:rgba(255,255,255,0.5);font-size:0.85rem;margin-bottom:16px; }
.agent-groups { margin-bottom:20px; }
.agent-groups h4 { color:rgba(255,255,255,0.7);font-size:0.9rem;margin-bottom:12px; }
.group-card { display:flex;justify-content:space-between;align-items:center;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:8px;padding:12px 16px;margin-bottom:8px; }
.group-info { display:flex;flex-direction:column;gap:4px; }
.group-name { color:#e2e8f0;font-weight:500; }
.group-desc { color:rgba(255,255,255,0.4);font-size:0.8rem; }
.group-agents { color:rgba(255,255,255,0.5);font-size:0.75rem; }
.no-groups { margin-bottom:20px; }
.create-group-form { margin-top:16px; }
:deep(.create-group-form .ant-form-item-label>label){ color:rgba(255,255,255,0.6)!important; }
:deep(.create-group-form .ant-input){ background:rgba(255,255,255,0.05)!important;border:1px solid rgba(255,255,255,0.1)!important;color:#e2e8f0!important; }
:deep(.create-group-form .ant-select-selector){ background:rgba(255,255,255,0.05)!important;border:1px solid rgba(255,255,255,0.1)!important; }
</style>

&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h2 &gt;{{ isEdit ? '编辑 Agent' : '创建 Agent' }}&lt;/h2&gt;
      &lt;a-button @click="$router.back()"&gt;返回&lt;/a-button&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;a-form :model="form" layout="vertical" &gt;
        &lt;a-row :gutter="24"&gt;
          &lt;a-col :span="12"&gt;
            &lt;a-form-item label="Agent ID" required extra="英文+数字+下划线，创建后不可修改"&gt;
              &lt;a-input v-model:value="form.agentId" :disabled="isEdit" placeholder="如 my_agent_01" /&gt;
            &lt;/a-form-item&gt;
          &lt;/a-col&gt;
          &lt;a-col :span="12"&gt;
            &lt;a-form-item label="名称" required extra="不可与已有 Agent 重复"&gt;
              &lt;a-input v-model:value="form.name" placeholder="Agent 显示名称" /&gt;
            &lt;/a-form-item&gt;
          &lt;/a-col&gt;
        &lt;/a-row&gt;
        &lt;a-form-item label="描述"&gt;
          &lt;a-textarea v-model:value="form.description" :rows="3" placeholder="描述 Agent 的功能和用途" /&gt;
        &lt;/a-form-item&gt;
        &lt;a-row :gutter="24"&gt;
          &lt;a-col :span="24"&gt;
            &lt;a-form-item label="LLM 模式"&gt;
              &lt;a-switch v-model:checked="routeAuto" checked-children="自动路由" un-checked-children="指定服务商" @change="onAutoChange" /&gt;
              &lt;span style="margin-left:10px;font-size:.78rem;color:rgba(255,255,255,0.35)"&gt;
                {{ routeAuto ? '跨所有已联通服务商，按多模态能力自动匹配模型' : '手动指定服务商及其下的模型' }}
              &lt;/span&gt;
            &lt;/a-form-item&gt;
            &lt;template v-if="!routeAuto"&gt;
              &lt;a-form-item label="服务商" extra="仅显示已联通（已配置 API Key）的服务商"&gt;
                &lt;a-select v-model:value="selectedProvider" placeholder="选择服务商" :options="providerOpts" :loading="providerLoading" show-search @change="onProviderChange" style="width:100%" /&gt;
              &lt;/a-form-item&gt;
              &lt;a-form-item label="模型" extra="该服务商下的可用模型"&gt;
                &lt;a-select v-model:value="form.llmModel" @change="(val: string) =&gt; console.log('[AgentForm] 模型选择变更:', val)" placeholder="选择模型" :options="modelOptions" :loading="modelLoading" show-search :disabled="!selectedProvider" style="width:100%" /&gt;
              &lt;/a-form-item&gt;
            &lt;/template&gt;
          &lt;/a-col&gt;
          &lt;a-col :span="12"&gt;
            &lt;a-form-item label="工作目录"&gt;
              &lt;a-input v-model:value="form.workingDirectory" :disabled="isEdit" placeholder="工作目录路径" /&gt;
            &lt;/a-form-item&gt;
          &lt;/a-col&gt;
        &lt;/a-row&gt;
        &lt;a-divider orientation="left"&gt;个性与准则&lt;/a-divider&gt;
        &lt;a-form-item label="个性设定"&gt;
          &lt;a-textarea v-model:value="form.personality" :rows="3" placeholder="例如：友善、专业、幽默..." /&gt;
        &lt;/a-form-item&gt;
        &lt;a-form-item label="行为准则（宪法）"&gt;
          &lt;a-textarea v-model:value="form.constitution" :rows="4" placeholder="定义 Agent 的核心行为准则..." /&gt;
        &lt;/a-form-item&gt;
        &lt;a-divider orientation="left"&gt;TTS 配置&lt;/a-divider&gt;
        &lt;a-row :gutter="24"&gt;
          &lt;a-col :span="6"&gt;
            &lt;a-form-item label="启用 TTS"&gt;
              &lt;a-switch v-model:checked="form.ttsEnabled" /&gt;
            &lt;/a-form-item&gt;
          &lt;/a-col&gt;
          &lt;a-col :span="6"&gt;
            &lt;a-form-item label="语音类型"&gt;
              &lt;a-select v-model:value="form.ttsVoice" :disabled="!form.ttsEnabled" :options="voiceOptions" /&gt;
            &lt;/a-form-item&gt;
          &lt;/a-col&gt;
          &lt;a-col :span="6"&gt;
            &lt;a-form-item label="语速"&gt;
              &lt;a-slider v-model:value="form.ttsSpeed" :min="0.5" :max="2" :step="0.1" :disabled="!form.ttsEnabled" /&gt;
            &lt;/a-form-item&gt;
          &lt;/a-col&gt;
          &lt;a-col :span="6"&gt;
            &lt;a-form-item label="音调"&gt;
              &lt;a-slider v-model:value="form.ttsPitch" :min="0.5" :max="2" :step="0.1" :disabled="!form.ttsEnabled" /&gt;
            &lt;/a-form-item&gt;
          &lt;/a-col&gt;
        &lt;/a-row&gt;
        &lt;a-divider orientation="left"&gt;对话显示设置&lt;/a-divider&gt;
        &lt;a-row :gutter="24"&gt;
          &lt;a-col :span="12"&gt;
            &lt;a-form-item label="显示思考过程" extra="展示 Agent 内部推理链（如 DeepSeek-R1）"&gt;
              &lt;a-switch v-model:checked="form.showThinking" /&gt;
            &lt;/a-form-item&gt;
          &lt;/a-col&gt;
          &lt;a-col :span="12"&gt;
            &lt;a-form-item label="显示工具消息" extra="展示工具调用过程和结果"&gt;
              &lt;a-switch v-model:checked="form.showToolMessages" /&gt;
            &lt;/a-form-item&gt;
          &lt;/a-col&gt;
        &lt;/a-row&gt;
        &lt;a-divider /&gt;
        &lt;a-space&gt;
          &lt;a-button type="primary" size="large" :loading="saving" @click="handleSave"&gt;保存&lt;/a-button&gt;
          &lt;a-button size="large" @click="$router.back()"&gt;取消&lt;/a-button&gt;
        &lt;/a-space&gt;
      &lt;/a-form&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref, reactive, watch, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { useAgentStore } from '@/stores/agents'
import { providerAPI } from '@/api/modules/providers'
import type { Agent } from '@/types/agent'
const route = useRoute()
const router = useRouter()
const agentStore = useAgentStore()
const isEdit = computed(() =&gt; !!route.params.id)
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
interface ConnectedProvider { id:string;name:string;models?:Array&lt;string|{name?:string;model?:string}&gt; }
const connectedProviders = ref&lt;ConnectedProvider[]&gt;([])
const selectedProvider = ref('')
const routeAuto = ref(true)
const providerOpts = ref&lt;{ label: string; value: string }[]&gt;([])
const providerLoading = ref(false)
const modelOptions = ref&lt;{ label: string; value: string }[]&gt;([])
const modelLoading = ref(false)
const voiceOptions = [
  { label: '女声', value: 'female' },
  { label: '男声', value: 'male' },
  { label: '自定义', value: 'custom' },
]
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
      p.models.forEach((m: string | { name?: string; model?: string }) =&gt; {
        const name = typeof m === 'string' ? m : (m.name || m.model || m)
        if (name) modelOptions.value.push({ label: name, value: name })
      })
      console.log('[AgentForm] modelOptions:', modelOptions.value)
    }
  } catch (e) {
    console.error('[AgentForm] load models error:', e)
    // 降级：从本地 connectedProviders 查找
    const p = connectedProviders.value.find(x =&gt; x.id === pid)
    if (p?.models?.length) {
      p.models.forEach((m: string | { name?: string; model?: string }) =&gt; {
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
    const data: Record&lt;string, unknown&gt; = {
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
    if (!routeAuto.value &amp;&amp; selectedProvider.value &amp;&amp; form.llmModel) {
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
onMounted(async () =&gt; {
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
    const providers = (res?.data?.providers || []) as Array&lt;{ id: string; name: string; has_api_key?: boolean; enabled?: boolean; models?: Array&lt;string | { name?: string; model?: string }&gt; }&gt;
    console.log('[AgentForm] providers 数量:', providers.length)
    const connected = providers.filter(p =&gt; p.has_api_key &amp;&amp; p.enabled !== false)
    console.log('[AgentForm] 已配置服务商 (has_api_key=true):', connected)
    console.log('[AgentForm] 已配置服务商数量:', connected.length)
    if (connected.length) {
      connectedProviders.value = connected
      providerOpts.value = connected.map(p =&gt; ({
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
      } else if (savedProvider &amp;&amp; connectedProviders.value.some(p =&gt; p.id === savedProvider)) {
        routeAuto.value = false
        selectedProvider.value = savedProvider
        // 关键：await 等待模型列表加载完成
        await onProviderChange(savedProvider)
        // 确保模型在列表中
        if (!modelOptions.value.find(m =&gt; m.value === tempLlmModel)) {
          modelOptions.value.push({ label: tempLlmModel, value: tempLlmModel })
        }
        // 现在再赋值，下拉框能正确匹配
        form.llmModel = tempLlmModel
        console.log('[AgentForm] 模型ID已赋值:', form.llmModel)
      } else {
        // 反查模型所属服务商
        for (const p of connectedProviders.value) {
          const found = (p.models || []).some((m: string | { name?: string; model?: string }) =&gt; (typeof m === 'string' ? m : m.name) === tempLlmModel)
          if (found) {
            routeAuto.value = false
            selectedProvider.value = p.id
            // 关键：await 等待模型列表加载完成
            await onProviderChange(p.id)
            // 确保模型在列表中
            if (!modelOptions.value.find(m =&gt; m.value === tempLlmModel)) {
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
      const agent = agentStore.agents.find(a =&gt; (a.agentId || a.id) === route.params.id) as Record&lt;string,unknown&gt; | undefined
      if (agent) {
        form.agentId = (agent.agentId || agent.id) as string || ''
        form.name = (agent.name as string) || ''
        form.description = (agent.description as string) || ''
        form.llmModel = (agent.llmModel as string) || 'auto'
        form.workingDirectory = (agent.workingDirectory as string) || ''
      }
    }
  }
  // 初次加载
  await loadConfig()
  // 监听路由参数变化（处理同组件不同 ID 的切换）
  watch(() =&gt; route.params.id, async () =&gt; {
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
    // 重新加载配置
    await loadConfig()
  })
})
&lt;/script&gt;
&lt;style scoped&gt;
.agent-form-page { display:flex;flex-direction:column;gap:16px;max-width:860px; }
.page-header { display:flex;justify-content:space-between;align-items:center;padding:20px 24px;border-radius:12px; }
.page-title { font-size:1.25rem;color:#e2e8f0;margin:0; }
.form-body { padding:28px;border-radius:12px; }
:deep(.settings-form .ant-form-item-label&gt;label){ color:rgba(255,255,255,0.6)!important; }
:deep(.settings-form .ant-input),:deep(.settings-form .ant-input-affix-wrapper),:deep(.settings-form textarea.ant-input){ background:rgba(255,255,255,0.05)!important;border:1px solid rgba(255,255,255,0.1)!important;color:#e2e8f0!important; }
:deep(.ant-divider-inner-text){ color:rgba(255,255,255,0.4)!important;font-size:0.85rem; }
&lt;/style&gt;
&nbsp;
<template>
  <div class="pg">
    <div class="hd glass-effect">
      <h2 class="t"><SendOutlined :style="{color:'#8b5cf6'}"/> 发起协作</h2>
    </div>

    <div class="card glass-effect">
      <a-spin v-if="loading" style="display:flex;justify-content:center;padding:20px" />
      <a-form v-else layout="vertical" @finish="handleSubmit">
        <a-row :gutter="24">
          <a-col :span="12">
            <a-form-item label="协作名称" name="name" :rules="[{ required: true, message: '请输入协作名称' }]">
              <a-input v-model:value="form.name" placeholder="输入协作名称" />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="选择模板" name="template_id">
              <a-select v-model:value="form.template_id" placeholder="选择模板（可选）" :options="templates.map(t=>({label:t.name,value:t.id}))" allow-clear />
            </a-form-item>
          </a-col>
        </a-row>

        <a-form-item label="参与Agent" name="participants" :rules="[{ required: true, message: '请选择至少一个Agent' }]">
          <a-select v-model:value="form.participants" mode="multiple" placeholder="选择参与Agent" :options="agents.map(a=>({label:a.agent_name || a.agent_id,value:a.agent_id}))" />
        </a-form-item>

        <a-form-item label="所需能力" name="required_capabilities">
          <a-select v-model:value="form.required_capabilities" mode="multiple" placeholder="选择所需能力（可选）" :options="capabilityOptions" allow-clear />
        </a-form-item>

        <a-form-item label="任务描述" name="task_description" :rules="[{ required: true, message: '请输入任务描述' }]">
          <a-textarea v-model:value="form.task_description" placeholder="描述协作目标" :rows="4" />
        </a-form-item>

        <a-row :gutter="24">
          <a-col :span="12">
            <a-form-item label="优先级" name="priority">
              <a-select v-model:value="form.priority" placeholder="选择优先级" :options="priorityOptions" />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="超时时间（秒）" name="timeout_seconds">
              <a-input-number v-model:value="form.timeout_seconds" :min="60" :max="3600" :step="60" placeholder="超时时间" style="width:100%" />
            </a-form-item>
          </a-col>
        </a-row>

        <a-form-item>
          <a-button type="primary" html-type="submit" size="large" :loading="submitting">启动协作</a-button>
        </a-form-item>
      </a-form>
    </div>

    <!-- 推荐Agent -->
    <div class="recommend glass-effect" v-if="recommendations.length">
      <h3><BulbOutlined /> 推荐Agent</h3>
      <div class="rec-list">
        <div v-for="r in recommendations" :key="r.agent_id" class="rec-item" @click="selectAgent(r.agent_id)">
          <div class="rec-info">
            <span class="rec-name">{{ r.agent_name || r.agent_id }}</span>
            <a-tag :color="getMatchColor(r.match_score)">{{ (r.match_score*100).toFixed(0) }}% 匹配</a-tag>
          </div>
          <div class="rec-caps">
            <span v-for="cap in r.matched_capabilities" :key="cap" class="cap-tag">{{ cap }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { SendOutlined, BulbOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { collaborationAPI } from '@/api/modules/collaboration'
import { agentAPI } from '@/api/modules/agents'

const loading = ref(false)
const submitting = ref(false)
interface TemplateInfo {
  id: string
  name: string
}

interface AgentInfo {
  agent_id: string
  agent_name?: string
}

interface Recommendation {
  agent_id: string
  agent_name?: string
  match_score: number
  matched_capabilities?: string[]
}

const templates = ref<TemplateInfo[]>([])
const agents = ref<AgentInfo[]>([])
const recommendations = ref<Recommendation[]>([])

const form = ref({
  name: '',
  template_id: undefined,
  participants: [],
  task_description: '',
  required_capabilities: [],
  priority: 'normal',
  timeout_seconds: 300
})

const capabilityOptions = [
  { label: '对话', value: 'chat' },
  { label: '搜索', value: 'search' },
  { label: '文档处理', value: 'doc' },
  { label: '代码', value: 'code' },
  { label: '数据分析', value: 'analytics' }
]

const priorityOptions = [
  { label: '低', value: 'low' },
  { label: '普通', value: 'normal' },
  { label: '高', value: 'high' },
  { label: '紧急', value: 'urgent' }
]

const getMatchColor = (score: number) => {
  if (score >= 0.8) return 'green'
  if (score >= 0.6) return 'orange'
  return 'red'
}

const selectAgent = (agentId: string) => {
  if (!form.value.participants.includes(agentId)) {
    form.value.participants.push(agentId)
  }
}

const loadData = async () => {
  loading.value = true
  try {
    const [templatesRes, agentsRes] = await Promise.allSettled([
      collaborationAPI.getTemplates(),
      agentAPI.list()
    ])

    if (templatesRes.status === 'fulfilled') {
      templates.value = templatesRes.value?.data?.templates || []
    }

    if (agentsRes.status === 'fulfilled') {
      agents.value = agentsRes.value?.data || []
    }
  } catch (err) {
    console.error('加载数据失败', err)
  } finally {
    loading.value = false
  }
}

const loadRecommendations = async () => {
  if (!form.value.task_description || form.value.required_capabilities.length === 0) {
    recommendations.value = []
    return
  }

  try {
    const res = await collaborationAPI.getRecommendations({
      required_capabilities: form.value.required_capabilities,
      min_match_score: 0.5
    })
    recommendations.value = res?.data?.recommendations || []
  } catch (err) {
    console.error('加载推荐失败', err)
  }
}

const handleSubmit = async () => {
  submitting.value = true
  try {
    const res = await collaborationAPI.startCollaboration({
      template_id: form.value.template_id,
      participants: form.value.participants,
      task_description: form.value.task_description,
      required_capabilities: form.value.required_capabilities,
      priority: form.value.priority,
      timeout_seconds: form.value.timeout_seconds
    })
    message.success('协作启动成功')
    // 重置表单或跳转
    form.value = {
      name: '',
      template_id: undefined,
      participants: [],
      task_description: '',
      required_capabilities: [],
      priority: 'normal',
      timeout_seconds: 300
    }
  } catch (err) {
    message.error('启动失败')
  } finally {
    submitting.value = false
  }
}

// 监听任务描述和能力变化，获取推荐
watch([() => form.value.task_description, () => form.value.required_capabilities], () => {
  loadRecommendations()
}, { debounce: 500 } as { debounce?: number })

onMounted(() => {
  loadData()
})
</script>

<style scoped>
.pg { display: flex; flex-direction: column; gap: 14px; }
.hd { padding: 16px 24px; border-radius: 12px; }
.t { font-size: 1.2rem; color: #e2e8f0; margin: 0; display: flex; align-items: center; gap: 8px; }
.card { padding: 28px; border-radius: 12px; max-width: 720px; }
.recommend { padding: 20px; border-radius: 12px; }
.recommend h3 { color: #e2e8f0; margin: 0 0 12px; display: flex; align-items: center; gap: 8px; }
.rec-list { display: flex; flex-direction: column; gap: 10px; }
.rec-item { padding: 12px; border-radius: 8px; background: rgba(255,255,255,0.03); cursor: pointer; transition: background 0.2s; }
.rec-item:hover { background: rgba(255,255,255,0.06); }
.rec-info { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.rec-name { color: #e2e8f0; font-weight: 500; }
.rec-caps { display: flex; flex-wrap: wrap; gap: 6px; }
.cap-tag { padding: 2px 8px; background: rgba(59,130,246,0.15); color: #60a5fa; border-radius: 4px; font-size: 0.75rem; }
</style>

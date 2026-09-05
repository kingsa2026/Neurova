&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h2 &gt;&lt;SendOutlined :style="{color:'#8b5cf6'}"/&gt; 发起协作&lt;/h2&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;a-spin v-if="loading" style="display:flex;justify-content:center;padding:20px" /&gt;
      &lt;a-form v-else layout="vertical" @finish="handleSubmit"&gt;
        &lt;a-row :gutter="24"&gt;
          &lt;a-col :span="12"&gt;
            &lt;a-form-item label="协作名称" name="name" :rules="[{ required: true, message: '请输入协作名称' }]"&gt;
              &lt;a-input v-model:value="form.name" placeholder="输入协作名称" /&gt;
            &lt;/a-form-item&gt;
          &lt;/a-col&gt;
          &lt;a-col :span="12"&gt;
            &lt;a-form-item label="选择模板" name="template_id"&gt;
              &lt;a-select v-model:value="form.template_id" placeholder="选择模板（可选）" :options="templates.map(t=&gt;({label:t.name,value:t.id}))" allow-clear /&gt;
            &lt;/a-form-item&gt;
          &lt;/a-col&gt;
        &lt;/a-row&gt;
        &lt;a-form-item label="参与Agent" name="participants" :rules="[{ required: true, message: '请选择至少一个Agent' }]"&gt;
          &lt;a-select v-model:value="form.participants" mode="multiple" placeholder="选择参与Agent" :options="agents.map(a=&gt;({label:a.agent_name || a.agent_id,value:a.agent_id}))" /&gt;
        &lt;/a-form-item&gt;
        &lt;a-form-item label="所需能力" name="required_capabilities"&gt;
          &lt;a-select v-model:value="form.required_capabilities" mode="multiple" placeholder="选择所需能力（可选）" :options="capabilityOptions" allow-clear /&gt;
        &lt;/a-form-item&gt;
        &lt;a-form-item label="任务描述" name="task_description" :rules="[{ required: true, message: '请输入任务描述' }]"&gt;
          &lt;a-textarea v-model:value="form.task_description" placeholder="描述协作目标" :rows="4" /&gt;
        &lt;/a-form-item&gt;
        &lt;a-row :gutter="24"&gt;
          &lt;a-col :span="12"&gt;
            &lt;a-form-item label="优先级" name="priority"&gt;
              &lt;a-select v-model:value="form.priority" placeholder="选择优先级" :options="priorityOptions" /&gt;
            &lt;/a-form-item&gt;
          &lt;/a-col&gt;
          &lt;a-col :span="12"&gt;
            &lt;a-form-item label="超时时间（秒）" name="timeout_seconds"&gt;
              &lt;a-input-number v-model:value="form.timeout_seconds" :min="60" :max="3600" :step="60" placeholder="超时时间" style="width:100%" /&gt;
            &lt;/a-form-item&gt;
          &lt;/a-col&gt;
        &lt;/a-row&gt;
        &lt;a-form-item&gt;
          &lt;a-button type="primary" html-type="submit" size="large" :loading="submitting"&gt;启动协作&lt;/a-button&gt;
        &lt;/a-form-item&gt;
      &lt;/a-form&gt;
    &lt;/div&gt;
    &lt;!-- 推荐Agent --&gt;
    &lt;div  v-if="recommendations.length"&gt;
      &lt;h3&gt;&lt;BulbOutlined /&gt; 推荐Agent&lt;/h3&gt;
      &lt;div &gt;
        &lt;div v-for="r in recommendations" :key="r.agent_id"  @click="selectAgent(r.agent_id)"&gt;
          &lt;div &gt;
            &lt;span &gt;{{ r.agent_name || r.agent_id }}&lt;/span&gt;
            &lt;a-tag :color="getMatchColor(r.match_score)"&gt;{{ (r.match_score*100).toFixed(0) }}% 匹配&lt;/a-tag&gt;
          &lt;/div&gt;
          &lt;div &gt;
            &lt;span v-for="cap in r.matched_capabilities" :key="cap" &gt;{{ cap }}&lt;/span&gt;
          &lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
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
const templates = ref&lt;TemplateInfo[]&gt;([])
const agents = ref&lt;AgentInfo[]&gt;([])
const recommendations = ref&lt;Recommendation[]&gt;([])
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
const getMatchColor = (score: number) =&gt; {
  if (score &gt;= 0.8) return 'green'
  if (score &gt;= 0.6) return 'orange'
  return 'red'
}
const selectAgent = (agentId: string) =&gt; {
  if (!form.value.participants.includes(agentId)) {
    form.value.participants.push(agentId)
  }
}
const loadData = async () =&gt; {
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
const loadRecommendations = async () =&gt; {
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
const handleSubmit = async () =&gt; {
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
watch([() =&gt; form.value.task_description, () =&gt; form.value.required_capabilities], () =&gt; {
  loadRecommendations()
}, { debounce: 500 } as { debounce?: number })
onMounted(() =&gt; {
  loadData()
})
&lt;/script&gt;
&lt;style scoped&gt;
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
&lt;/style&gt;
&nbsp;
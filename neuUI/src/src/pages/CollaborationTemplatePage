&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h2 &gt;&lt;FileTextOutlined :style="{color:'#3b82f6'}"/&gt; 协作模板&lt;/h2&gt;
      &lt;a-button type="primary" size="small" @click="showCreateModal = true"&gt;&lt;PlusOutlined/&gt; 新建模板&lt;/a-button&gt;
    &lt;/div&gt;
    &lt;!-- 统计 --&gt;
    &lt;div &gt;
      &lt;div &gt;
        模板&lt;b &gt;{{ templates.length }}&lt;/b&gt;
      &lt;/div&gt;
      &lt;div &gt;
        预设&lt;b &gt;{{ presets.length }}&lt;/b&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;!-- 加载状态 --&gt;
    &lt;a-spin v-if="loading" size="large" style="display:flex;justify-content:center;padding:40px" /&gt;
    &lt;!-- 模板列表 --&gt;
    &lt;div v-else&gt;
      &lt;!-- 自定义模板 --&gt;
      &lt;div  v-if="templates.length"&gt;
        &lt;h3&gt;自定义模板&lt;/h3&gt;
        &lt;div &gt;
          &lt;div v-for="t in templates" :key="t.id"  @click="viewTemplate(t)"&gt;
            &lt;h4&gt;{{ t.name }}&lt;/h4&gt;
            &lt;p&gt;{{ t.description || '暂无描述' }}&lt;/p&gt;
            &lt;div &gt;
              &lt;span&gt;{{ t.steps || t.workflow?.steps?.length || 0 }} 步骤&lt;/span&gt;
              &lt;a-tag v-if="t.tags?.length" size="small"&gt;{{ t.tags[0] }}&lt;/a-tag&gt;
              &lt;span &gt;使用 {{ t.usage_count || 0 }} 次&lt;/span&gt;
            &lt;/div&gt;
          &lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;!-- 预设模板 --&gt;
      &lt;div  v-if="presets.length"&gt;
        &lt;h3&gt;预设模板&lt;/h3&gt;
        &lt;div &gt;
          &lt;div v-for="t in presets" :key="t.id"  @click="viewTemplate(t)"&gt;
            &lt;h4&gt;{{ t.name }}&lt;/h4&gt;
            &lt;p&gt;{{ t.description || '暂无描述' }}&lt;/p&gt;
            &lt;div &gt;
              &lt;span&gt;{{ t.steps || t.workflow?.steps?.length || 0 }} 步骤&lt;/span&gt;
              &lt;a-tag color="blue" size="small"&gt;预设&lt;/a-tag&gt;
              &lt;span &gt;使用 {{ t.usage_count || 0 }} 次&lt;/span&gt;
            &lt;/div&gt;
          &lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;!-- 空状态 --&gt;
      &lt;div v-if="!templates.length &amp;&amp; !presets.length" &gt;
        暂无模板，点击"新建模板"创建第一个协作模板
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;!-- 模板详情模态框 --&gt;
    &lt;a-modal v-model:open="viewVisible" :title="currentTemplate?.name" width="700px" @ok="viewVisible=false"&gt;
      &lt;div v-if="currentTemplate" &gt;
        &lt;a-descriptions :column="2" bordered size="small"&gt;
          &lt;a-descriptions-item label="描述" :span="2"&gt;{{ currentTemplate.description || '暂无' }}&lt;/a-descriptions-item&gt;
          &lt;a-descriptions-item label="最大参与人数"&gt;{{ currentTemplate.max_participants || '无限制' }}&lt;/a-descriptions-item&gt;
          &lt;a-descriptions-item label="最小参与人数"&gt;{{ currentTemplate.min_participants || 1 }}&lt;/a-descriptions-item&gt;
          &lt;a-descriptions-item label="标签"&gt;
            &lt;a-tag v-for="tag in currentTemplate.tags" :key="tag"&gt;{{ tag }}&lt;/a-tag&gt;
          &lt;/a-descriptions-item&gt;
        &lt;/a-descriptions&gt;
        &lt;div  v-if="currentTemplate.workflow"&gt;
          &lt;h4&gt;工作流&lt;/h4&gt;
          &lt;div &gt;
            &lt;div v-for="(step, idx) in (currentTemplate.workflow.steps || [])" :key="idx" &gt;
              &lt;div &gt;{{ idx + 1 }}&lt;/div&gt;
              &lt;div &gt;
                &lt;span &gt;{{ step.name }}&lt;/span&gt;
                &lt;span &gt;{{ step.description || step.agent || '自动执行' }}&lt;/span&gt;
              &lt;/div&gt;
            &lt;/div&gt;
          &lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;template #footer&gt;
        &lt;a-space&gt;
          &lt;a-button @click="cloneTemplate(currentTemplate?.id)" :loading="cloning"&gt;克隆&lt;/a-button&gt;
          &lt;a-button type="primary" @click="useTemplate(currentTemplate)"&gt;使用此模板&lt;/a-button&gt;
        &lt;/a-space&gt;
      &lt;/template&gt;
    &lt;/a-modal&gt;
    &lt;!-- 创建模板模态框 --&gt;
    &lt;a-modal v-model:open="showCreateModal" title="新建模板" width="800px" @ok="createTemplate" :confirmLoading="creating"&gt;
      &lt;a-form layout="vertical"&gt;
        &lt;a-form-item label="模板名称" :rules="[{ required: true }]"&gt;
          &lt;a-input v-model:value="newTemplate.name" placeholder="输入模板名称" /&gt;
        &lt;/a-form-item&gt;
        &lt;a-form-item label="描述"&gt;
          &lt;a-textarea v-model:value="newTemplate.description" placeholder="输入描述" :rows="3" /&gt;
        &lt;/a-form-item&gt;
        &lt;a-form-item label="模板类型"&gt;
          &lt;a-select v-model:value="newTemplate.template_type" placeholder="选择类型" :options="typeOptions" /&gt;
        &lt;/a-form-item&gt;
        &lt;a-form-item label="标签"&gt;
          &lt;a-select v-model:value="newTemplate.tags" mode="tags" placeholder="输入标签" /&gt;
        &lt;/a-form-item&gt;
        &lt;a-row :gutter="16"&gt;
          &lt;a-col :span="12"&gt;
            &lt;a-form-item label="最大参与人数"&gt;
              &lt;a-input-number v-model:value="newTemplate.max_participants" :min="1" :max="10" /&gt;
            &lt;/a-form-item&gt;
          &lt;/a-col&gt;
          &lt;a-col :span="12"&gt;
            &lt;a-form-item label="最小参与人数"&gt;
              &lt;a-input-number v-model:value="newTemplate.min_participants" :min="1" :max="5" /&gt;
            &lt;/a-form-item&gt;
          &lt;/a-col&gt;
        &lt;/a-row&gt;
      &lt;/a-form&gt;
    &lt;/a-modal&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { FileTextOutlined, PlusOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { collaborationAPI } from '@/api/modules/collaboration'
const router = useRouter()
const loading = ref(false)
interface TemplateData {
  id: string
  name: string
  description?: string
  steps?: number
  workflow?: { steps?: { name?: string; description?: string; agent?: string }[] }
  tags?: string[]
  usage_count?: number
  max_participants?: number
  min_participants?: number
}
const templates = ref&lt;TemplateData[]&gt;([])
const presets = ref&lt;TemplateData[]&gt;([])
const viewVisible = ref(false)
const currentTemplate = ref&lt;TemplateData | null&gt;(null)
const showCreateModal = ref(false)
const creating = ref(false)
const cloning = ref(false)
const newTemplate = ref({
  name: '',
  description: '',
  template_type: 'custom',
  tags: [] as string[],
  max_participants: 5,
  min_participants: 1,
  workflow: { steps: [] }
})
const typeOptions = [
  { label: '自定义', value: 'custom' },
  { label: '文档处理', value: 'document' },
  { label: '数据分析', value: 'analytics' },
  { label: '代码生成', value: 'code' },
  { label: '问答系统', value: 'qa' }
]
const loadTemplates = async () =&gt; {
  loading.value = true
  try {
    const [customRes, presetRes] = await Promise.allSettled([
      collaborationAPI.getTemplates(),
      collaborationAPI.getPresetTemplates()
    ])
    if (customRes.status === 'fulfilled') {
      templates.value = customRes.value?.data?.templates || []
    }
    if (presetRes.status === 'fulfilled') {
      presets.value = presetRes.value?.data?.templates || []
    }
  } catch (err) {
    console.error('加载模板失败', err)
  } finally {
    loading.value = false
  }
}
const viewTemplate = (t: TemplateData) =&gt; {
  currentTemplate.value = t
  viewVisible.value = true
}
const useTemplate = (t: TemplateData) =&gt; {
  viewVisible.value = false
  router.push({ path: '/collaboration/initiate', query: { template_id: t.id } })
}
const cloneTemplate = async (id: string) =&gt; {
  if (!id) return
  cloning.value = true
  try {
    await collaborationAPI.cloneTemplate(id)
    message.success('克隆成功')
    viewVisible.value = false
    loadTemplates()
  } catch (err) {
    message.error('克隆失败')
  } finally {
    cloning.value = false
  }
}
const createTemplate = async () =&gt; {
  if (!newTemplate.value.name) {
    message.error('请输入模板名称')
    return
  }
  creating.value = true
  try {
    await collaborationAPI.createTemplate(newTemplate.value as Parameters&lt;typeof collaborationAPI.createTemplate&gt;[0])
    message.success('创建成功')
    showCreateModal.value = false
    newTemplate.value = {
      name: '',
      description: '',
      template_type: 'custom',
      tags: [],
      max_participants: 5,
      min_participants: 1,
      workflow: { steps: [] }
    }
    loadTemplates()
  } catch (err) {
    message.error('创建失败')
  } finally {
    creating.value = false
  }
}
onMounted(() =&gt; {
  loadTemplates()
})
&lt;/script&gt;
&lt;style scoped&gt;
.pg { display: flex; flex-direction: column; gap: 14px; }
.hd { display: flex; justify-content: space-between; align-items: center; padding: 16px 24px; border-radius: 12px; }
.t { font-size: 1.2rem; color: #e2e8f0; margin: 0; display: flex; align-items: center; gap: 8px; }
.stats { display: flex; gap: 12px; }
.s { flex: 1; padding: 14px 18px; border-radius: 10px; display: flex; justify-content: space-between; align-items: center; color: rgba(255,255,255,0.5); font-size: 0.85rem; }
.s b { font-size: 1.4rem; }
.c1 { color: #3b82f6; }
.section { margin-bottom: 20px; }
.section h3 { color: #e2e8f0; margin: 0 0 12px; font-size: 1rem; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 14px; }
.card { padding: 20px; border-radius: 12px; cursor: pointer; transition: transform 0.2s, box-shadow 0.2s; }
.card:hover { transform: translateY(-2px); box-shadow: 0 8px 16px rgba(0,0,0,0.2); }
.card h4 { color: #e2e8f0; margin: 0 0 6px; }
.card p { color: rgba(255,255,255,0.4); font-size: 0.82rem; margin: 0 0 14px; }
.cf { display: flex; justify-content: space-between; align-items: center; color: rgba(255,255,255,0.3); font-size: 0.78rem; }
.usage { color: rgba(255,255,255,0.2); }
.empty { text-align: center; padding: 64px 0; color: rgba(255,255,255,0.3); border-radius: 12px; }
.template-detail { padding: 10px 0; }
.workflow-section { margin-top: 16px; }
.workflow-section h4 { color: #e2e8f0; margin: 0 0 12px; }
.steps { display: flex; flex-direction: column; gap: 8px; }
.step-item { display: flex; align-items: flex-start; gap: 12px; padding: 10px; background: rgba(255,255,255,0.03); border-radius: 8px; }
.step-num { min-width: 24px; height: 24px; background: #3b82f6; border-radius: 50%; display: flex; align-items: center; justify-content: center; color: white; font-size: 0.8rem; font-weight: 700; }
.step-content { flex: 1; }
.step-name { color: #e2e8f0; font-weight: 500; display: block; }
.step-desc { color: rgba(255,255,255,0.4); font-size: 0.8rem; }
&lt;/style&gt;
&nbsp;
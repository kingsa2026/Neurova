<template>
  <div >
    <div >
      <h2 ><FileTextOutlined :style="{color:'#3b82f6'}"/> 协作模板</h2>
      <a-button type="primary" size="small" @click="showCreateModal = true"><PlusOutlined/> 新建模板</a-button>
    </div>
    <!-- 统计 -->
    <div >
      <div >
        模板<b >{{ templates.length }}</b>
      </div>
      <div >
        预设<b >{{ presets.length }}</b>
      </div>
    </div>
    <!-- 加载状态 -->
    <a-spin v-if="loading" size="large" style="display:flex;justify-content:center;padding:40px" />
    <!-- 模板列表 -->
    <div v-else>
      <!-- 自定义模板 -->
      <div  v-if="templates.length">
        <h3>自定义模板</h3>
        <div >
          <div v-for="t in templates" :key="t.id"  @click="viewTemplate(t)">
            <h4>{{ t.name }}</h4>
            <p>{{ t.description || '暂无描述' }}</p>
            <div >
              <span>{{ t.steps || t.workflow?.steps?.length || 0 }} 步骤</span>
              <a-tag v-if="t.tags?.length" size="small">{{ t.tags[0] }}</a-tag>
              <span >使用 {{ t.usage_count || 0 }} 次</span>
            </div>
          </div>
        </div>
      </div>
      <!-- 预设模板 -->
      <div  v-if="presets.length">
        <h3>预设模板</h3>
        <div >
          <div v-for="t in presets" :key="t.id"  @click="viewTemplate(t)">
            <h4>{{ t.name }}</h4>
            <p>{{ t.description || '暂无描述' }}</p>
            <div >
              <span>{{ t.steps || t.workflow?.steps?.length || 0 }} 步骤</span>
              <a-tag color="blue" size="small">预设</a-tag>
              <span >使用 {{ t.usage_count || 0 }} 次</span>
            </div>
          </div>
        </div>
      </div>
      <!-- 空状态 -->
      <div v-if="!templates.length && !presets.length" >
        暂无模板，点击"新建模板"创建第一个协作模板
      </div>
    </div>
    <!-- 模板详情模态框 -->
    <a-modal v-model:open="viewVisible" :title="currentTemplate?.name" width="700px" @ok="viewVisible=false">
      <div v-if="currentTemplate" >
        <a-descriptions :column="2" bordered size="small">
          <a-descriptions-item label="描述" :span="2">{{ currentTemplate.description || '暂无' }}</a-descriptions-item>
          <a-descriptions-item label="最大参与人数">{{ currentTemplate.max_participants || '无限制' }}</a-descriptions-item>
          <a-descriptions-item label="最小参与人数">{{ currentTemplate.min_participants || 1 }}</a-descriptions-item>
          <a-descriptions-item label="标签">
            <a-tag v-for="tag in currentTemplate.tags" :key="tag">{{ tag }}</a-tag>
          </a-descriptions-item>
        </a-descriptions>
        <div  v-if="currentTemplate.workflow">
          <h4>工作流</h4>
          <div >
            <div v-for="(step, idx) in (currentTemplate.workflow.steps || [])" :key="idx" >
              <div >{{ idx + 1 }}</div>
              <div >
                <span >{{ step.name }}</span>
                <span >{{ step.description || step.agent || '自动执行' }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
      <template #footer>
        <a-space>
          <a-button @click="cloneTemplate(currentTemplate?.id)" :loading="cloning">克隆</a-button>
          <a-button type="primary" @click="useTemplate(currentTemplate)">使用此模板</a-button>
        </a-space>
      </template>
    </a-modal>
    <!-- 创建模板模态框 -->
    <a-modal v-model:open="showCreateModal" title="新建模板" width="800px" @ok="createTemplate" :confirmLoading="creating">
      <a-form layout="vertical">
        <a-form-item label="模板名称" :rules="[{ required: true }]">
          <a-input v-model:value="newTemplate.name" placeholder="输入模板名称" />
        </a-form-item>
        <a-form-item label="描述">
          <a-textarea v-model:value="newTemplate.description" placeholder="输入描述" :rows="3" />
        </a-form-item>
        <a-form-item label="模板类型">
          <a-select v-model:value="newTemplate.template_type" placeholder="选择类型" :options="typeOptions" />
        </a-form-item>
        <a-form-item label="标签">
          <a-select v-model:value="newTemplate.tags" mode="tags" placeholder="输入标签" />
        </a-form-item>
        <a-row :gutter="16">
          <a-col :span="12">
            <a-form-item label="最大参与人数">
              <a-input-number v-model:value="newTemplate.max_participants" :min="1" :max="10" />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="最小参与人数">
              <a-input-number v-model:value="newTemplate.min_participants" :min="1" :max="5" />
            </a-form-item>
          </a-col>
        </a-row>
      </a-form>
    </a-modal>
  </div>
</template>
<script setup lang="ts">
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
const templates = ref<TemplateData[]>([])
const presets = ref<TemplateData[]>([])
const viewVisible = ref(false)
const currentTemplate = ref<TemplateData | null>(null)
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
const loadTemplates = async () => {
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
const viewTemplate = (t: TemplateData) => {
  currentTemplate.value = t
  viewVisible.value = true
}
const useTemplate = (t: TemplateData) => {
  viewVisible.value = false
  router.push({ path: '/collaboration/initiate', query: { template_id: t.id } })
}
const cloneTemplate = async (id: string) => {
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
const createTemplate = async () => {
  if (!newTemplate.value.name) {
    message.error('请输入模板名称')
    return
  }
  creating.value = true
  try {
    await collaborationAPI.createTemplate(newTemplate.value as Parameters<typeof collaborationAPI.createTemplate>[0])
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
onMounted(() => {
  loadTemplates()
})
</script>
<style scoped>
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
</style>
 
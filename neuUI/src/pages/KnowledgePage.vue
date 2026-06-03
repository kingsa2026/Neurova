<template>
  <div >
    <!-- 页面头部 -->
    <div >
      <h2 ><BookOutlined /> 知识库</h2>
      <div >
        <a-button @click="configVisible = true"><SettingOutlined /> 配置管理</a-button>
        <a-button @click="createColVisible = true"><PlusOutlined /> 创建知识库</a-button>
        <a-button type="primary" @click="uploadVisible = true"><UploadOutlined /> 上传文档</a-button>
      </div>
    </div>
    <!-- 错误提示 -->
    <a-alert v-if="kbError" :message="kbError" type="error" show-icon closable />
    <!-- 标签页 -->
    <a-tabs v-model:activeKey="activeTab" >
      <a-tab-pane key="collections" tab="知识库列表">
        <!-- 加载状态 -->
        <a-spin v-if="colLoading" size="large" style="display:flex;justify-content:center;padding:40px" />
        <!-- 知识库列表 -->
        <div  v-else-if="collections.length">
          <div v-for="col in collections" :key="col.id"  @click="selectCollection(col)">
            <div ><FolderOutlined /></div>
            <div >
              <h4>{{ col.collection_name }}</h4>
              <p>{{ col.collection_description || '暂无描述' }}</p>
              <div >
                <a-tag size="small" :color="col.id === selectedCol?.id?'blue':'default'">
                  {{ col.id === selectedCol?.id?'当前选择':'' }}
                </a-tag>
                <span >{{ formatDate(col.created_at) }}</span>
              </div>
            </div>
          </div>
        </div>
        <div v-else >暂无知识库，点击"创建知识库"开始</div>
      </a-tab-pane>
      <a-tab-pane key="documents" tab="文档管理">
        <!-- 搜索栏 -->
        <div >
          <a-input-search v-model:value="kw" placeholder="搜索文档..." style="width:360px" allow-clear @search="searchDocs" />
          <a-select v-model:value="selCol" placeholder="选择知识库" style="width:200px" allow-clear @change="loadDocuments">
            <a-option v-for="c in collections" :key="c.id" :value="c.id">{{ c.collection_name }}</a-option>
          </a-select>
        </div>
        <!-- 加载状态 -->
        <a-spin v-if="docLoading" size="large" style="display:flex;justify-content:center;padding:40px" />
        <!-- 文档列表 -->
        <div  v-else-if="documents.length">
          <div v-for="doc in documents" :key="doc.id" >
            <div ><FileTextOutlined /></div>
            <div >
              <h4>{{ doc.name }}</h4>
              <p>{{ doc.description || doc.summary || '暂无描述' }}</p>
              <div >
                <a-tag size="small" :color="getStatusColor(doc.status)">{{ doc.status || '处理中' }}</a-tag>
                <span >{{ formatDate(doc.created_at) }}</span>
                <a-button type="link" size="small" danger @click.stop="deleteDoc(doc.id)">删除</a-button>
              </div>
            </div>
          </div>
        </div>
        <div v-else >暂无文档，点击"上传文档"开始</div>
      </a-tab-pane>
      <a-tab-pane key="search" tab="智能搜索">
        <div >
          <a-input-search v-model:value="searchQuery" placeholder="输入搜索内容，进行语义检索..." size="large" @search="doSearch" enter-button="搜索" />
          <div  style="margin-top:10px">
            <a-select v-model:value="searchCol" placeholder="选择知识库（可选）" style="width:200px" allow-clear>
              <a-option v-for="c in collections" :key="c.id" :value="c.id">{{ c.collection_name }}</a-option>
            </a-select>
            <a-tag color="blue" style="margin-left:10px">支持语义搜索</a-tag>
          </div>
        </div>
        <a-spin v-if="searchLoading" size="large" style="display:flex;justify-content:center;padding:40px" />
        <div  v-else-if="searchResults.length">
          <div v-for="(item,idx) in searchResults" :key="idx" >
            <div >{{ (item.score*100).toFixed(0) }}%</div>
            <div >
              <h4>{{ item.title || item.source_name || '相关文档' }}</h4>
              <p>{{ item.content || item.text || item.summary }}</p>
              <a-tag v-if="item.collection_id" size="small">{{ item.collection_id }}</a-tag>
            </div>
          </div>
        </div>
        <div v-else-if="searchQuery" >未找到相关结果</div>
        <div v-else >输入搜索内容开始检索</div>
      </a-tab-pane>
    </a-tabs>
    <!-- 配置管理模态框 -->
    <a-modal v-model:open="configVisible" title="知识库配置管理" width="800px" @ok="saveConfig">
      <a-spin v-if="configLoading" />
      <div v-else>
        <a-button type="primary" size="small" @click="addNewConfig" style="margin-bottom:16px"><PlusOutlined /> 添加配置</a-button>
        <a-list :data-source="configs" size="small">
          <template #renderItem="{ item }">
            <a-list-item>
              <a-list-item-meta>
                <template #title>
                  {{ item.config_name }}
                  <a-tag v-if="item.is_default" color="blue">默认</a-tag>
                  <a-tag v-if="item.is_active" color="green">已启用</a-tag>
                  <a-tag v-else color="default">已禁用</a-tag>
                </template>
                <template #description>
                  {{ item.source_type }} · API Key: {{ item.api_key }}
                </template>
              </a-list-item-meta>
              <a-space>
                <a-button size="small" @click="editConfig(item)">编辑</a-button>
                <a-button size="small" danger @click="deleteConfig(item.id)">删除</a-button>
              </a-space>
            </a-list-item>
          </template>
        </a-list>
      </div>
      <!-- 编辑配置的子模态框 -->
      <a-modal v-model:open="editConfigVisible" title="编辑配置" @ok="submitConfig">
        <a-form layout="vertical">
          <a-form-item label="配置名称">
            <a-input v-model:value="editingConfig.config_name" />
          </a-form-item>
          <a-form-item label="API Key">
            <a-input-password v-model:value="editingConfig.api_key" placeholder="输入API Key" />
          </a-form-item>
          <a-form-item label="Base URL（可选）">
            <a-input v-model:value="editingConfig.base_url" placeholder="https://platform.iflow.cn" />
          </a-form-item>
          <a-form-item label="设为默认">
            <a-switch v-model:checked="editingConfig.is_default" />
          </a-form-item>
          <a-form-item label="启用">
            <a-switch v-model:checked="editingConfig.is_active" />
          </a-form-item>
        </a-form>
      </a-modal>
    </a-modal>
    <!-- 创建知识库模态框 -->
    <a-modal v-model:open="createColVisible" title="创建知识库" @ok="createCollection">
      <a-form layout="vertical">
        <a-form-item label="知识库名称">
          <a-input v-model:value="newCol.name" placeholder="输入知识库名称" />
        </a-form-item>
        <a-form-item label="描述">
          <a-textarea v-model:value="newCol.description" placeholder="输入描述（可选）" :rows="3" />
        </a-form-item>
      </a-form>
    </a-modal>
    <!-- 上传文档模态框 -->
    <a-modal v-model:open="uploadVisible" title="上传文档" @ok="uploadVisible = false" width="700px">
      <a-form layout="vertical">
        <a-form-item label="选择知识库">
          <a-select v-model:value="uploadCol" placeholder="请选择要上传到的知识库" style="width:100%">
            <a-option v-for="c in collections" :key="c.id" :value="c.id">{{ c.collection_name }}</a-option>
          </a-select>
        </a-form-item>
        <a-form-item label="文档">
          <a-upload-dragger name="file" :file-list="fileList" :before-upload="beforeUpload" :on-change="handleFileChange" :multiple="true">
            <p ><InboxOutlined /></p>
            <p >点击或拖拽文件到此区域上传</p>
            <p >支持 PDF、Word、TXT、Markdown、PPT、Excel 等格式</p>
          </a-upload-dragger>
        </a-form-item>
        <a-button type="primary" :loading="uploading" @click="doUpload" block>上传文档</a-button>
      </a-form>
    </a-modal>
  </div>
</template>
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { BookOutlined, UploadOutlined, FileTextOutlined, InboxOutlined, FolderOutlined, SettingOutlined, PlusOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { knowledgeAPI, type KnowledgeConfig } from '@/api/modules/knowledge_api'
// 状态
const activeTab = ref('collections')
const kw = ref('')
const kbError = ref('')
const kbLoading = ref(false)
// 配置管理
const configVisible = ref(false)
const configLoading = ref(false)
const configs = ref<KnowledgeConfig[]>([])
const editConfigVisible = ref(false)
const editingConfig = ref<Partial<KnowledgeConfig>>({})
// 知识库管理
const createColVisible = ref(false)
const colLoading = ref(false)
interface CollectionData { id: string; collection_name: string; collection_description?: string; created_at?: string }
const collections = ref<CollectionData[]>([])
const selectedCol = ref<CollectionData | null>(null)
const newCol = ref({ name: '', description: '' })
// 文档管理
const uploadVisible = ref(false)
const docLoading = ref(false)
interface DocumentData { id: string; name: string; description?: string; summary?: string; status?: string; created_at?: string }
const documents = ref<DocumentData[]>([])
const selCol = ref<string>('')
const uploadCol = ref<string>('')
interface UploadFile { uid: string; name: string; originFileObj?: File; status?: string }
const fileList = ref<UploadFile[]>([])
const uploading = ref(false)
// 搜索
const searchQuery = ref('')
const searchCol = ref<string>('')
const searchLoading = ref(false)
interface SearchResult { score: number; title?: string; source_name?: string; content?: string; text?: string; summary?: string; collection_id?: string }
const searchResults = ref<SearchResult[]>([])
// 格式化日期
const formatDate = (d: string) => {
  if (!d) return ''
  const dt = new Date(d)
  return `${dt.getFullYear()}-${String(dt.getMonth()+1).padStart(2,'0')}-${String(dt.getDate()).padStart(2,'0')}`
}
const getStatusColor = (status: string) => {
  const map: Record<string,string> = { processed:'green', processing:'blue', error:'red', failed:'red', ready:'blue' }
  return map[status] || 'default'
}
// 加载配置
const loadConfigs = async () => {
  configLoading.value = true
  try {
    const res = await knowledgeAPI.getConfigs()
    if (res?.data?.configs) configs.value = res.data.configs
  } catch (e) {
    console.error('加载配置失败', e)
  } finally {
    configLoading.value = false
  }
}
const addNewConfig = () => {
  editingConfig.value = { config_name:'新配置', is_default:false, is_active:true, source_type:'iflow' }
  editConfigVisible.value = true
}
const editConfig = (cfg: KnowledgeConfig) => {
  editingConfig.value = { ...cfg }
  editConfigVisible.value = true
}
const deleteConfig = async (id: string) => {
  try {
    await knowledgeAPI.deleteConfig(id)
    message.success('删除成功')
    loadConfigs()
  } catch (e) {
    message.error('删除失败')
  }
}
const submitConfig = async () => {
  try {
    if (editingConfig.value.id) {
      await knowledgeAPI.updateConfig(editingConfig.value.id, editingConfig.value as KnowledgeConfig)
    } else {
      await knowledgeAPI.createConfig(editingConfig.value as KnowledgeConfig)
    }
    message.success('保存成功')
    editConfigVisible.value = false
    loadConfigs()
  } catch (e) {
    message.error('保存失败')
  }
}
const saveConfig = () => { configVisible.value = false }
// 加载知识库
const loadCollections = async () => {
  colLoading.value = true
  kbError.value = ''
  try {
    const res = await knowledgeAPI.getCollections()
    if (res?.data?.collections) {
      collections.value = res.data.collections
      if (collections.value.length && !selectedCol.value) {
        selectedCol.value = collections.value[0]
        selCol.value = selectedCol.value.id
      }
    }
  } catch (e: unknown) {
    const err = e as { response?: { data?: { message?: string } }; message?: string }
    kbError.value = err?.response?.data?.message || err?.message || '加载知识库失败'
    console.error('加载知识库失败', e)
  } finally {
    colLoading.value = false
  }
}
const selectCollection = (col: CollectionData) => {
  selectedCol.value = col
  selCol.value = col.id
  activeTab.value = 'documents'
  loadDocuments()
}
const createCollection = async () => {
  if (!newCol.value.name) { message.error('请输入知识库名称'); return }
  try {
    await knowledgeAPI.createCollection(newCol.value)
    message.success('创建成功')
    createColVisible.value = false
    newCol.value = { name:'', description:'' }
    loadCollections()
  } catch (e) {
    message.error('创建失败')
  }
}
// 加载文档
const loadDocuments = async () => {
  if (!selCol.value) return
  docLoading.value = true
  try {
    const res = await knowledgeAPI.getDocuments(selCol.value, 1, 50, kw.value)
    if (res?.data?.documents) documents.value = res.data.documents
  } catch (e) {
    console.error('加载文档失败', e)
  } finally {
    docLoading.value = false
  }
}
const searchDocs = () => loadDocuments()
const deleteDoc = async (id: string) => {
  try {
    await knowledgeAPI.deleteDocument(id)
    message.success('删除成功')
    loadDocuments()
  } catch (e) {
    message.error('删除失败')
  }
}
// 上传
const beforeUpload = (file: UploadFile) => {
  fileList.value = [...fileList.value, file]
  return false
}
const handleFileChange = (info: { fileList: UploadFile[] }) => {
  fileList.value = info.fileList
}
const doUpload = async () => {
  if (!uploadCol.value) { message.error('请选择知识库'); return }
  if (!fileList.value.length) { message.error('请选择文件'); return }
  uploading.value = true
  try {
    for (const f of fileList.value) {
      const fd = new FormData()
      fd.append('file', f.originFileObj || f)
      fd.append('collectionId', uploadCol.value)
      fd.append('name', f.name)
      await knowledgeAPI.uploadDocument(fd)
    }
    message.success('上传成功')
    uploadVisible.value = false
    fileList.value = []
    loadDocuments()
  } catch (e) {
    message.error('上传失败')
  } finally {
    uploading.value = false
  }
}
// 搜索
const doSearch = async () => {
  if (!searchQuery.value) return
  searchLoading.value = true
  try {
    const res = await knowledgeAPI.search(searchQuery.value, searchCol.value || undefined)
    if (res?.data?.items) searchResults.value = res.data.items
  } catch (e) {
    message.error('搜索失败')
  } finally {
    searchLoading.value = false
  }
}
onMounted(async () => {
  await Promise.all([loadConfigs(), loadCollections()])
})
</script>
<style scoped>
.knowledge-page { display:flex;flex-direction:column;gap:16px; }
.page-header { display:flex;justify-content:space-between;align-items:center;padding:16px 24px;border-radius:12px; }
.page-title { font-size:1.25rem;color:#e2e8f0;margin:0;display:flex;align-items:center;gap:8px; }
.header-actions { display:flex;gap:8px; }
.search-bar { display:flex;align-items:center;gap:10px;padding:12px 16px;border-radius:10px; }
.filter-tag { cursor:pointer; }
.kb-tabs { background:transparent; }
.kb-tabs :deep(.ant-tabs-nav) { background:rgba(255,255,255,0.03); border-radius:8px; padding:0 8px; }
.kb-grid { display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px; }
.kb-card { display:flex;gap:16px;padding:20px;border-radius:12px;cursor:pointer; }
.kb-icon { font-size:2rem;color:#60a5fa;opacity:0.6; }
.kb-info h4 { color:#e2e8f0;margin:0 0 6px; }
.kb-info p { color:rgba(255,255,255,0.4);font-size:0.85rem;margin:0 0 8px; }
.kb-meta { display:flex;align-items:center;gap:8px; }
.kb-date { color:rgba(255,255,255,0.25);font-size:0.75rem; }
.empty-state { text-align:center;padding:64px 0;color:rgba(255,255,255,0.3);border-radius:12px; }
.search-section { padding:16px;border-radius:12px; }
.search-options { display:flex;align-items:center; }
.search-results { display:flex;flex-direction:column;gap:12px; }
.search-item { display:flex;gap:16px;padding:16px;border-radius:10px; }
.search-score { min-width:50px;text-align:right;font-size:1.25rem;color:#34d399;font-weight:700; }
.search-content { flex:1; }
.search-content h4 { color:#e2e8f0;margin:0 0 6px; }
.search-content p { color:rgba(255,255,255,0.5);margin:0; }
</style>
 
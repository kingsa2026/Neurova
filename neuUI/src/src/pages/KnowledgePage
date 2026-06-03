&lt;template&gt;
  &lt;div &gt;
    &lt;!-- 页面头部 --&gt;
    &lt;div &gt;
      &lt;h2 &gt;&lt;BookOutlined /&gt; 知识库&lt;/h2&gt;
      &lt;div &gt;
        &lt;a-button @click="configVisible = true"&gt;&lt;SettingOutlined /&gt; 配置管理&lt;/a-button&gt;
        &lt;a-button @click="createColVisible = true"&gt;&lt;PlusOutlined /&gt; 创建知识库&lt;/a-button&gt;
        &lt;a-button type="primary" @click="uploadVisible = true"&gt;&lt;UploadOutlined /&gt; 上传文档&lt;/a-button&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;!-- 错误提示 --&gt;
    &lt;a-alert v-if="kbError" :message="kbError" type="error" show-icon closable /&gt;
    &lt;!-- 标签页 --&gt;
    &lt;a-tabs v-model:activeKey="activeTab" &gt;
      &lt;a-tab-pane key="collections" tab="知识库列表"&gt;
        &lt;!-- 加载状态 --&gt;
        &lt;a-spin v-if="colLoading" size="large" style="display:flex;justify-content:center;padding:40px" /&gt;
        &lt;!-- 知识库列表 --&gt;
        &lt;div  v-else-if="collections.length"&gt;
          &lt;div v-for="col in collections" :key="col.id"  @click="selectCollection(col)"&gt;
            &lt;div &gt;&lt;FolderOutlined /&gt;&lt;/div&gt;
            &lt;div &gt;
              &lt;h4&gt;{{ col.collection_name }}&lt;/h4&gt;
              &lt;p&gt;{{ col.collection_description || '暂无描述' }}&lt;/p&gt;
              &lt;div &gt;
                &lt;a-tag size="small" :color="col.id === selectedCol?.id?'blue':'default'"&gt;
                  {{ col.id === selectedCol?.id?'当前选择':'' }}
                &lt;/a-tag&gt;
                &lt;span &gt;{{ formatDate(col.created_at) }}&lt;/span&gt;
              &lt;/div&gt;
            &lt;/div&gt;
          &lt;/div&gt;
        &lt;/div&gt;
        &lt;div v-else &gt;暂无知识库，点击"创建知识库"开始&lt;/div&gt;
      &lt;/a-tab-pane&gt;
      &lt;a-tab-pane key="documents" tab="文档管理"&gt;
        &lt;!-- 搜索栏 --&gt;
        &lt;div &gt;
          &lt;a-input-search v-model:value="kw" placeholder="搜索文档..." style="width:360px" allow-clear @search="searchDocs" /&gt;
          &lt;a-select v-model:value="selCol" placeholder="选择知识库" style="width:200px" allow-clear @change="loadDocuments"&gt;
            &lt;a-option v-for="c in collections" :key="c.id" :value="c.id"&gt;{{ c.collection_name }}&lt;/a-option&gt;
          &lt;/a-select&gt;
        &lt;/div&gt;
        &lt;!-- 加载状态 --&gt;
        &lt;a-spin v-if="docLoading" size="large" style="display:flex;justify-content:center;padding:40px" /&gt;
        &lt;!-- 文档列表 --&gt;
        &lt;div  v-else-if="documents.length"&gt;
          &lt;div v-for="doc in documents" :key="doc.id" &gt;
            &lt;div &gt;&lt;FileTextOutlined /&gt;&lt;/div&gt;
            &lt;div &gt;
              &lt;h4&gt;{{ doc.name }}&lt;/h4&gt;
              &lt;p&gt;{{ doc.description || doc.summary || '暂无描述' }}&lt;/p&gt;
              &lt;div &gt;
                &lt;a-tag size="small" :color="getStatusColor(doc.status)"&gt;{{ doc.status || '处理中' }}&lt;/a-tag&gt;
                &lt;span &gt;{{ formatDate(doc.created_at) }}&lt;/span&gt;
                &lt;a-button type="link" size="small" danger @click.stop="deleteDoc(doc.id)"&gt;删除&lt;/a-button&gt;
              &lt;/div&gt;
            &lt;/div&gt;
          &lt;/div&gt;
        &lt;/div&gt;
        &lt;div v-else &gt;暂无文档，点击"上传文档"开始&lt;/div&gt;
      &lt;/a-tab-pane&gt;
      &lt;a-tab-pane key="search" tab="智能搜索"&gt;
        &lt;div &gt;
          &lt;a-input-search v-model:value="searchQuery" placeholder="输入搜索内容，进行语义检索..." size="large" @search="doSearch" enter-button="搜索" /&gt;
          &lt;div  style="margin-top:10px"&gt;
            &lt;a-select v-model:value="searchCol" placeholder="选择知识库（可选）" style="width:200px" allow-clear&gt;
              &lt;a-option v-for="c in collections" :key="c.id" :value="c.id"&gt;{{ c.collection_name }}&lt;/a-option&gt;
            &lt;/a-select&gt;
            &lt;a-tag color="blue" style="margin-left:10px"&gt;支持语义搜索&lt;/a-tag&gt;
          &lt;/div&gt;
        &lt;/div&gt;
        &lt;a-spin v-if="searchLoading" size="large" style="display:flex;justify-content:center;padding:40px" /&gt;
        &lt;div  v-else-if="searchResults.length"&gt;
          &lt;div v-for="(item,idx) in searchResults" :key="idx" &gt;
            &lt;div &gt;{{ (item.score*100).toFixed(0) }}%&lt;/div&gt;
            &lt;div &gt;
              &lt;h4&gt;{{ item.title || item.source_name || '相关文档' }}&lt;/h4&gt;
              &lt;p&gt;{{ item.content || item.text || item.summary }}&lt;/p&gt;
              &lt;a-tag v-if="item.collection_id" size="small"&gt;{{ item.collection_id }}&lt;/a-tag&gt;
            &lt;/div&gt;
          &lt;/div&gt;
        &lt;/div&gt;
        &lt;div v-else-if="searchQuery" &gt;未找到相关结果&lt;/div&gt;
        &lt;div v-else &gt;输入搜索内容开始检索&lt;/div&gt;
      &lt;/a-tab-pane&gt;
    &lt;/a-tabs&gt;
    &lt;!-- 配置管理模态框 --&gt;
    &lt;a-modal v-model:open="configVisible" title="知识库配置管理" width="800px" @ok="saveConfig"&gt;
      &lt;a-spin v-if="configLoading" /&gt;
      &lt;div v-else&gt;
        &lt;a-button type="primary" size="small" @click="addNewConfig" style="margin-bottom:16px"&gt;&lt;PlusOutlined /&gt; 添加配置&lt;/a-button&gt;
        &lt;a-list :data-source="configs" size="small"&gt;
          &lt;template #renderItem="{ item }"&gt;
            &lt;a-list-item&gt;
              &lt;a-list-item-meta&gt;
                &lt;template #title&gt;
                  {{ item.config_name }}
                  &lt;a-tag v-if="item.is_default" color="blue"&gt;默认&lt;/a-tag&gt;
                  &lt;a-tag v-if="item.is_active" color="green"&gt;已启用&lt;/a-tag&gt;
                  &lt;a-tag v-else color="default"&gt;已禁用&lt;/a-tag&gt;
                &lt;/template&gt;
                &lt;template #description&gt;
                  {{ item.source_type }} · API Key: {{ item.api_key }}
                &lt;/template&gt;
              &lt;/a-list-item-meta&gt;
              &lt;a-space&gt;
                &lt;a-button size="small" @click="editConfig(item)"&gt;编辑&lt;/a-button&gt;
                &lt;a-button size="small" danger @click="deleteConfig(item.id)"&gt;删除&lt;/a-button&gt;
              &lt;/a-space&gt;
            &lt;/a-list-item&gt;
          &lt;/template&gt;
        &lt;/a-list&gt;
      &lt;/div&gt;
      &lt;!-- 编辑配置的子模态框 --&gt;
      &lt;a-modal v-model:open="editConfigVisible" title="编辑配置" @ok="submitConfig"&gt;
        &lt;a-form layout="vertical"&gt;
          &lt;a-form-item label="配置名称"&gt;
            &lt;a-input v-model:value="editingConfig.config_name" /&gt;
          &lt;/a-form-item&gt;
          &lt;a-form-item label="API Key"&gt;
            &lt;a-input-password v-model:value="editingConfig.api_key" placeholder="输入API Key" /&gt;
          &lt;/a-form-item&gt;
          &lt;a-form-item label="Base URL（可选）"&gt;
            &lt;a-input v-model:value="editingConfig.base_url" placeholder="https://platform.iflow.cn" /&gt;
          &lt;/a-form-item&gt;
          &lt;a-form-item label="设为默认"&gt;
            &lt;a-switch v-model:checked="editingConfig.is_default" /&gt;
          &lt;/a-form-item&gt;
          &lt;a-form-item label="启用"&gt;
            &lt;a-switch v-model:checked="editingConfig.is_active" /&gt;
          &lt;/a-form-item&gt;
        &lt;/a-form&gt;
      &lt;/a-modal&gt;
    &lt;/a-modal&gt;
    &lt;!-- 创建知识库模态框 --&gt;
    &lt;a-modal v-model:open="createColVisible" title="创建知识库" @ok="createCollection"&gt;
      &lt;a-form layout="vertical"&gt;
        &lt;a-form-item label="知识库名称"&gt;
          &lt;a-input v-model:value="newCol.name" placeholder="输入知识库名称" /&gt;
        &lt;/a-form-item&gt;
        &lt;a-form-item label="描述"&gt;
          &lt;a-textarea v-model:value="newCol.description" placeholder="输入描述（可选）" :rows="3" /&gt;
        &lt;/a-form-item&gt;
      &lt;/a-form&gt;
    &lt;/a-modal&gt;
    &lt;!-- 上传文档模态框 --&gt;
    &lt;a-modal v-model:open="uploadVisible" title="上传文档" @ok="uploadVisible = false" width="700px"&gt;
      &lt;a-form layout="vertical"&gt;
        &lt;a-form-item label="选择知识库"&gt;
          &lt;a-select v-model:value="uploadCol" placeholder="请选择要上传到的知识库" style="width:100%"&gt;
            &lt;a-option v-for="c in collections" :key="c.id" :value="c.id"&gt;{{ c.collection_name }}&lt;/a-option&gt;
          &lt;/a-select&gt;
        &lt;/a-form-item&gt;
        &lt;a-form-item label="文档"&gt;
          &lt;a-upload-dragger name="file" :file-list="fileList" :before-upload="beforeUpload" :on-change="handleFileChange" :multiple="true"&gt;
            &lt;p &gt;&lt;InboxOutlined /&gt;&lt;/p&gt;
            &lt;p &gt;点击或拖拽文件到此区域上传&lt;/p&gt;
            &lt;p &gt;支持 PDF、Word、TXT、Markdown、PPT、Excel 等格式&lt;/p&gt;
          &lt;/a-upload-dragger&gt;
        &lt;/a-form-item&gt;
        &lt;a-button type="primary" :loading="uploading" @click="doUpload" block&gt;上传文档&lt;/a-button&gt;
      &lt;/a-form&gt;
    &lt;/a-modal&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
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
const configs = ref&lt;KnowledgeConfig[]&gt;([])
const editConfigVisible = ref(false)
const editingConfig = ref&lt;Partial&lt;KnowledgeConfig&gt;&gt;({})
// 知识库管理
const createColVisible = ref(false)
const colLoading = ref(false)
interface CollectionData { id: string; collection_name: string; collection_description?: string; created_at?: string }
const collections = ref&lt;CollectionData[]&gt;([])
const selectedCol = ref&lt;CollectionData | null&gt;(null)
const newCol = ref({ name: '', description: '' })
// 文档管理
const uploadVisible = ref(false)
const docLoading = ref(false)
interface DocumentData { id: string; name: string; description?: string; summary?: string; status?: string; created_at?: string }
const documents = ref&lt;DocumentData[]&gt;([])
const selCol = ref&lt;string&gt;('')
const uploadCol = ref&lt;string&gt;('')
interface UploadFile { uid: string; name: string; originFileObj?: File; status?: string }
const fileList = ref&lt;UploadFile[]&gt;([])
const uploading = ref(false)
// 搜索
const searchQuery = ref('')
const searchCol = ref&lt;string&gt;('')
const searchLoading = ref(false)
interface SearchResult { score: number; title?: string; source_name?: string; content?: string; text?: string; summary?: string; collection_id?: string }
const searchResults = ref&lt;SearchResult[]&gt;([])
// 格式化日期
const formatDate = (d: string) =&gt; {
  if (!d) return ''
  const dt = new Date(d)
  return `${dt.getFullYear()}-${String(dt.getMonth()+1).padStart(2,'0')}-${String(dt.getDate()).padStart(2,'0')}`
}
const getStatusColor = (status: string) =&gt; {
  const map: Record&lt;string,string&gt; = { processed:'green', processing:'blue', error:'red', failed:'red', ready:'blue' }
  return map[status] || 'default'
}
// 加载配置
const loadConfigs = async () =&gt; {
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
const addNewConfig = () =&gt; {
  editingConfig.value = { config_name:'新配置', is_default:false, is_active:true, source_type:'iflow' }
  editConfigVisible.value = true
}
const editConfig = (cfg: KnowledgeConfig) =&gt; {
  editingConfig.value = { ...cfg }
  editConfigVisible.value = true
}
const deleteConfig = async (id: string) =&gt; {
  try {
    await knowledgeAPI.deleteConfig(id)
    message.success('删除成功')
    loadConfigs()
  } catch (e) {
    message.error('删除失败')
  }
}
const submitConfig = async () =&gt; {
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
const saveConfig = () =&gt; { configVisible.value = false }
// 加载知识库
const loadCollections = async () =&gt; {
  colLoading.value = true
  kbError.value = ''
  try {
    const res = await knowledgeAPI.getCollections()
    if (res?.data?.collections) {
      collections.value = res.data.collections
      if (collections.value.length &amp;&amp; !selectedCol.value) {
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
const selectCollection = (col: CollectionData) =&gt; {
  selectedCol.value = col
  selCol.value = col.id
  activeTab.value = 'documents'
  loadDocuments()
}
const createCollection = async () =&gt; {
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
const loadDocuments = async () =&gt; {
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
const searchDocs = () =&gt; loadDocuments()
const deleteDoc = async (id: string) =&gt; {
  try {
    await knowledgeAPI.deleteDocument(id)
    message.success('删除成功')
    loadDocuments()
  } catch (e) {
    message.error('删除失败')
  }
}
// 上传
const beforeUpload = (file: UploadFile) =&gt; {
  fileList.value = [...fileList.value, file]
  return false
}
const handleFileChange = (info: { fileList: UploadFile[] }) =&gt; {
  fileList.value = info.fileList
}
const doUpload = async () =&gt; {
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
const doSearch = async () =&gt; {
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
onMounted(async () =&gt; {
  await Promise.all([loadConfigs(), loadCollections()])
})
&lt;/script&gt;
&lt;style scoped&gt;
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
&lt;/style&gt;
&nbsp;
&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h1 &gt;记忆检索设置&lt;/h1&gt;
      &lt;p &gt;配置同义词库和语义搜索能力&lt;/p&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;a-tabs v-model:activeKey="activeTab"  size="large"&gt;
        &lt;!-- ===== 同义词库管理 ===== --&gt;
        &lt;a-tab-pane key="synonyms" tab="同义词库"&gt;
          &lt;div &gt;
            &lt;div &gt;
              &lt;div &gt;
                &lt;h3 &gt;同义词词典&lt;/h3&gt;
                &lt;div &gt;
                  &lt;a-button @click="loadSynonyms" :loading="loading"&gt;
                    &lt;ReloadOutlined /&gt; 重新加载
                  &lt;/a-button&gt;
                  &lt;a-button type="primary" @click="saveSynonyms" :loading="saving"&gt;
                    &lt;SaveOutlined /&gt; 保存到文件
                  &lt;/a-button&gt;
                &lt;/div&gt;
              &lt;/div&gt;
              &lt;a-alert
                :message="`共 ${synonymStats.word_count} 个词条，平均 ${synonymStats.average_synonyms} 个同义词`"
                type="info"
                show-icon
                style="margin-bottom: 16px"
              /&gt;
              &lt;div &gt;
                &lt;div  v-for="item in synonymList" :key="item.word"&gt;
                  &lt;div &gt;{{ item.word }}&lt;/div&gt;
                  &lt;div &gt;
                    &lt;a-tag v-for="syn in item.synonyms" :key="syn" closable @close="removeSynonym(item.word, syn)"&gt;
                      {{ syn }}
                    &lt;/a-tag&gt;
                  &lt;/div&gt;
                  &lt;a-button type="link" danger size="small" @click="deleteWord(item.word)"&gt;
                    删除
                  &lt;/a-button&gt;
                &lt;/div&gt;
              &lt;/div&gt;
              &lt;a-divider&gt;添加新词条&lt;/a-divider&gt;
              &lt;a-form layout="inline" @finish="addSynonym"&gt;
                &lt;a-form-item name="word" :rules="[{ required: true, message: '请输入词语' }]"&gt;
                  &lt;a-input v-model:value="newWord" placeholder="词语" style="width: 120px" /&gt;
                &lt;/a-form-item&gt;
                &lt;a-form-item name="synonyms" :rules="[{ required: true, message: '请输入同义词' }]"&gt;
                  &lt;a-select
                    v-model:value="newSynonyms"
                    mode="tags"
                    placeholder="输入同义词后按回车"
                    style="width: 300px"
                    :token-separators="[',', '，']"
                  /&gt;
                &lt;/a-form-item&gt;
                &lt;a-form-item&gt;
                  &lt;a-button type="primary" html-type="submit"&gt;
                    添加
                  &lt;/a-button&gt;
                &lt;/a-form-item&gt;
              &lt;/a-form&gt;
            &lt;/div&gt;
          &lt;/div&gt;
        &lt;/a-tab-pane&gt;
        &lt;!-- ===== LLM配置 ===== --&gt;
        &lt;a-tab-pane key="llm-config" tab="LLM 配置"&gt;
          &lt;div &gt;
            &lt;div &gt;
              &lt;h3 &gt;向量语义增强&lt;/h3&gt;
              &lt;p &gt;
                当同义词库无法覆盖时，使用LLM进行语义扩展，提升记忆检索的准确性
              &lt;/p&gt;
              &lt;div &gt;
                &lt;div &gt;
                  &lt;div &gt;
                    &lt;span &gt;启用LLM增强&lt;/span&gt;
                    &lt;span &gt;当同义词库无法覆盖时，调用LLM进行语义扩展&lt;/span&gt;
                  &lt;/div&gt;
                  &lt;a-switch v-model:checked="llmConfig.enable_llm_fallback" @change="saveLLMConfig" /&gt;
                &lt;/div&gt;
              &lt;/div&gt;
              &lt;a-divider /&gt;
              &lt;a-form layout="vertical" &gt;
                &lt;a-row :gutter="24"&gt;
                  &lt;a-col :span="12"&gt;
                    &lt;a-form-item label="API提供商"&gt;
                      &lt;a-select v-model:value="llmConfig.llm_provider" @change="saveLLMConfig"&gt;
                        &lt;a-select-option value="openai"&gt;OpenAI&lt;/a-select-option&gt;
                        &lt;a-select-option value="azure"&gt;Azure OpenAI&lt;/a-select-option&gt;
                        &lt;a-select-option value="anthropic"&gt;Anthropic&lt;/a-select-option&gt;
                        &lt;a-select-option value="ollama"&gt;Ollama (本地)&lt;/a-select-option&gt;
                        &lt;a-select-option value="custom"&gt;自定义&lt;/a-select-option&gt;
                      &lt;/a-select&gt;
                    &lt;/a-form-item&gt;
                  &lt;/a-col&gt;
                  &lt;a-col :span="12"&gt;
                    &lt;a-form-item label="模型ID"&gt;
                      &lt;a-input
                        v-model:value="llmConfig.llm_model_id"
                        placeholder="text-embedding-3-small"
                        @change="saveLLMConfig"
                      /&gt;
                    &lt;/a-form-item&gt;
                  &lt;/a-col&gt;
                &lt;/a-row&gt;
                &lt;a-form-item label="API地址"&gt;
                  &lt;a-input
                    v-model:value="llmConfig.llm_api_url"
                    placeholder="https://api.openai.com/v1"
                    @change="saveLLMConfig"
                  /&gt;
                &lt;/a-form-item&gt;
                &lt;a-form-item label="API密钥"&gt;
                  &lt;a-input-password
                    v-model:value="llmConfig.llm_api_key"
                    placeholder="sk-..."
                    @change="saveLLMConfig"
                  /&gt;
                &lt;/a-form-item&gt;
                &lt;a-row :gutter="24"&gt;
                  &lt;a-col :span="12"&gt;
                    &lt;a-form-item label="Temperature"&gt;
                      &lt;a-slider
                        v-model:value="llmConfig.llm_temperature"
                        :min="0"
                        :max="1"
                        :step="0.1"
                        @change="saveLLMConfig"
                      /&gt;
                      &lt;span &gt;{{ llmConfig.llm_temperature }}&lt;/span&gt;
                    &lt;/a-form-item&gt;
                  &lt;/a-col&gt;
                  &lt;a-col :span="12"&gt;
                    &lt;a-form-item label="最大Token数"&gt;
                      &lt;a-input-number
                        v-model:value="llmConfig.llm_max_tokens"
                        :min="100"
                        :max="4000"
                        style="width: 100%"
                        @change="saveLLMConfig"
                      /&gt;
                    &lt;/a-form-item&gt;
                  &lt;/a-col&gt;
                &lt;/a-row&gt;
              &lt;/a-form&gt;
            &lt;/div&gt;
            &lt;!-- 测试区域 --&gt;
            &lt;div &gt;
              &lt;h3 &gt;语义搜索测试&lt;/h3&gt;
              &lt;a-form layout="inline" @finish="testSearch"&gt;
                &lt;a-form-item name="query" style="flex: 1"&gt;
                  &lt;a-input
                    v-model:value="testQuery"
                    placeholder="输入查询词测试语义扩展效果，如：宠物、开心..."
                  /&gt;
                &lt;/a-form-item&gt;
                &lt;a-form-item&gt;
                  &lt;a-button type="primary" html-type="submit" :loading="testing"&gt;
                    测试
                  &lt;/a-button&gt;
                &lt;/a-form-item&gt;
              &lt;/a-form&gt;
              &lt;div v-if="testResult" &gt;
                &lt;a-descriptions :column="1" bordered size="small"&gt;
                  &lt;a-descriptions-item label="原始查询"&gt;
                    &lt;code&gt;{{ testResult.original_query }}&lt;/code&gt;
                  &lt;/a-descriptions-item&gt;
                  &lt;a-descriptions-item label="扩展查询"&gt;
                    &lt;code&gt;{{ testResult.expanded_query }}&lt;/code&gt;
                  &lt;/a-descriptions-item&gt;
                  &lt;a-descriptions-item label="使用的同义词"&gt;
                    &lt;a-tag v-for="syn in testResult.synonyms_used" :key="syn" color="blue"&gt;
                      {{ syn }}
                    &lt;/a-tag&gt;
                    &lt;span v-if="testResult.synonyms_used.length === 0"&gt;无&lt;/span&gt;
                  &lt;/a-descriptions-item&gt;
                  &lt;a-descriptions-item label="LLM增强"&gt;
                    &lt;a-tag :color="testResult.llm_enhanced ? 'green' : 'default'"&gt;
                      {{ testResult.llm_enhanced ? '已启用' : '未启用' }}
                    &lt;/a-tag&gt;
                  &lt;/a-descriptions-item&gt;
                &lt;/a-descriptions&gt;
              &lt;/div&gt;
            &lt;/div&gt;
          &lt;/div&gt;
        &lt;/a-tab-pane&gt;
        &lt;!-- ===== 向量搜索配置 ===== --&gt;
        &lt;a-tab-pane key="vector-config" tab="向量搜索"&gt;
          &lt;div &gt;
            &lt;div &gt;
              &lt;h3 &gt;向量搜索后端&lt;/h3&gt;
              &lt;p &gt;选择记忆检索使用的向量搜索引擎&lt;/p&gt;
              &lt;div &gt;
                &lt;div
                  :
                &gt;
                  &lt;div &gt;
                    &lt;span &gt;TF-IDF (默认)&lt;/span&gt;
                    &lt;span &gt;轻量级，无需额外依赖，适合中小规模数据&lt;/span&gt;
                  &lt;/div&gt;
                  &lt;a-tag color="green"&gt;可用&lt;/a-tag&gt;
                &lt;/div&gt;
                &lt;div
                  :
                &gt;
                  &lt;div &gt;
                    &lt;span &gt;FAISS&lt;/span&gt;
                    &lt;span &gt;Facebook开源，高性能，适合大规模向量检索&lt;/span&gt;
                  &lt;/div&gt;
                  &lt;a-tag :color="availableBackends.faiss ? 'green' : 'default'"&gt;
                    {{ availableBackends.faiss ? '可用' : '不可用' }}
                  &lt;/a-tag&gt;
                &lt;/div&gt;
                &lt;div
                  :
                &gt;
                  &lt;div &gt;
                    &lt;span &gt;ChromaDB&lt;/span&gt;
                    &lt;span &gt;轻量级向量数据库，支持持久化&lt;/span&gt;
                  &lt;/div&gt;
                  &lt;a-tag :color="availableBackends.chromadb ? 'green' : 'default'"&gt;
                    {{ availableBackends.chromadb ? '可用' : '不可用' }}
                  &lt;/a-tag&gt;
                &lt;/div&gt;
              &lt;/div&gt;
            &lt;/div&gt;
          &lt;/div&gt;
        &lt;/a-tab-pane&gt;
      &lt;/a-tabs&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref, reactive, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import {
  ReloadOutlined,
  SaveOutlined,
} from '@ant-design/icons-vue'
import { synonymAPI, type SynonymWord, type SynonymStats, type SynonymConfig, type SemanticSearchResult } from '@/api/modules/synonym'
const activeTab = ref('synonyms')
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
// 同义词库数据
const synonymStats = reactive&lt;SynonymStats&gt;({
  word_count: 0,
  total_synonyms: 0,
  average_synonyms: 0,
  file_path: ''
})
const synonymList = ref&lt;SynonymWord[]&gt;([])
const newWord = ref('')
const newSynonyms = ref&lt;string[]&gt;([])
// LLM配置
const llmConfig = reactive&lt;SynonymConfig&gt;({
  enable_llm_fallback: false,
  llm_provider: 'openai',
  llm_api_url: '',
  llm_api_key: '',
  llm_model_id: 'text-embedding-3-small',
  llm_temperature: 0.7,
  llm_max_tokens: 1000
})
// 向量搜索后端
const availableBackends = reactive({
  tfidf: true,
  faiss: false,
  chromadb: false
})
// 测试结果
const testQuery = ref('')
const testResult = ref&lt;SemanticSearchResult | null&gt;(null)
// 加载同义词库
async function loadSynonyms() {
  loading.value = true
  try {
    const [statsRes, listRes] = await Promise.all([
      synonymAPI.getStats(),
      synonymAPI.getAll()
    ])
    if (statsRes.data) {
      Object.assign(synonymStats, statsRes.data)
    }
    if (listRes.data) {
      synonymList.value = listRes.data.words
    }
    message.success('同义词库已重新加载')
  } catch (err: unknown) {
    const e = err as { message?: string }
    message.error('加载失败: ' + (e.message || '未知错误'))
  } finally {
    loading.value = false
  }
}
// 保存同义词库
async function saveSynonyms() {
  saving.value = true
  try {
    await synonymAPI.saveToFile()
    message.success('同义词库已保存到文件')
  } catch (err: unknown) {
    const e = err as { message?: string }
    message.error('保存失败: ' + (e.message || '未知错误'))
  } finally {
    saving.value = false
  }
}
// 添加同义词
async function addSynonym() {
  if (!newWord.value.trim()) {
    message.warning('请输入词语')
    return
  }
  if (newSynonyms.value.length === 0) {
    message.warning('请输入至少一个同义词')
    return
  }
  try {
    await synonymAPI.addSynonyms({
      word: newWord.value,
      synonyms: newSynonyms.value
    })
    message.success('添加成功')
    newWord.value = ''
    newSynonyms.value = []
    await loadSynonyms()
  } catch (err: unknown) {
    const e = err as { message?: string }
    message.error('添加失败: ' + (e.message || '未知错误'))
  }
}
// 移除同义词
async function removeSynonym(word: string, synonym: string) {
  try {
    await synonymAPI.removeSynonym(word, synonym)
    message.success('已移除')
    await loadSynonyms()
  } catch (err: unknown) {
    const e = err as { message?: string }
    message.error('移除失败: ' + (e.message || '未知错误'))
  }
}
// 删除词条
async function deleteWord(word: string) {
  try {
    await synonymAPI.deleteWord(word)
    message.success('已删除')
    await loadSynonyms()
  } catch (err: unknown) {
    const e = err as { message?: string }
    message.error('删除失败: ' + (e.message || '未知错误'))
  }
}
// 保存LLM配置
async function saveLLMConfig() {
  try {
    await synonymAPI.setLLMConfig(llmConfig)
    message.success('LLM配置已保存')
  } catch (err: unknown) {
    const e = err as { message?: string }
    message.error('保存失败: ' + (e.message || '未知错误'))
  }
}
// 测试语义搜索
async function testSearch() {
  if (!testQuery.value.trim()) {
    message.warning('请输入查询词')
    return
  }
  testing.value = true
  try {
    const res = await synonymAPI.testSemanticSearch(testQuery.value)
    if (res.data) {
      testResult.value = res.data
    }
  } catch (err: unknown) {
    const e = err as { message?: string }
    message.error('测试失败: ' + (e.message || '未知错误'))
    testResult.value = null
  } finally {
    testing.value = false
  }
}
// 初始化
onMounted(async () =&gt; {
  await loadSynonyms()
  try {
    const configRes = await synonymAPI.getLLMConfig()
    if (configRes.data) {
      Object.assign(llmConfig, configRes.data)
      // 移除密钥的掩码以便编辑
      if (llmConfig.llm_api_key?.startsWith('***')) {
        llmConfig.llm_api_key = ''
      }
    }
  } catch (err) {
    console.error('加载LLM配置失败:', err)
  }
})
&lt;/script&gt;
&lt;style scoped&gt;
.memory-search-settings {
  padding: 24px 28px;
  max-width: 960px;
}
.settings-header {
  margin-bottom: 20px;
}
.page-title {
  font-size: 1.5rem;
  font-weight: 700;
  color: #e2e8f0;
  margin: 0 0 4px;
}
.page-sub {
  color: rgba(255, 255, 255, 0.4);
  font-size: 0.9rem;
  margin: 0;
}
.tab-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.section {
  padding: 24px 28px;
}
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.section-title {
  font-size: 1.05rem;
  font-weight: 600;
  color: #e2e8f0;
  margin: 0;
}
.section-desc {
  color: rgba(255, 255, 255, 0.4);
  font-size: 0.85rem;
  margin: -12px 0 16px;
}
.section-actions {
  display: flex;
  gap: 8px;
}
.synonym-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 400px;
  overflow-y: auto;
  margin-bottom: 16px;
}
.synonym-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 8px;
}
.synonym-word {
  font-weight: 500;
  color: #e2e8f0;
  min-width: 80px;
}
.synonym-tags {
  flex: 1;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.llm-form {
  max-width: 600px;
}
.slider-value {
  margin-left: 12px;
  color: #60a5fa;
}
.test-result {
  margin-top: 16px;
}
.test-result code {
  background: rgba(96, 165, 250, 0.1);
  padding: 2px 6px;
  border-radius: 4px;
  color: #60a5fa;
}
.backend-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.backend-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 8px;
}
.backend-item.active {
  border-color: rgba(96, 165, 250, 0.3);
  background: rgba(96, 165, 250, 0.05);
}
.backend-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.backend-name {
  font-weight: 500;
  color: #e2e8f0;
}
.backend-desc {
  font-size: 0.8rem;
  color: rgba(255, 255, 255, 0.4);
}
/* 深色主题适配 */
:deep(.ant-tabs-nav) {
  margin-bottom: 20px;
}
:deep(.ant-tabs-tab) {
  color: rgba(255, 255, 255, 0.5) !important;
}
:deep(.ant-tabs-tab-active) {
  color: #93c5fd !important;
}
:deep(.ant-tabs-ink-bar) {
  background: #60a5fa;
}
:deep(.ant-input),
:deep(.ant-input-number),
:deep(.ant-select-selector) {
  background: rgba(255, 255, 255, 0.05) !important;
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
  color: #e2e8f0 !important;
}
:deep(.ant-form-item-label &gt; label) {
  color: rgba(255, 255, 255, 0.6) !important;
}
:deep(.ant-divider) {
  border-color: rgba(255, 255, 255, 0.06);
}
:deep(.ant-descriptions-item-label) {
  color: rgba(255, 255, 255, 0.5);
}
:deep(.ant-descriptions-item-content) {
  color: #e2e8f0;
}
&lt;/style&gt;
&nbsp;
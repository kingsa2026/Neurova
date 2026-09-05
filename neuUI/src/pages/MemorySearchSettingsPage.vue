<template>
  <div class="memory-search-settings">
    <div class="settings-header">
      <h1 class="page-title">记忆检索设置</h1>
      <p class="page-sub">配置同义词库和语义搜索能力</p>
    </div>

    <div class="settings-body">
      <a-tabs v-model:activeKey="activeTab" class="settings-tabs" size="large">
        <!-- ===== 同义词库管理 ===== -->
        <a-tab-pane key="synonyms" tab="同义词库">
          <div class="tab-content">
            <div class="section glass-effect">
              <div class="section-header">
                <h3 class="section-title">同义词词典</h3>
                <div class="section-actions">
                  <a-button @click="loadSynonyms" :loading="loading">
                    <ReloadOutlined /> 重新加载
                  </a-button>
                  <a-button type="primary" @click="saveSynonyms" :loading="saving">
                    <SaveOutlined /> 保存到文件
                  </a-button>
                </div>
              </div>

              <a-alert
                :message="`共 ${synonymStats.word_count} 个词条，平均 ${synonymStats.average_synonyms} 个同义词`"
                type="info"
                show-icon
                style="margin-bottom: 16px"
              />

              <div class="synonym-list">
                <div class="synonym-item" v-for="item in synonymList" :key="item.word">
                  <div class="synonym-word">{{ item.word }}</div>
                  <div class="synonym-tags">
                    <a-tag v-for="syn in item.synonyms" :key="syn" closable @close="removeSynonym(item.word, syn)">
                      {{ syn }}
                    </a-tag>
                  </div>
                  <a-button type="link" danger size="small" @click="deleteWord(item.word)">
                    删除
                  </a-button>
                </div>
              </div>

              <a-divider>添加新词条</a-divider>

              <a-form layout="inline" @finish="addSynonym">
                <a-form-item name="word" :rules="[{ required: true, message: '请输入词语' }]">
                  <a-input v-model:value="newWord" placeholder="词语" style="width: 120px" />
                </a-form-item>
                <a-form-item name="synonyms" :rules="[{ required: true, message: '请输入同义词' }]">
                  <a-select
                    v-model:value="newSynonyms"
                    mode="tags"
                    placeholder="输入同义词后按回车"
                    style="width: 300px"
                    :token-separators="[',', '，']"
                  />
                </a-form-item>
                <a-form-item>
                  <a-button type="primary" html-type="submit">
                    添加
                  </a-button>
                </a-form-item>
              </a-form>
            </div>
          </div>
        </a-tab-pane>

        <!-- ===== LLM配置 ===== -->
        <a-tab-pane key="llm-config" tab="LLM 配置">
          <div class="tab-content">
            <div class="section glass-effect">
              <h3 class="section-title">向量语义增强</h3>
              <p class="section-desc">
                当同义词库无法覆盖时，使用LLM进行语义扩展，提升记忆检索的准确性
              </p>

              <div class="pref-list">
                <div class="pref-item">
                  <div class="pref-info">
                    <span class="pref-label">启用LLM增强</span>
                    <span class="pref-desc">当同义词库无法覆盖时，调用LLM进行语义扩展</span>
                  </div>
                  <a-switch v-model:checked="llmConfig.enable_llm_fallback" @change="saveLLMConfig" />
                </div>
              </div>

              <a-divider />

              <a-form layout="vertical" class="llm-form">
                <a-row :gutter="24">
                  <a-col :span="12">
                    <a-form-item label="API提供商">
                      <a-select v-model:value="llmConfig.llm_provider" @change="saveLLMConfig">
                        <a-select-option value="openai">OpenAI</a-select-option>
                        <a-select-option value="azure">Azure OpenAI</a-select-option>
                        <a-select-option value="anthropic">Anthropic</a-select-option>
                        <a-select-option value="ollama">Ollama (本地)</a-select-option>
                        <a-select-option value="custom">自定义</a-select-option>
                      </a-select>
                    </a-form-item>
                  </a-col>
                  <a-col :span="12">
                    <a-form-item label="模型ID">
                      <a-input
                        v-model:value="llmConfig.llm_model_id"
                        placeholder="text-embedding-3-small"
                        @change="saveLLMConfig"
                      />
                    </a-form-item>
                  </a-col>
                </a-row>

                <a-form-item label="API地址">
                  <a-input
                    v-model:value="llmConfig.llm_api_url"
                    placeholder="https://api.openai.com/v1"
                    @change="saveLLMConfig"
                  />
                </a-form-item>

                <a-form-item label="API密钥">
                  <a-input-password
                    v-model:value="llmConfig.llm_api_key"
                    placeholder="sk-..."
                    @change="saveLLMConfig"
                  />
                </a-form-item>

                <a-row :gutter="24">
                  <a-col :span="12">
                    <a-form-item label="Temperature">
                      <a-slider
                        v-model:value="llmConfig.llm_temperature"
                        :min="0"
                        :max="1"
                        :step="0.1"
                        @change="saveLLMConfig"
                      />
                      <span class="slider-value">{{ llmConfig.llm_temperature }}</span>
                    </a-form-item>
                  </a-col>
                  <a-col :span="12">
                    <a-form-item label="最大Token数">
                      <a-input-number
                        v-model:value="llmConfig.llm_max_tokens"
                        :min="100"
                        :max="4000"
                        style="width: 100%"
                        @change="saveLLMConfig"
                      />
                    </a-form-item>
                  </a-col>
                </a-row>
              </a-form>
            </div>

            <!-- 测试区域 -->
            <div class="section glass-effect">
              <h3 class="section-title">语义搜索测试</h3>
              <a-form layout="inline" @finish="testSearch">
                <a-form-item name="query" style="flex: 1">
                  <a-input
                    v-model:value="testQuery"
                    placeholder="输入查询词测试语义扩展效果，如：宠物、开心..."
                  />
                </a-form-item>
                <a-form-item>
                  <a-button type="primary" html-type="submit" :loading="testing">
                    测试
                  </a-button>
                </a-form-item>
              </a-form>

              <div v-if="testResult" class="test-result">
                <a-descriptions :column="1" bordered size="small">
                  <a-descriptions-item label="原始查询">
                    <code>{{ testResult.original_query }}</code>
                  </a-descriptions-item>
                  <a-descriptions-item label="扩展查询">
                    <code>{{ testResult.expanded_query }}</code>
                  </a-descriptions-item>
                  <a-descriptions-item label="使用的同义词">
                    <a-tag v-for="syn in testResult.synonyms_used" :key="syn" color="blue">
                      {{ syn }}
                    </a-tag>
                    <span v-if="testResult.synonyms_used.length === 0">无</span>
                  </a-descriptions-item>
                  <a-descriptions-item label="LLM增强">
                    <a-tag :color="testResult.llm_enhanced ? 'green' : 'default'">
                      {{ testResult.llm_enhanced ? '已启用' : '未启用' }}
                    </a-tag>
                  </a-descriptions-item>
                </a-descriptions>
              </div>
            </div>
          </div>
        </a-tab-pane>

        <!-- ===== 向量搜索配置 ===== -->
        <a-tab-pane key="vector-config" tab="向量搜索">
          <div class="tab-content">
            <div class="section glass-effect">
              <h3 class="section-title">向量搜索后端</h3>
              <p class="section-desc">选择记忆检索使用的向量搜索引擎</p>

              <div class="backend-list">
                <div
                  class="backend-item"
                  :class="{ active: availableBackends.tfidf }"
                >
                  <div class="backend-info">
                    <span class="backend-name">TF-IDF (默认)</span>
                    <span class="backend-desc">轻量级，无需额外依赖，适合中小规模数据</span>
                  </div>
                  <a-tag color="green">可用</a-tag>
                </div>
                <div
                  class="backend-item"
                  :class="{ active: availableBackends.faiss }"
                >
                  <div class="backend-info">
                    <span class="backend-name">FAISS</span>
                    <span class="backend-desc">Facebook开源，高性能，适合大规模向量检索</span>
                  </div>
                  <a-tag :color="availableBackends.faiss ? 'green' : 'default'">
                    {{ availableBackends.faiss ? '可用' : '不可用' }}
                  </a-tag>
                </div>
                <div
                  class="backend-item"
                  :class="{ active: availableBackends.chromadb }"
                >
                  <div class="backend-info">
                    <span class="backend-name">ChromaDB</span>
                    <span class="backend-desc">轻量级向量数据库，支持持久化</span>
                  </div>
                  <a-tag :color="availableBackends.chromadb ? 'green' : 'default'">
                    {{ availableBackends.chromadb ? '可用' : '不可用' }}
                  </a-tag>
                </div>
              </div>
            </div>
          </div>
        </a-tab-pane>
      </a-tabs>
    </div>
  </div>
</template>

<script setup lang="ts">
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
const synonymStats = reactive<SynonymStats>({
  word_count: 0,
  total_synonyms: 0,
  average_synonyms: 0,
  file_path: ''
})
const synonymList = ref<SynonymWord[]>([])
const newWord = ref('')
const newSynonyms = ref<string[]>([])

// LLM配置
const llmConfig = reactive<SynonymConfig>({
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
const testResult = ref<SemanticSearchResult | null>(null)

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
onMounted(async () => {
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
</script>

<style scoped>
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
:deep(.ant-form-item-label > label) {
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
</style>

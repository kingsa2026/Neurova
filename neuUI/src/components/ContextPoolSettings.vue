<template>
  <div class="context-pool-settings">
    <!-- 池参数配置 -->
    <div class="section">
      <h3 class="section-title">上下文池参数</h3>
      <div class="pref-list">
        <div class="pref-item">
          <div class="pref-info">
            <span class="pref-label">最大池大小</span>
            <span class="pref-desc">上下文池中最多保留的上下文数量（超出时自动移除最旧的）</span>
          </div>
          <a-input-number
            v-model:value="settings.max_size"
            :min="10"
            :max="1000"
            :step="10"
            style="width: 140px"
            addon-after="条"
          />
        </div>
        <div class="pref-item">
          <div class="pref-info">
            <span class="pref-label">TTL 过期时间</span>
            <span class="pref-desc">上下文在此时间后自动过期，过期内容会被定期清理</span>
          </div>
          <a-input-number
            v-model:value="settings.ttl_seconds"
            :min="60"
            :max="86400"
            :step="60"
            style="width: 160px"
            addon-after="秒"
          />
        </div>
        <div class="pref-item">
          <div class="pref-info">
            <span class="pref-label">默认 Token 预算</span>
            <span class="pref-desc">未匹配到预设模型时使用的默认 Token 上限</span>
          </div>
          <a-input-number
            v-model:value="settings.default_token_budget"
            :min="1000"
            :max="200000"
            :step="1000"
            style="width: 160px"
            addon-after="tokens"
          />
        </div>
      </div>
      <a-form-item style="margin-top: 20px">
        <a-button type="primary" :loading="saving" @click="saveSettings">
          保存池设置
        </a-button>
      </a-form-item>
    </div>

    <!-- 模型预算预设 -->
    <div class="section">
      <h3 class="section-title">模型 Token 预算预设</h3>
      <p class="section-desc">不同模型自动分配的 Token 预算上限，基于模型名称前缀匹配</p>
      <a-table
        :columns="budgetColumns"
        :data-source="budgetList"
        :pagination="false"
        size="small"
        row-key="model"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'budget'">
            <a-input-number
              v-model:value="record.budget"
              :min="1000"
              :max="500000"
              :step="1000"
              size="small"
              style="width: 130px"
              @change="onBudgetChange(record.model, $event)"
            />
          </template>
          <template v-if="column.key === 'action'">
            <a-button type="link" danger size="small" @click="removeBudget(record.model)">
              移除
            </a-button>
          </template>
        </template>
      </a-table>
      <div style="margin-top: 12px; display: flex; gap: 8px">
        <a-input
          v-model:value="newModelName"
          placeholder="模型名称（如 gpt-4o）"
          style="width: 200px"
          size="small"
        />
        <a-input-number
          v-model:value="newModelBudget"
          :min="1000"
          :max="500000"
          :step="1000"
          placeholder="预算"
          style="width: 130px"
          size="small"
        />
        <a-button size="small" @click="addBudget" :disabled="!newModelName">
          添加
        </a-button>
      </div>
    </div>

    <!-- Token 预算计算器 -->
    <div class="section">
      <h3 class="section-title">Token 预算计算器</h3>
      <p class="section-desc">输入模型名称，测试系统将分配多少 Token 预算</p>
      <div style="display: flex; gap: 12px; align-items: flex-start">
        <a-input
          v-model:value="testModelName"
          placeholder="输入模型名称，如 claude-3-opus"
          style="width: 280px"
          @press-enter="testBudget"
        />
        <a-button type="primary" :loading="testing" @click="testBudget">
          计算
        </a-button>
      </div>
      <div v-if="testResult" class="test-result">
        <a-descriptions size="small" :column="1" bordered>
          <a-descriptions-item label="模型名称">{{ testResult.model_name }}</a-descriptions-item>
          <a-descriptions-item label="计算预算">
            <a-tag color="blue">{{ testResult.calculated_budget.toLocaleString() }} tokens</a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="说明">{{ testResult.explanation }}</a-descriptions-item>
        </a-descriptions>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { contextPoolAPI, type PoolSettings } from '@/api/modules/context-pool'

// ─── 池设置 ───
const settings = reactive<PoolSettings>({
  max_size: 100,
  ttl_seconds: 3600,
  default_token_budget: 16000,
  model_budgets: {},
})
const saving = ref(false)

// ─── 预算表格 ───
const budgetColumns = [
  { title: '模型', dataIndex: 'model', key: 'model', width: 200 },
  { title: 'Token 预算', key: 'budget', width: 160 },
  { title: '操作', key: 'action', width: 80 },
]
const budgetList = ref<Array<{ model: string; budget: number }>>([])
const newModelName = ref('')
const newModelBudget = ref(32000)

// ─── 测试计算器 ───
const testModelName = ref('')
const testing = ref(false)
const testResult = ref<{ model_name: string; calculated_budget: number; explanation: string } | null>(null)

// ─── 加载设置 ───
async function loadSettings() {
  try {
    const res = await contextPoolAPI.getSettings()
    if (res?.data) {
      Object.assign(settings, res.data)
      syncBudgetList()
    }
  } catch (err) {
    console.error('Failed to load context pool settings:', err)
  }
}

function syncBudgetList() {
  budgetList.value = Object.entries(settings.model_budgets).map(([model, budget]) => ({
    model,
    budget,
  }))
}

// ─── 保存设置 ───
async function saveSettings() {
  saving.value = true
  try {
    await contextPoolAPI.updateSettings({
      max_size: settings.max_size,
      ttl_seconds: settings.ttl_seconds,
      default_token_budget: settings.default_token_budget,
    })
    message.success('上下文池设置已保存')
  } catch (err: unknown) {
    const e = err as { response?: { data?: { detail?: string } } }
    message.error(e.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

// ─── 预算管理 ───
function onBudgetChange(model: string, value: number | null) {
  if (value !== null) {
    settings.model_budgets[model] = value
  }
}

function addBudget() {
  if (!newModelName.value.trim()) return
  settings.model_budgets[newModelName.value.trim()] = newModelBudget.value
  syncBudgetList()
  newModelName.value = ''
  newModelBudget.value = 32000
}

function removeBudget(model: string) {
  delete settings.model_budgets[model]
  syncBudgetList()
}

// ─── 测试预算 ───
async function testBudget() {
  if (!testModelName.value.trim()) return
  testing.value = true
  testResult.value = null
  try {
    const res = await contextPoolAPI.testBudget({
      model_name: testModelName.value.trim(),
    })
    if (res?.data) {
      testResult.value = res.data
    }
  } catch (err: unknown) {
    const e = err as { response?: { data?: { detail?: string } } }
    message.error(e.response?.data?.detail || '计算失败')
  } finally {
    testing.value = false
  }
}

// ─── 初始化 ───
onMounted(() => {
  loadSettings()
})
</script>

<style scoped>
.context-pool-settings {
  display: flex;
  flex-direction: column;
  gap: 24px;
}
.section {
  padding: 24px 28px;
  background: rgba(255, 255, 255, 0.02);
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.06);
}
.section-title {
  font-size: 1.05rem;
  font-weight: 600;
  color: #e2e8f0;
  margin: 0 0 8px;
}
.section-desc {
  color: rgba(255, 255, 255, 0.4);
  font-size: 0.85rem;
  margin: 0 0 16px;
}
.pref-list {
  display: flex;
  flex-direction: column;
  gap: 0;
}
.pref-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}
.pref-item:last-child {
  border-bottom: none;
}
.pref-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.pref-label {
  color: #e2e8f0;
  font-size: 0.9rem;
}
.pref-desc {
  color: rgba(255, 255, 255, 0.35);
  font-size: 0.78rem;
}
.test-result {
  margin-top: 16px;
  max-width: 400px;
}
</style>

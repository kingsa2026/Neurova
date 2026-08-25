<template>
  <div class="neuron-page">
    <div class="page-header">
      <h1>NEURON 记忆系统</h1>
      <p class="subtitle">依赖图谱 · 级联推理 · 缺失检测</p>
    </div>

    <!-- 统计卡片 -->
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-value">{{ stats.total_entities || 0 }}</div>
        <div class="stat-label">实体数量</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ stats.total_edges || 0 }}</div>
        <div class="stat-label">依赖关系</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ stats.entity_types || 0 }}</div>
        <div class="stat-label">实体类型</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ healthStatus === 'healthy' ? '正常' : '异常' }}</div>
        <div class="stat-label">系统状态</div>
      </div>
    </div>

    <!-- 功能标签页 -->
    <div class="tabs">
      <button 
        v-for="tab in tabs" 
        :key="tab.key"
        :class="['tab', { active: activeTab === tab.key }]"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- 依赖图谱 -->
    <div v-show="activeTab === 'graph'" class="tab-content">
      <div class="section">
        <h3>实体列表</h3>
        <div class="entity-list">
          <div v-for="entity in entities" :key="entity.id" class="entity-item">
            <span class="entity-type">{{ entity.entity_type }}</span>
            <span class="entity-name">{{ entity.name }}</span>
            <button class="btn-sm" @click="showDependencies(entity.id)">查看依赖</button>
          </div>
          <div v-if="entities.length === 0" class="empty-state">
            暂无实体数据
          </div>
        </div>
      </div>

      <div class="section">
        <h3>依赖关系</h3>
        <div v-if="selectedEntity" class="dependency-view">
          <p>实体: <strong>{{ selectedEntity }}</strong></p>
          <div class="dep-list">
            <div v-if="dependencies.downstream.length > 0">
              <h4>下游依赖 ({{ dependencies.downstream.length }})</h4>
              <div v-for="dep in dependencies.downstream" :key="dep" class="dep-item downstream">
                → {{ dep }}
              </div>
            </div>
            <div v-if="dependencies.upstream.length > 0">
              <h4>上游依赖 ({{ dependencies.upstream.length }})</h4>
              <div v-for="dep in dependencies.upstream" :key="dep" class="dep-item upstream">
                ← {{ dep }}
              </div>
            </div>
            <div v-if="dependencies.downstream.length === 0 && dependencies.upstream.length === 0" class="empty-state">
              无依赖关系
            </div>
          </div>
        </div>
        <div v-else class="empty-state">
          请先选择一个实体查看依赖
        </div>
      </div>
    </div>

    <!-- 级联推理 -->
    <div v-show="activeTab === 'cascade'" class="tab-content">
      <div class="section">
        <h3>级联推理</h3>
        <div class="form-group">
          <label>实体ID</label>
          <input v-model="cascadeForm.entityId" placeholder="输入实体ID" />
        </div>
        <div class="form-group">
          <label>方向</label>
          <select v-model="cascadeForm.direction">
            <option value="forward">正向 (A变化→影响B)</option>
            <option value="backward">反向 (B变化←受A影响)</option>
          </select>
        </div>
        <div class="form-group">
          <label>最大深度</label>
          <input v-model.number="cascadeForm.maxDepth" type="number" min="1" max="10" />
        </div>
        <button class="btn-primary" @click="runCascade" :disabled="cascadeLoading">
          {{ cascadeLoading ? '推理中...' : '执行推理' }}
        </button>

        <div v-if="cascadeResult" class="result-panel">
          <h4>推理结果</h4>
          <p>影响实体数: <strong>{{ cascadeResult.total_affected }}</strong></p>
          <p>置信度: <strong>{{ (cascadeResult.confidence * 100).toFixed(1) }}%</strong></p>
          <div class="effects-list">
            <div v-for="(effect, idx) in cascadeResult.effects" :key="idx" class="effect-item">
              <span class="effect-type">{{ effect.effect_type }}</span>
              <span class="effect-id">{{ effect.entity_id }}</span>
              <span class="effect-conf">{{ (effect.confidence * 100).toFixed(1) }}%</span>
            </div>
          </div>
          <div class="reasoning-chain">
            <h4>推理链</h4>
            <div v-for="(line, idx) in cascadeResult.reasoning_chain" :key="idx" class="chain-line">
              {{ line }}
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 缺失检测 -->
    <div v-show="activeTab === 'absence'" class="tab-content">
      <div class="section">
        <h3>缺失检测</h3>
        <div class="form-group">
          <label>期望实体</label>
          <input v-model="absenceForm.expectedEntity" placeholder="输入期望存在的实体" />
        </div>
        <div class="form-group">
          <label>期望关系</label>
          <select v-model="absenceForm.expectedRelation">
            <option value="causal">因果 (causal)</option>
            <option value="temporal">时间 (temporal)</option>
            <option value="conditional">条件 (conditional)</option>
            <option value="prerequisite">前提 (prerequisite)</option>
            <option value="support">支持 (support)</option>
            <option value="hierarchical">层级 (hierarchical)</option>
          </select>
        </div>
        <div class="form-group">
          <label>上下文实体 (逗号分隔)</label>
          <input v-model="absenceForm.contextEntities" placeholder="实体1, 实体2, ..." />
        </div>
        <button class="btn-primary" @click="runAbsenceCheck" :disabled="absenceLoading">
          {{ absenceLoading ? '检测中...' : '执行检测' }}
        </button>

        <div v-if="absenceResult" class="result-panel">
          <h4>检测结果</h4>
          <div :class="['status-badge', absenceResult.is_absent ? 'absent' : 'present']">
            {{ absenceResult.is_absent ? '检测到缺失' : '未检测到缺失' }}
          </div>
          <div class="check-results">
            <div class="check-item">
              <span>实体存在:</span>
              <span :class="absenceResult.entity_exists ? 'ok' : 'fail'">
                {{ absenceResult.entity_exists ? '✓' : '✗' }}
              </span>
            </div>
            <div class="check-item">
              <span>关系存在:</span>
              <span :class="absenceResult.relation_exists ? 'ok' : 'fail'">
                {{ absenceResult.relation_exists ? '✓' : '✗' }}
              </span>
            </div>
            <div class="check-item">
              <span>上下文依赖:</span>
              <span :class="absenceResult.context_has_dependency ? 'ok' : 'fail'">
                {{ absenceResult.context_has_dependency ? '✓' : '✗' }}
              </span>
            </div>
          </div>
          <div v-if="absenceResult.explanation.length > 0" class="explanation">
            <h4>解释</h4>
            <div v-for="(exp, idx) in absenceResult.explanation" :key="idx">
              {{ exp }}
            </div>
          </div>
          <div v-if="absenceResult.suggestions.length > 0" class="suggestions">
            <h4>建议</h4>
            <div v-for="(sug, idx) in absenceResult.suggestions" :key="idx">
              {{ sug }}
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import {
  listEntities,
  getEntityDependencies,
  cascadeReasoning,
  detectAbsence,
  getNeuronStats,
  neuronHealth,
  type Entity,
  type CascadeResult,
  type AbsenceResult,
  type NeuronStats,
} from '@/api/neuron'

// 状态
const activeTab = ref('graph')
const stats = ref<NeuronStats>({ total_entities: 0, total_edges: 0, entity_types: 0, dependency_types: 0 })
const healthStatus = ref('healthy')
const entities = ref<Entity[]>([])
const selectedEntity = ref('')
const dependencies = ref<{ downstream: string[]; upstream: string[] }>({ downstream: [], upstream: [] })
const cascadeForm = ref({ entityId: '', direction: 'forward', maxDepth: 5 })
const cascadeLoading = ref(false)
const cascadeResult = ref<CascadeResult | null>(null)
const absenceForm = ref({ expectedEntity: '', expectedRelation: 'causal', contextEntities: '' })
const absenceLoading = ref(false)
const absenceResult = ref<AbsenceResult | null>(null)

const tabs = [
  { key: 'graph', label: '依赖图谱' },
  { key: 'cascade', label: '级联推理' },
  { key: 'absence', label: '缺失检测' },
]

// 加载数据
onMounted(async () => {
  await loadStats()
  await loadEntities()
})

async function loadStats() {
  try {
    const result = await getNeuronStats()
    if (result.success) {
      stats.value = result.data
    }
  } catch (e) {
    console.error('加载统计失败:', e)
  }
}

async function loadEntities() {
  try {
    const result = await listEntities()
    if (result.success) {
      entities.value = result.data
    }
  } catch (e) {
    console.error('加载实体失败:', e)
  }
}

async function showDependencies(entityId: string) {
  selectedEntity.value = entityId
  try {
    const result = await getEntityDependencies(entityId)
    if (result.success) {
      dependencies.value = result.data
    }
  } catch (e) {
    console.error('加载依赖失败:', e)
  }
}

async function runCascade() {
  if (!cascadeForm.value.entityId) return
  
  cascadeLoading.value = true
  try {
    const result = await cascadeReasoning(
      cascadeForm.value.entityId,
      cascadeForm.value.direction,
      cascadeForm.value.maxDepth
    )
    if (result.success) {
      cascadeResult.value = result.data
    }
  } catch (e) {
    console.error('级联推理失败:', e)
  } finally {
    cascadeLoading.value = false
  }
}

async function runAbsenceCheck() {
  if (!absenceForm.value.expectedEntity) return
  
  absenceLoading.value = true
  try {
    const contextEntities = absenceForm.value.contextEntities
      .split(',')
      .map(s => s.trim())
      .filter(s => s)
    
    const result = await detectAbsence(
      absenceForm.value.expectedEntity,
      absenceForm.value.expectedRelation,
      contextEntities
    )
    if (result.success) {
      absenceResult.value = result.data
    }
  } catch (e) {
    console.error('缺失检测失败:', e)
  } finally {
    absenceLoading.value = false
  }
}
</script>

<style scoped>
.neuron-page {
  padding: 24px;
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 24px;
}

.page-header h1 {
  margin: 0 0 8px 0;
  font-size: 28px;
  color: #1a1a1a;
}

.subtitle {
  color: #666;
  margin: 0;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.stat-card {
  background: #f8f9fa;
  border-radius: 8px;
  padding: 20px;
  text-align: center;
}

.stat-value {
  font-size: 32px;
  font-weight: 600;
  color: #1a1a1a;
}

.stat-label {
  color: #666;
  margin-top: 8px;
}

.tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 24px;
  border-bottom: 1px solid #e0e0e0;
  padding-bottom: 8px;
}

.tab {
  padding: 10px 20px;
  border: none;
  background: none;
  cursor: pointer;
  font-size: 14px;
  color: #666;
  border-radius: 4px;
  transition: all 0.2s;
}

.tab:hover {
  background: #f0f0f0;
}

.tab.active {
  background: #1890ff;
  color: white;
}

.section {
  background: white;
  border-radius: 8px;
  padding: 20px;
  margin-bottom: 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.section h3 {
  margin: 0 0 16px 0;
  font-size: 16px;
  color: #1a1a1a;
}

.entity-list {
  max-height: 400px;
  overflow-y: auto;
}

.entity-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  border-bottom: 1px solid #f0f0f0;
}

.entity-type {
  background: #e6f7ff;
  color: #1890ff;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 12px;
}

.entity-name {
  flex: 1;
  font-weight: 500;
}

.btn-sm {
  padding: 4px 12px;
  border: 1px solid #d9d9d9;
  border-radius: 4px;
  background: white;
  cursor: pointer;
  font-size: 12px;
}

.btn-sm:hover {
  border-color: #1890ff;
  color: #1890ff;
}

.empty-state {
  text-align: center;
  color: #999;
  padding: 40px;
}

.dependency-view h4 {
  margin: 16px 0 8px 0;
  font-size: 14px;
  color: #666;
}

.dep-item {
  padding: 8px 12px;
  margin: 4px 0;
  border-radius: 4px;
  font-size: 13px;
}

.dep-item.downstream {
  background: #e6f7ff;
  color: #1890ff;
}

.dep-item.upstream {
  background: #f6ffed;
  color: #52c41a;
}

.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  margin-bottom: 8px;
  font-weight: 500;
  color: #333;
}

.form-group input,
.form-group select {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #d9d9d9;
  border-radius: 4px;
  font-size: 14px;
}

.form-group input:focus,
.form-group select:focus {
  border-color: #1890ff;
  outline: none;
  box-shadow: 0 0 0 2px rgba(24, 144, 255, 0.2);
}

.btn-primary {
  padding: 10px 24px;
  background: #1890ff;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  transition: background 0.2s;
}

.btn-primary:hover {
  background: #40a9ff;
}

.btn-primary:disabled {
  background: #d9d9d9;
  cursor: not-allowed;
}

.result-panel {
  margin-top: 24px;
  padding: 20px;
  background: #f8f9fa;
  border-radius: 8px;
}

.result-panel h4 {
  margin: 0 0 12px 0;
  font-size: 16px;
}

.status-badge {
  display: inline-block;
  padding: 8px 16px;
  border-radius: 4px;
  font-weight: 500;
}

.status-badge.absent {
  background: #fff1f0;
  color: #ff4d4f;
}

.status-badge.present {
  background: #f6ffed;
  color: #52c41a;
}

.effects-list {
  margin: 12px 0;
}

.effect-item {
  display: flex;
  gap: 12px;
  padding: 8px;
  margin: 4px 0;
  background: white;
  border-radius: 4px;
}

.effect-type {
  background: #e6f7ff;
  color: #1890ff;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
}

.effect-conf {
  color: #52c41a;
  font-weight: 500;
}

.reasoning-chain {
  margin-top: 16px;
  padding: 12px;
  background: white;
  border-radius: 4px;
}

.chain-line {
  padding: 4px 0;
  font-family: monospace;
  font-size: 13px;
  color: #666;
}

.check-results {
  margin: 12px 0;
}

.check-item {
  display: flex;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px solid #f0f0f0;
}

.check-item .ok {
  color: #52c41a;
  font-weight: bold;
}

.check-item .fail {
  color: #ff4d4f;
  font-weight: bold;
}

.explanation,
.suggestions {
  margin-top: 16px;
  padding: 12px;
  background: white;
  border-radius: 4px;
}

.explanation h4,
.suggestions h4 {
  margin: 0 0 8px 0;
  font-size: 14px;
  color: #666;
}
</style>

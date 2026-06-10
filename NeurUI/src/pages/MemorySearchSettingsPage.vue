<template>
  <div class="memory-search-settings-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('memorySearch.title') }}</h2>
      <GlassButton variant="ghost" size="sm" :loading="loading" @click="fetchSettings">{{ t('common.refresh') }}</GlassButton>
    </div>

    <a-spin :spinning="loading">
      <!-- Search method -->
      <GlassCard :title="t('memorySearch.searchMethod')" style="margin-top: 8px">
        <a-form layout="vertical" :model="searchConfig">
          <a-form-item :label="t('memorySearch.searchMethod')">
            <a-radio-group v-model:value="searchConfig.method">
              <a-radio-button value="hybrid">{{ t('memorySearch.hybrid') }}</a-radio-button>
              <a-radio-button value="bm25">{{ t('memorySearch.bm25') }}</a-radio-button>
              <a-radio-button value="vector">{{ t('memorySearch.vector') }}</a-radio-button>
            </a-radio-group>
          </a-form-item>
          <a-form-item :label="t('memorySearch.topK')">
            <a-input-number v-model:value="searchConfig.top_k" :min="1" :max="100" style="width: 100%" />
          </a-form-item>
          <a-form-item :label="t('memorySearch.scoreThreshold')">
            <a-slider v-model:value="searchConfig.score_threshold" :min="0" :max="100" />
          </a-form-item>
        </a-form>
        <template #footer>
          <GlassButton variant="primary" size="sm" :loading="saving" @click="saveSettings">{{ t('common.save') }}</GlassButton>
        </template>
      </GlassCard>

      <!-- Decay settings -->
      <GlassCard :title="t('memory.decay')" style="margin-top: 16px">
        <a-form layout="vertical" :model="decay">
          <a-form-item :label="t('memorySearch.enableDecay')">
            <a-switch v-model:checked="decay.enabled" />
          </a-form-item>
          <a-form-item :label="t('memorySearch.decayRate')">
            <a-slider v-model:value="decay.rate" :min="0" :max="100" />
          </a-form-item>
          <a-form-item :label="t('memorySearch.halfLife')">
            <a-input-number v-model:value="decay.half_life_days" :min="1" :max="365" style="width: 100%" />
          </a-form-item>
          <a-form-item :label="t('memorySearch.minScoreFloor')">
            <a-slider v-model:value="decay.min_score" :min="0" :max="100" />
          </a-form-item>
        </a-form>
        <template #footer>
          <GlassButton variant="primary" size="sm" :loading="saving" @click="saveSettings">{{ t('common.save') }}</GlassButton>
        </template>
      </GlassCard>

      <!-- Enhancement settings -->
      <GlassCard :title="t('memory.enhance')" style="margin-top: 16px">
        <a-form layout="vertical" :model="enhancement">
          <a-form-item :label="t('memorySearch.enableEnhancement')">
            <a-switch v-model:checked="enhancement.enabled" />
          </a-form-item>
          <a-form-item :label="t('memorySearch.boostFactor')">
            <a-slider v-model:value="enhancement.boost_factor" :min="1" :max="10" />
          </a-form-item>
          <a-form-item :label="t('memorySearch.recencyWeight')">
            <a-slider v-model:value="enhancement.recency_weight" :min="0" :max="100" />
          </a-form-item>
          <a-form-item :label="t('memorySearch.frequencyWeight')">
            <a-slider v-model:value="enhancement.frequency_weight" :min="0" :max="100" />
          </a-form-item>
        </a-form>
        <template #footer>
          <GlassButton variant="primary" size="sm" :loading="saving" @click="saveSettings">{{ t('common.save') }}</GlassButton>
        </template>
      </GlassCard>

      <!-- Test search -->
      <GlassCard :title="t('memorySearch.testSearch')" style="margin-top: 16px">
        <div class="test-search">
          <a-input-search v-model:value="testQuery" :placeholder="t('memorySearch.testQueryPlaceholder')" @search="runTestSearch" style="width: 100%" />
          <div v-if="testResults.length" class="test-results">
            <a-list :data-source="testResults" size="small">
              <template #renderItem="{ item }">
                <a-list-item>
                  <div class="result-item">
                    <span class="result-content">{{ item.content || item.text }}</span>
                    <a-tag>{{ (item.score ?? 0).toFixed(3) }}</a-tag>
                  </div>
                </a-list-item>
              </template>
            </a-list>
          </div>
          <a-empty v-if="!testResults.length && testExecuted" :description="t('common.noData')" />
        </div>
      </GlassCard>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'

const { t } = useI18n()

const loading = ref(false)
const saving = ref(false)
const testExecuted = ref(false)
const testQuery = ref('')
const testResults = ref<any[]>([])

const searchConfig = ref({ method: 'hybrid', top_k: 10, score_threshold: 30 })
const decay = ref({ enabled: true, rate: 50, half_life_days: 30, min_score: 10 })
const enhancement = ref({ enabled: true, boost_factor: 2, recency_weight: 60, frequency_weight: 40 })

const fetchSettings = async () => {
  loading.value = true
  try {
    const res: any = await request.get('/memory-search/settings')
    const data = res?.data ?? res ?? {}
    if (data.search) searchConfig.value = { ...searchConfig.value, ...data.search }
    if (data.decay) decay.value = { ...decay.value, ...data.decay }
    if (data.enhancement) enhancement.value = { ...enhancement.value, ...data.enhancement }
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

const saveSettings = async () => {
  saving.value = true
  try {
    await request.put('/memory-search/settings', {
      search: searchConfig.value,
      decay: decay.value,
      enhancement: enhancement.value,
    })
    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  } finally {
    saving.value = false
  }
}

const runTestSearch = async () => {
  if (!testQuery.value) return
  try {
    const endpoint = searchConfig.value.method === 'hybrid' ? '/semantic-search/hybrid' : '/enhanced-memory-search/search'
    const res: any = await request.post(endpoint, {
      query: testQuery.value,
      method: searchConfig.value.method,
      top_k: searchConfig.value.top_k,
      score_threshold: searchConfig.value.score_threshold / 100,
    })
    const data = res?.data ?? res ?? {}
    testResults.value = data.results ?? data.items ?? (Array.isArray(data) ? data : [])
    testExecuted.value = true
  } catch {
    message.error(t('common.error'))
    testResults.value = []
    testExecuted.value = true
  }
}

onMounted(fetchSettings)
</script>

<style scoped>
.memory-search-settings-page { display: flex; flex-direction: column; gap: 16px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.test-search { display: flex; flex-direction: column; gap: 16px; }
.test-results { max-height: 300px; overflow: auto; }
.result-item { display: flex; justify-content: space-between; align-items: center; width: 100%; }
.result-content { font-size: 13px; color: var(--nr-text-secondary); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>

<template>
  <div class="memory-search-settings-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('memorySearch.title') }}</h2>
      <p class="page-global-hint">{{ t('common.globalSettingHint') }}</p>
      <GlassButton variant="ghost" size="sm" :loading="loading" @click="fetchSettings">{{ t('common.refresh') }}</GlassButton>
    </div>

    <a-spin :spinning="loading">
      <!-- 非管理员:仅提示, 不渲染任何设置操作 -->
      <template v-if="!isAdmin">
        <div class="admin-gate">{{ t('common.adminOnlyHint') }}</div>
      </template>
      <template v-else>
      <!-- 数据未就绪前仅渲染轻量占位, 避免"默认值表单 → 真值表单"两轮全页 patch
           (该双帧载荷恰落在 a-spin 遮罩过渡的兜底 setTimeout 回调整链上,
           在慢环境/DevTools 下被记 [Violation] 'setTimeout' handler took >50ms) -->
      <template v-if="initialized">
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

      <!-- NeRF Volume Rendering Settings -->
      <GlassCard :title="t('memorySearch.nerfTitle')" style="margin-top: 16px">
        <a-form layout="vertical" :model="nerfSettings">
          <a-form-item :label="t('memorySearch.nerfMode')">
            <a-radio-group v-model:value="nerfSettings.fusion_mode" @change="onNerfModeChange">
              <a-radio-button value="legacy">
                <a-tooltip :title="t('memorySearch.nerfLegacyDesc')">{{ t('memorySearch.nerfLegacy') }}</a-tooltip>
              </a-radio-button>
              <a-radio-button value="nerf">
                <a-tooltip :title="t('memorySearch.nerfNerfDesc')">{{ t('memorySearch.nerfNerf') }}</a-tooltip>
              </a-radio-button>
            </a-radio-group>
            <div class="mode-desc">{{ nerfModeDescription }}</div>
          </a-form-item>

          <template v-if="nerfSettings.fusion_mode === 'nerf'">
            <a-form-item :label="t('memorySearch.densityScale')">
              <a-slider v-model:value="nerfSettings.density_scale" :min="0.1" :max="5.0" :step="0.1" />
              <div class="slider-hint">{{ t('memorySearch.densityScaleHint') }}</div>
            </a-form-item>

            <a-form-item :label="t('memorySearch.channelDensities')">
              <div class="channel-densities">
                <div v-for="(val, ch) in nerfSettings.channel_densities" :key="ch" class="channel-density-row">
                  <span class="channel-name">{{ channelLabel(ch as string) }}</span>
                  <a-slider
                    :value="val"
                    :min="0" :max="1.0" :step="0.05"
                    style="flex: 1"
                    @change="(v: number) => onChannelDensityChange(ch, v)"
                  />
                  <span class="channel-value">{{ (val as number).toFixed(2) }}</span>
                </div>
              </div>
            </a-form-item>

            <!-- Intent weight visualization -->
            <a-form-item :label="t('memorySearch.intentWeightPreview')">
              <a-select v-model:value="previewIntent" style="width: 200px" @change="fetchChannelWeights">
                <a-select-option value="factual">{{ t('memorySearch.intentFactual') }}</a-select-option>
                <a-select-option value="temporal">{{ t('memorySearch.intentTemporal') }}</a-select-option>
                <a-select-option value="causal">{{ t('memorySearch.intentCausal') }}</a-select-option>
                <a-select-option value="comparative">{{ t('memorySearch.intentComparative') }}</a-select-option>
                <a-select-option value="exploratory">{{ t('memorySearch.intentExploratory') }}</a-select-option>
              </a-select>
              <div class="weight-bars">
                <div v-for="(w, ch) in channelWeights" :key="ch" class="weight-bar-row">
                  <span class="weight-label">{{ channelLabel(ch as string) }}</span>
                  <div class="weight-bar-bg">
                    <div class="weight-bar-fill" :style="{ width: `${(w as number) * 100}%`, backgroundColor: channelColor(ch as string) }" />
                  </div>
                  <span class="weight-value">{{ ((w as number) * 100).toFixed(0) }}%</span>
                </div>
              </div>
            </a-form-item>
          </template>
        </a-form>
        <template #footer>
          <GlassButton variant="ghost" size="sm" :loading="saving" @click="resetNerf">{{ t('common.reset') }}</GlassButton>
          <GlassButton variant="primary" size="sm" :loading="saving" @click="saveNerfSettings">{{ t('common.save') }}</GlassButton>
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
                    <a-tag v-if="item.channel_scores" color="cyan" class="nerf-tag">{{ t('memorySearch.nerfTag') }}</a-tag>
                  </div>
                </a-list-item>
              </template>
            </a-list>
          </div>
          <a-empty v-if="!testResults.length && testExecuted" :description="t('common.noData')" />
        </div>
      </GlassCard>
      </template>
      <a-empty v-else :description="t('common.loading')" />
      </template>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import { getNerfSettings, updateNerfSettings, resetNerfSettings, getChannelWeights } from '@/api/modules/memory'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()
const authStore = useAuthStore()
/** 全局记忆检索设置仅管理员可操作; 非管理员不渲染设置区 */
const isAdmin = computed(() => authStore.user?.role === 'admin')

const loading = ref(false)
const saving = ref(false)
const initialized = ref(false)
const testExecuted = ref(false)
const testQuery = ref('')
const testResults = ref<any[]>([])

const searchConfig = ref({ method: 'hybrid', top_k: 10, score_threshold: 30 })
const decay = ref({ enabled: true, rate: 50, half_life_days: 30, min_score: 10 })
const enhancement = ref({ enabled: true, boost_factor: 2, recency_weight: 60, frequency_weight: 40 })

// NeRF settings
const nerfSettings = ref({
  fusion_mode: 'legacy' as 'legacy' | 'nerf',
  density_scale: 1.0,
  channel_densities: {
    temperature: 0.7,
    text: 0.9,
    category: 0.5,
    graph: 0.6,
    emotion: 0.8,
    voice: 0.4,
  } as Record<string, number>,
})
const previewIntent = ref('exploratory')
const channelWeights = ref<Record<string, number>>({})

const nerfModeDescription = computed(() => {
  return nerfSettings.value.fusion_mode === 'nerf'
    ? t('memorySearch.nerfNerfDesc')
    : t('memorySearch.nerfLegacyDesc')
})

const channelColors: Record<string, string> = {
  text: '#1890ff',
  temperature: '#ff7a45',
  category: '#722ed1',
  graph: '#13c2c2',
  emotion: '#eb2f96',
  voice: '#52c41a',
}

const channelColor = (ch: string) => channelColors[ch] || '#8c8c8c'

const channelLabelMap: Record<string, string> = {
  text: 'channelText',
  temperature: 'channelTemperature',
  category: 'channelCategory',
  graph: 'channelGraph',
  emotion: 'channelEmotion',
  voice: 'channelVoice',
}
const channelLabel = (ch: string) => t(`memorySearch.${channelLabelMap[ch] || ch}`)

const fetchSettings = async () => {
  loading.value = true
  try {
    const res: any = await request.get('/enhanced-memory-search/settings')
    const data = res?.data ?? res ?? {}
    if (data.search) searchConfig.value = { ...searchConfig.value, ...data.search }
    if (data.decay) decay.value = { ...decay.value, ...data.decay }
    if (data.enhancement) enhancement.value = { ...enhancement.value, ...data.enhancement }
  } catch {
    message.error(t('common.error'))
  } finally {
    initialized.value = true // 成败都放行: 失败时以默认配置可编辑, 不永久留白
    loading.value = false
  }
}

const fetchNerfSettings = async () => {
  try {
    const res = await getNerfSettings()
    const data = res?.data
    if (data) {
      nerfSettings.value.fusion_mode = data.fusion_mode
      nerfSettings.value.density_scale = data.density_scale
      nerfSettings.value.channel_densities = data.channel_densities
    }
  } catch {
    // NeRF settings may not be available yet
  }
}

const fetchChannelWeights = async (intent: string) => {
  try {
    const res = await getChannelWeights(intent)
    channelWeights.value = res?.data?.weights || {}
  } catch {
    channelWeights.value = {}
  }
}

const onNerfModeChange = () => {
  // Mode changed, nothing else needed
}

const onChannelDensityChange = (ch: string, val: number) => {
  nerfSettings.value.channel_densities[ch] = val
}

const saveSettings = async () => {
  saving.value = true
  try {
    await request.put('/enhanced-memory-search/settings', {
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

const saveNerfSettings = async () => {
  saving.value = true
  try {
    await updateNerfSettings({
      fusion_mode: nerfSettings.value.fusion_mode,
      density_scale: nerfSettings.value.density_scale,
      channel_densities: nerfSettings.value.channel_densities,
    })
    message.success(t('memorySearch.saved'))
  } catch {
    message.error(t('common.error'))
  } finally {
    saving.value = false
  }
}

const resetNerf = async () => {
  saving.value = true
  try {
    const res = await resetNerfSettings()
    const data = res?.data
    if (data) {
      nerfSettings.value.fusion_mode = data.fusion_mode
      nerfSettings.value.density_scale = data.density_scale
      nerfSettings.value.channel_densities = data.channel_densities
    }
    message.success(t('memorySearch.resetDone'))
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

onMounted(() => {
  fetchSettings()
  fetchNerfSettings()
  fetchChannelWeights(previewIntent.value)
})
</script>

<style scoped>
/* 全局设置说明（标题下方） */
.page-global-hint {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--nr-text-secondary, #8a8a92);
}

/* 非管理员提示 */
.admin-gate {
  margin: 24px auto;
  max-width: 480px;
  padding: 16px;
  border: 1px dashed var(--nr-border, rgba(255, 255, 255, 0.12));
  border-radius: 10px;
  text-align: center;
  font-size: 13px;
  color: var(--nr-text-secondary, #8a8a92);
}
.memory-search-settings-page { display: flex; flex-direction: column; gap: 16px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.test-search { display: flex; flex-direction: column; gap: 16px; }
.test-results { max-height: 300px; overflow: auto; }
.result-item { display: flex; justify-content: space-between; align-items: center; width: 100%; }
.result-content { font-size: 13px; color: var(--nr-text-secondary); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nerf-tag { margin-left: 8px; }

/* NeRF settings styles */
.mode-desc {
  margin-top: 8px;
  font-size: 12px;
  color: var(--nr-text-secondary);
  font-style: italic;
}
.slider-hint {
  margin-top: 4px;
  font-size: 11px;
  color: var(--nr-text-tertiary);
}
.channel-densities {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.channel-density-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.channel-name {
  width: 80px;
  font-size: 13px;
  color: var(--nr-text-primary);
  text-transform: capitalize;
}
.channel-value {
  width: 40px;
  text-align: right;
  font-size: 12px;
  color: var(--nr-text-secondary);
  font-family: monospace;
}

/* Intent weight bars */
.weight-bars {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.weight-bar-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.weight-label {
  width: 80px;
  font-size: 12px;
  color: var(--nr-text-primary);
  text-transform: capitalize;
}
.weight-bar-bg {
  flex: 1;
  height: 16px;
  background: var(--nr-bg-secondary, rgba(255,255,255,0.05));
  border-radius: 4px;
  overflow: hidden;
}
.weight-bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s ease;
  min-width: 2px;
}
.weight-value {
  width: 40px;
  text-align: right;
  font-size: 11px;
  color: var(--nr-text-secondary);
  font-family: monospace;
}
</style>

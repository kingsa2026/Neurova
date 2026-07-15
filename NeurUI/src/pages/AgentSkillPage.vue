<template>
  <div class="skill-page">
    <!-- Stats Row -->
    <div class="skill-stats">
      <GlassStatCard :label="t('skill.totalSkills')" :value="skills.length" emoji="🧩" />
      <GlassStatCard :label="t('skill.enabledSkills')" :value="enabledCount" emoji="✅" />
      <GlassStatCard :label="t('skill.executionCount')" :value="totalExecutions" emoji="⚡" />
    </div>

    <!-- Toolbar -->
    <GlassPanel class="skill-toolbar">
      <div class="toolbar-row">
        <a-input-search
          v-model:value="searchQuery"
          :placeholder="t('skill.searchPlaceholder')"
          allow-clear
          style="max-width: 320px"
        />
        <div class="toolbar-actions">
          <GlassButton variant="secondary" size="sm" @click="openMarketImportModal">
            {{ t('skill.importFromMarket') }}
          </GlassButton>
          <GlassButton variant="primary" size="sm" @click="refreshSkills">
            {{ t('common.refresh') }}
          </GlassButton>
        </div>
      </div>
    </GlassPanel>

    <!-- Skills Grid -->
    <a-spin :spinning="loading">
      <div v-if="filteredSkills.length" class="skill-grid">
        <GlassCard
          v-for="skill in filteredSkills"
          :key="skill.id"
          :title="skill.name"
          :subtitle="skill.description"
          variant="default"
        >
          <div class="skill-card-body">
            <div class="skill-meta">
              <a-tag :color="skill.enabled ? 'green' : 'default'">
                {{ skill.enabled ? t('skill.enabled') : t('skill.disabled') }}
              </a-tag>
              <span class="skill-exec-count">
                {{ skill.execution_count ?? 0 }} {{ t('skill.executions') }}
              </span>
            </div>
            <div class="skill-actions">
              <a-switch
                :checked="skill.enabled"
                :loading="skill._toggling"
                @change="(val: boolean) => toggleSkill(skill, val)"
                size="small"
              />
              <GlassButton
                variant="primary"
                size="sm"
                :disabled="!skill.enabled"
                @click="openExecuteModal(skill)"
              >
                {{ t('skill.execute') }}
              </GlassButton>
            </div>
          </div>
        </GlassCard>
      </div>
      <a-empty v-else :description="t('skill.noSkills')" />
    </a-spin>

    <!-- Execute Skill Modal -->
    <a-modal
      v-model:open="executeVisible"
      :title="`${t('skill.executeSkill')}: ${activeSkill?.name}`"
      :confirm-loading="executing"
      @ok="runExecute"
      @cancel="executeVisible = false"
    >
      <a-form layout="vertical">
        <a-form-item :label="t('skill.arguments')">
          <a-textarea
            v-model:value="executeArgs"
            :placeholder="t('skill.argsPlaceholder')"
            :rows="6"
          />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- Import Skill from Market Modal -->
    <a-modal
      v-model:open="marketImportVisible"
      :title="t('skill.importFromMarket')"
      :footer="null"
      width="640px"
    >
      <a-input-search
        v-model:value="marketSearch"
        :placeholder="t('skill.marketSearchPlaceholder')"
        allow-clear
        style="margin-bottom: 12px"
      />
      <a-spin :spinning="marketLoading">
        <div v-if="filteredMarketSkills.length" class="market-import-list">
          <div v-for="s in filteredMarketSkills" :key="s.id" class="market-import-row">
            <div class="market-import-info">
              <div class="market-import-name">{{ s.name }}</div>
              <div class="market-import-desc">{{ s.description }}</div>
            </div>
            <GlassButton
              variant="primary"
              size="sm"
              :loading="s._installing"
              @click="installFromMarket(s)"
            >
              {{ t('skill.install') }}
            </GlassButton>
          </div>
        </div>
        <a-empty v-else :description="t('skill.noMarketSkills')" />
      </a-spin>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import * as skillPoolApi from '@/api/modules/skill-pool'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import GlassStatCard from '@/components/GlassStatCard.vue'

interface Skill {
  id: string
  name: string
  description: string
  enabled: boolean
  execution_count?: number
  _toggling?: boolean
}

interface MarketSkill {
  id: string
  name: string
  description: string
  category?: string
  _installing?: boolean
}

const props = defineProps<{ agentId: string }>()
const { t } = useI18n()

const skills = ref<Skill[]>([])
const loading = ref(false)
const searchQuery = ref('')

// Execute modal state
const executeVisible = ref(false)
const executing = ref(false)
const activeSkill = ref<Skill | null>(null)
const executeArgs = ref('')

// Market import modal state
const marketImportVisible = ref(false)
const marketLoading = ref(false)
const marketSearch = ref('')
const marketSkills = ref<MarketSkill[]>([])

const filteredMarketSkills = computed(() => {
  const q = marketSearch.value.toLowerCase()
  if (!q) return marketSkills.value
  return marketSkills.value.filter(
    (s) => s.name.toLowerCase().includes(q) || s.description.toLowerCase().includes(q),
  )
})

const enabledCount = computed(() => skills.value.filter((s) => s.enabled).length)
const totalExecutions = computed(() =>
  skills.value.reduce((sum, s) => sum + (s.execution_count ?? 0), 0),
)

const filteredSkills = computed(() => {
  const q = searchQuery.value.toLowerCase()
  if (!q) return skills.value
  return skills.value.filter(
    (s) => s.name.toLowerCase().includes(q) || s.description.toLowerCase().includes(q),
  )
})

async function refreshSkills() {
  loading.value = true
  try {
    const res = await skillPoolApi.getAgentSkills(props.agentId)
    const data: any = (res as any)?.data ?? res
    skills.value = (Array.isArray(data) ? data : data?.items ?? []).map((s: any) => ({
      ...s,
      _toggling: false,
    }))
  } catch (err: any) {
    const msg = err?.response?.data?.error || err?.message || t('skill.loadError')
    message.error(msg)
  } finally {
    loading.value = false
  }
}

async function toggleSkill(skill: Skill, enabled: boolean) {
  skill._toggling = true
  try {
    await skillPoolApi.enableSkill(skill.id, enabled)
    skill.enabled = enabled
    message.success(enabled ? t('skill.enabledSuccess') : t('skill.disabledSuccess'))
  } catch (err: any) {
    const msg = err?.response?.data?.error || err?.message || t('skill.toggleError')
    message.error(msg)
  } finally {
    skill._toggling = false
  }
}

function openExecuteModal(skill: Skill) {
  activeSkill.value = skill
  executeArgs.value = ''
  executeVisible.value = true
}

async function runExecute() {
  if (!activeSkill.value) return
  executing.value = true
  try {
    let parsedArgs: any = executeArgs.value
    try {
      parsedArgs = JSON.parse(executeArgs.value)
    } catch {
      // keep as string if not valid JSON
    }
    await skillPoolApi.executeSkill(activeSkill.value.id, props.agentId, parsedArgs)
    activeSkill.value.execution_count = (activeSkill.value.execution_count ?? 0) + 1
    message.success(t('skill.executeSuccess'))
    executeVisible.value = false
  } catch (err: any) {
    const msg = err?.response?.data?.error || err?.message || t('skill.executeError')
    message.error(msg)
  } finally {
    executing.value = false
  }
}

onMounted(refreshSkills)

async function openMarketImportModal() {
  marketImportVisible.value = true
  marketSearch.value = ''
  await fetchMarketSkills()
}

async function fetchMarketSkills() {
  marketLoading.value = true
  try {
    const res = await skillPoolApi.getPublicSkills()
    const data: any = (res as any)?.data ?? res
    marketSkills.value = (Array.isArray(data) ? data : data?.items ?? []).map((s: any) => ({
      ...s,
      _installing: false,
    }))
  } catch (err: any) {
    const msg = err?.response?.data?.error || err?.message || t('skill.loadError')
    message.error(msg)
  } finally {
    marketLoading.value = false
  }
}

async function installFromMarket(skill: MarketSkill) {
  skill._installing = true
  try {
    await skillPoolApi.installSkill(skill.id, props.agentId)
    message.success(t('skill.installSuccess'))
    // Refresh agent skills so the new skill appears in the grid.
    await refreshSkills()
  } catch (err: any) {
    const msg = err?.response?.data?.error || err?.message || t('skill.installError')
    message.error(msg)
  } finally {
    skill._installing = false
  }
}
</script>

<style scoped>
.skill-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.skill-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 16px;
}

.skill-toolbar .toolbar-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.toolbar-actions {
  display: flex;
  gap: 8px;
}

.skill-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}

.skill-card-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.skill-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.skill-exec-count {
  font-size: 12px;
  color: var(--nr-text-tertiary);
}

.skill-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--nr-glass-border);
}

.market-import-list {
  max-height: 420px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.market-import-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--nr-glass-border);
  border-radius: 8px;
}

.market-import-info {
  flex: 1;
  min-width: 0;
}

.market-import-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--nr-text-primary);
}

.market-import-desc {
  font-size: 12px;
  color: var(--nr-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>

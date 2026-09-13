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
          <GlassButton variant="secondary" size="sm" @click="openProposals">
            {{ t('skillEvo.proposals') }}
          </GlassButton>
          <GlassButton variant="secondary" size="sm" @click="openSettings">
            {{ t('skillEvo.settings') }}
          </GlassButton>
          <GlassButton
            variant="secondary"
            size="sm"
            :loading="sweepRunning"
            @click="runSweep"
          >
            {{ t('skillEvo.runSweep') }}
          </GlassButton>
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
              <div class="skill-tags">
                <a-tag :color="skill.enabled ? 'green' : 'default'">
                  {{ skill.enabled ? t('skill.enabled') : t('skill.disabled') }}
                </a-tag>
                <a-tag v-if="stateOf(skill) !== 'active' || skill.usage" :color="stateColor(stateOf(skill))">
                  {{ stateLabel(stateOf(skill)) }}
                </a-tag>
                <a-tag v-if="skill.usage?.pinned" color="purple">📌 {{ t('skillEvo.pinned') }}</a-tag>
                <a-tag v-if="skill.usage?.created_by === 'agent'" color="blue">
                  {{ t('skillEvo.agentCreated') }}
                </a-tag>
              </div>
              <span class="skill-exec-count">
                {{ useCountOf(skill) }} {{ t('skill.executions') }}
              </span>
            </div>
            <div class="skill-actions">
              <a-switch
                :checked="skill.enabled"
                :loading="skill._toggling"
                @change="(val: boolean) => toggleSkill(skill, val)"
                size="small"
              />
              <div class="skill-action-buttons">
                <GlassButton
                  variant="ghost"
                  size="sm"
                  :loading="skill._pinning"
                  @click="togglePin(skill)"
                >
                  {{ skill.usage?.pinned ? t('skillEvo.unpin') : t('skillEvo.pin') }}
                </GlassButton>
                <GlassButton
                  variant="secondary"
                  size="sm"
                  :disabled="!skill.enabled"
                  @click="openEvolve(skill)"
                >
                  {{ t('skillEvo.evolve') }}
                </GlassButton>
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

    <!-- 进化设置 Modal -->
    <a-modal
      v-model:open="settingsVisible"
      :title="t('skillEvo.settings')"
      :confirm-loading="settingsSaving"
      :ok-text="t('common.save')"
      @ok="saveSettings"
    >
      <a-spin :spinning="settingsLoading">
        <a-form v-if="settings" layout="vertical">
          <a-form-item :label="t('skillEvo.textEvolution')">
            <a-switch v-model:checked="settings.text_evolution" />
            <p class="evo-hint">{{ t('skillEvo.textEvolutionHint') }}</p>
          </a-form-item>
          <a-form-item :label="t('skillEvo.lifecycleSweep')">
            <a-switch v-model:checked="settings.lifecycle_sweep" />
            <p class="evo-hint">{{ t('skillEvo.lifecycleSweepHint') }}</p>
          </a-form-item>
          <a-form-item :label="t('skillEvo.sweepInterval')">
            <a-input-number v-model:value="settings.lifecycle_interval_hours" :min="1" :max="720" />
          </a-form-item>
        </a-form>
      </a-spin>
    </a-modal>

    <!-- 技能进化 Modal -->
    <a-modal
      v-model:open="evolveVisible"
      :title="`${t('skillEvo.evolve')}: ${evolveTarget?.name ?? ''}`"
      :confirm-loading="evolveRunning"
      :ok-text="t('skillEvo.runEvolve')"
      :cancel-text="t('common.cancel')"
      @ok="runEvolve"
    >
      <a-form layout="vertical">
        <a-form-item :label="t('skillEvo.iterations')">
          <a-input-number v-model:value="evolveIterations" :min="1" :max="50" />
        </a-form-item>
        <a-form-item :label="t('skillEvo.datasetSource')">
          <a-select v-model:value="evolveSource" style="width: 200px">
            <a-select-option value="auto">{{ t('skillEvo.sourceAuto') }}</a-select-option>
            <a-select-option value="golden">{{ t('skillEvo.sourceGolden') }}</a-select-option>
            <a-select-option value="mined">{{ t('skillEvo.sourceMined') }}</a-select-option>
            <a-select-option value="synthetic">{{ t('skillEvo.sourceSynthetic') }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-alert
          v-if="evolveResult"
          type="info"
          :message="evolveResult"
          show-icon
        />
      </a-form>
    </a-modal>

    <!-- 待审进化提案 Modal -->
    <a-modal
      v-model:open="proposalsVisible"
      :title="t('skillEvo.proposals')"
      :footer="null"
      width="720px"
    >
      <a-spin :spinning="proposalsLoading">
        <div v-if="proposals.length" class="proposal-list">
          <div v-for="p in proposals" :key="p.proposal_id" class="proposal-row">
            <div>
              <div class="proposal-skill">{{ p.skill_id }}</div>
              <div class="proposal-metric">
                {{ t('skillEvo.holdout') }}: {{ p.holdout_before }} → {{ p.holdout_after }}
                · {{ p.iterations_run }} {{ t('skillEvo.iterationsUnit') }}
              </div>
            </div>
            <div class="proposal-actions">
              <GlassButton variant="ghost" size="sm" @click="viewProposal(p)">
                {{ t('skillEvo.view') }}
              </GlassButton>
              <GlassButton variant="primary" size="sm" @click="decideProposal(p.proposal_id, true)">
                {{ t('skillEvo.approve') }}
              </GlassButton>
              <GlassButton variant="secondary" size="sm" @click="decideProposal(p.proposal_id, false)">
                {{ t('skillEvo.reject') }}
              </GlassButton>
            </div>
          </div>
        </div>
        <a-empty v-else :description="t('skillEvo.noProposals')" />
      </a-spin>
    </a-modal>

    <!-- 提案详情 Modal（改进前后对照） -->
    <a-modal
      v-model:open="detailVisible"
      :title="t('skillEvo.proposalDetail')"
      width="860px"
      :footer="null"
    >
      <template v-if="proposalDetail">
        <p class="proposal-metric">
          {{ t('skillEvo.holdout') }}: {{ proposalDetail.holdout_before }} →
          {{ proposalDetail.holdout_after }}
        </p>
        <a-row :gutter="12">
          <a-col :span="12">
            <div class="evo-diff-title">{{ t('skillEvo.baseline') }}</div>
            <pre class="evo-diff-body">{{ proposalDetail.baseline_text }}</pre>
          </a-col>
          <a-col :span="12">
            <div class="evo-diff-title evo-diff-new">{{ t('skillEvo.improved') }}</div>
            <pre class="evo-diff-body">{{ proposalDetail.improved_text }}</pre>
          </a-col>
        </a-row>
        <div class="proposal-detail-actions">
          <GlassButton variant="primary" size="sm" @click="decideProposal(proposalDetail.proposal_id, true)">
            {{ t('skillEvo.approve') }}
          </GlassButton>
          <GlassButton variant="secondary" size="sm" @click="decideProposal(proposalDetail.proposal_id, false)">
            {{ t('skillEvo.reject') }}
          </GlassButton>
        </div>
      </template>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import * as skillPoolApi from '@/api/modules/skill-pool'
import * as evolutionApi from '@/api/modules/text-evolution'
import type { EvolutionSettings, ProposalSummary, EvolutionProposal } from '@/api/modules/text-evolution'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import GlassStatCard from '@/components/GlassStatCard.vue'

interface SkillUsage {
  state?: string
  pinned?: boolean
  created_by?: string
  use_count?: number
  last_activity_at_ms?: number
}

interface Skill {
  id: string
  name: string
  description: string
  enabled: boolean
  execution_count?: number
  usage?: SkillUsage
  _toggling?: boolean
  _pinning?: boolean
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
    // 后端契约字段是 skill_id(SkillInfo);归一化为前端统一 id,
    // 并合并生命周期 usage(状态/钉住/来源/使用次数)
    const usageMap = await fetchLifecycleUsage()
    skills.value = (Array.isArray(data) ? data : data?.items ?? []).map((s: any) => {
      const id = s.skill_id ?? s.id ?? ''
      return {
        ...s,
        id,
        usage: usageMap[id] ?? s.usage ?? undefined,
        _toggling: false,
        _pinning: false,
      }
    })
  } catch (err: any) {
    const msg = err?.response?.data?.error || err?.message || t('skill.loadError')
    message.error(msg)
  } finally {
    loading.value = false
  }
}

async function fetchLifecycleUsage(): Promise<Record<string, SkillUsage>> {
  try {
    const res = await evolutionApi.getLifecycleUsage(props.agentId)
    const summary = (res as any)?.data ?? res
    const map: Record<string, SkillUsage> = {}
    for (const item of summary?.skills ?? []) {
      map[item.skill_id] = item
    }
    return map
  } catch {
    return {} // 生命周期面不可用时,列表仍可展示启用态
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

// ── 文本进化 / 生命周期 / 提案审批 ──

const settingsVisible = ref(false)
const settingsLoading = ref(false)
const settingsSaving = ref(false)
const settings = ref<EvolutionSettings | null>(null)

const sweepRunning = ref(false)

const proposalsVisible = ref(false)
const proposalsLoading = ref(false)
const proposals = ref<ProposalSummary[]>([])
const proposalDetail = ref<EvolutionProposal | null>(null)
const detailVisible = ref(false)

const evolveVisible = ref(false)
const evolveRunning = ref(false)
const evolveTarget = ref<Skill | null>(null)
const evolveIterations = ref<number>(5)
const evolveSource = ref<'auto' | 'golden' | 'mined' | 'synthetic'>('auto')
const evolveResult = ref<string | null>(null)

function stateOf(skill: Skill): string {
  return skill.usage?.state || 'active'
}

function stateColor(state: string): string {
  return state === 'archived' ? 'red' : state === 'stale' ? 'orange' : 'green'
}

function stateLabel(state: string): string {
  const map: Record<string, string> = {
    active: t('skillEvo.stateActive'),
    stale: t('skillEvo.stateStale'),
    archived: t('skillEvo.stateArchived'),
  }
  return map[state] ?? state
}

function rejectReasonText(reason: string): string {
  const map: Record<string, string> = {
    disabled: t('skillEvo.rejectDisabled'),
    no_improvement: t('skillEvo.rejectNoImprovement'),
    holdout_regression: t('skillEvo.rejectHoldoutRegression'),
    bench_regression: t('skillEvo.rejectBenchRegression'),
    empty_dataset: t('skillEvo.rejectEmptyDataset'),
    constraint_failed: t('skillEvo.rejectConstraintFailed'),
  }
  return map[reason] ?? t('skillEvo.rejected', { reason })
}

function useCountOf(skill: Skill): number {
  return skill.usage?.use_count ?? skill.execution_count ?? 0
}

async function togglePin(skill: Skill) {
  skill._pinning = true
  try {
    const next = !skill.usage?.pinned
    await evolutionApi.pinSkill(props.agentId, skill.id, next)
    skill.usage = { ...(skill.usage ?? {}), pinned: next }
    message.success(t('skillEvo.pinSuccess'))
  } catch (err: any) {
    const msg = err?.response?.data?.error || err?.message || t('skillEvo.pinError')
    message.error(msg)
  } finally {
    skill._pinning = false
  }
}

async function openSettings() {
  settingsVisible.value = true
  settingsLoading.value = true
  try {
    const res = await evolutionApi.getEvolutionSettings()
    settings.value = ((res as any)?.data ?? res) as EvolutionSettings
  } catch (err: any) {
    const msg = err?.response?.data?.error || err?.message || t('skillEvo.loadError')
    message.error(msg)
  } finally {
    settingsLoading.value = false
  }
}

async function saveSettings() {
  if (!settings.value) return
  settingsSaving.value = true
  try {
    const res = await evolutionApi.updateEvolutionSettings(settings.value)
    settings.value = ((res as any)?.data ?? res) as EvolutionSettings
    message.success(t('skillEvo.saveSuccess'))
  } catch (err: any) {
    const msg = err?.response?.data?.error || err?.message || t('skillEvo.saveError')
    message.error(msg)
  } finally {
    settingsSaving.value = false
  }
}

async function runSweep() {
  sweepRunning.value = true
  try {
    const res = await evolutionApi.runLifecycleSweep(props.agentId)
    const c = ((res as any)?.data ?? res) as Record<string, number>
    message.success(
      t('skillEvo.sweepDone', {
        stale: c.marked_stale ?? 0,
        archived: c.archived ?? 0,
        reactivated: c.reactivated ?? 0,
      }),
    )
    await refreshSkills()
  } catch (err: any) {
    const msg = err?.response?.data?.error || err?.message || t('skillEvo.sweepError')
    message.error(msg)
  } finally {
    sweepRunning.value = false
  }
}

function openEvolve(skill: Skill) {
  evolveTarget.value = skill
  evolveResult.value = null
  evolveVisible.value = true
}

async function runEvolve() {
  if (!evolveTarget.value) return
  evolveRunning.value = true
  evolveResult.value = null
  try {
    const res = await evolutionApi.evolveSkill(props.agentId, {
      skill_id: evolveTarget.value.id,
      iterations: evolveIterations.value,
      dataset_source: evolveSource.value,
    })
    const data = ((res as any)?.data ?? res) as import('@/api/modules/text-evolution').EvolutionRunData
    if (data.rejected) {
      const reason = data.reject_reason || 'rejected'
      evolveResult.value = rejectReasonText(reason)
    } else if (data.proposal) {
      evolveResult.value = t('skillEvo.accepted', {
        before: data.holdout_before,
        after: data.holdout_after,
      })
      await refreshProposals()
    } else {
      evolveResult.value = t('skillEvo.noChange')
    }
  } catch (err: any) {
    const msg = err?.response?.data?.detail || err?.response?.data?.error || err?.message || t('skillEvo.evolveError')
    message.error(msg)
  } finally {
    evolveRunning.value = false
  }
}

async function refreshProposals() {
  proposalsLoading.value = true
  try {
    const res = await evolutionApi.listProposals(props.agentId, 'pending')
    proposals.value = ((res as any)?.data ?? res) as ProposalSummary[]
  } catch (err: any) {
    const msg = err?.response?.data?.error || err?.message || t('skillEvo.loadError')
    message.error(msg)
  } finally {
    proposalsLoading.value = false
  }
}

async function openProposals() {
  proposalsVisible.value = true
  await refreshProposals()
}

async function viewProposal(p: ProposalSummary) {
  try {
    const res = await evolutionApi.getProposal(props.agentId, p.proposal_id)
    proposalDetail.value = ((res as any)?.data ?? res) as EvolutionProposal
    detailVisible.value = true
  } catch (err: any) {
    const msg = err?.response?.data?.error || err?.message || t('skillEvo.loadError')
    message.error(msg)
  }
}

async function decideProposal(proposalId: string, approve: boolean) {
  try {
    if (approve) await evolutionApi.approveProposal(props.agentId, proposalId)
    else await evolutionApi.rejectProposal(props.agentId, proposalId)
    message.success(approve ? t('skillEvo.approved') : t('skillEvo.rejectedOk'))
    detailVisible.value = false
    await refreshProposals()
    await refreshSkills()
  } catch (err: any) {
    const msg = err?.response?.data?.error || err?.message || t('skillEvo.decideError')
    message.error(msg)
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
  gap: 8px;
}

.skill-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
}

.skill-action-buttons {
  display: flex;
  gap: 6px;
  align-items: center;
}

.evo-hint {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--nr-text-tertiary);
}

.proposal-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 420px;
  overflow-y: auto;
}

.proposal-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--nr-glass-border);
  border-radius: 8px;
}

.proposal-skill {
  font-weight: 600;
  color: var(--nr-text-primary);
}

.proposal-metric {
  font-size: 12px;
  color: var(--nr-text-secondary);
}

.proposal-actions {
  display: flex;
  gap: 6px;
}

.proposal-detail-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}

.evo-diff-title {
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 4px;
  color: var(--nr-text-secondary);
}

.evo-diff-new {
  color: #10b981;
}

.evo-diff-body {
  max-height: 320px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 12px;
  padding: 8px;
  border: 1px solid var(--nr-glass-border);
  border-radius: 8px;
  margin: 0;
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

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
          <GlassButton variant="secondary" size="sm" @click="openConsolidation">
            {{ t('skillEvo.consolidation') }}
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

    <!-- Domain Harnesses: adopted harnesses across domains (read-only) -->
    <GlassPanel class="domain-harness-panel">
      <div class="domain-harness-title">{{ t('skill.domainHarnesses') }}</div>
      <div class="toolbar-row">
        <a-input-search
          v-model:value="harnessQuery"
          :placeholder="t('skill.domainHarnessesHint')"
          allow-clear
          style="max-width: 360px"
          @search="loadDomainHarnesses"
        />
      </div>
      <a-spin :spinning="harnessLoading">
        <div v-if="domainHarnesses.length" class="domain-harness-list">
          <div v-for="item in domainHarnesses" :key="item.skill_id" class="domain-harness-item">
            <div class="domain-harness-head">
              <strong>{{ item.name || item.skill_id }}</strong>
              <a-tag color="green">{{ item.domain }}</a-tag>
              <span class="domain-harness-version">v{{ item.version }}</span>
              <a-select
                v-model:value="adoptTargetId"
                size="small"
                style="width: 150px"
                :options="skillOptions"
                :placeholder="t('skillEvo.adoptTarget')"
              />
              <GlassButton variant="secondary" size="sm" @click="adoptHarness(item)">
                {{ t('skillEvo.adopt') }}
              </GlassButton>
            </div>
            <div class="domain-harness-desc">{{ item.description }}</div>
          </div>
        </div>
        <div v-else class="domain-harness-empty">{{ t('skill.noSkills') }}</div>
      </a-spin>
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
                <!-- 「已启用」不等于「能跑」：账本在册而落盘无构件时如实标出来，
                     原因走 title 透出（后端 `unavailable_reason` 是单点判定的读数，前端不自己猜） -->
                <a-tag v-if="skill.available === false" color="orange" :title="skill.unavailable_reason || ''">
                  {{ t('skill.artifactMissing') }}
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
                <GlassButton
                  variant="ghost"
                  size="sm"
                  @click="openArchive(skill.id)"
                >
                  {{ t('skillEvo.archive') }}
                </GlassButton>
                <GlassButton
                  variant="ghost"
                  size="sm"
                  :loading="skill._pushing"
                  @click="pushToMyLibrary(skill)"
                >
                  {{ t('skill.pushToMine') }}
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
              <div class="proposal-skill">
                {{ p.skill_id }}
                <a-tag v-if="p.requires_manual_review" color="orange">
                  {{ t('skillEvo.manualReviewRequired') }}
                </a-tag>
              </div>
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

    <!-- 待审技能合并计划 Modal（P1-2：重复技能收敛为类级 umbrella） -->
    <a-modal
      v-model:open="consolidationVisible"
      :title="t('skillEvo.consolidation')"
      :footer="null"
      width="720px"
    >
      <p class="evo-hint">{{ t('skillEvo.consolidationHint') }}</p>
      <a-spin :spinning="consolidationLoading">
        <div v-if="consolidationPlans.length" class="proposal-list">
          <div v-for="p in consolidationPlans" :key="p.umbrella" class="proposal-row">
            <div class="consolidation-info">
              <div class="proposal-skill">{{ p.umbrella }}</div>
              <div class="skill-tags">
                <a-tag :color="basisColor(p.basis)">{{ basisLabel(p.basis) }}</a-tag>
                <a-tag color="purple">
                  {{ t('skillEvo.consolidationAbsorbed') }}: {{ (p.absorbed ?? []).length }}
                </a-tag>
              </div>
              <div class="proposal-metric">{{ p.reason }}</div>
              <div class="proposal-metric consolidation-members">
                {{ (p.absorbed ?? []).join('、') }}
              </div>
            </div>
            <div class="proposal-actions">
              <GlassButton
                variant="primary"
                size="sm"
                :loading="consolidationBusy === p.umbrella"
                @click="decideConsolidation(p, true)"
              >
                {{ t('skillEvo.consolidationApprove') }}
              </GlassButton>
              <GlassButton
                variant="secondary"
                size="sm"
                :disabled="consolidationBusy === p.umbrella"
                @click="decideConsolidation(p, false)"
              >
                {{ t('skillEvo.reject') }}
              </GlassButton>
            </div>
          </div>
        </div>
        <a-empty v-else :description="t('skillEvo.consolidationEmpty')" />
      </a-spin>
    </a-modal>

    <!-- 归档与回滚 Modal（工单 011：归档读面 + 回滚写面） -->
    <a-modal
      v-model:open="archiveVisible"
      :title="`${t('skillEvo.archiveTitle')}: ${archiveSkillId}`"
      :footer="null"
      width="640px"
    >
      <a-spin :spinning="archiveLoading">
        <div v-if="archiveEntries.length" class="proposal-list">
          <div v-for="entry in archiveEntries" :key="entry.version" class="proposal-row">
            <div class="consolidation-info">
              <div class="proposal-skill">
                {{ t('skillEvo.archiveVersion') }} {{ entry.version }}
              </div>
              <div class="proposal-metric">{{ entry.description }}</div>
              <div class="proposal-metric">
                {{ t('skillEvo.archiveArchivedAt') }}: {{ formatArchivedAt(entry.archived_at) }}
              </div>
            </div>
            <div class="proposal-actions">
              <a-popconfirm
                :title="t('skillEvo.rollbackConfirm')"
                :ok-text="t('skillEvo.rollback')"
                :cancel-text="t('common.cancel')"
                :disabled="rollingBack"
                @confirm="confirmRollback"
              >
                <GlassButton
                  variant="secondary"
                  size="sm"
                  :loading="rollingBack"
                  :disabled="rollingBack"
                >
                  {{ t('skillEvo.rollback') }}
                </GlassButton>
              </a-popconfirm>
            </div>
          </div>
        </div>
        <a-empty v-else :description="t('skillEvo.archiveEmpty')" />
      </a-spin>
      <a-alert v-if="archiveResult" type="success" :message="archiveResult" show-icon />
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
        <!-- 那次进化的审计运行（runs/*.json 的读者；§6-95 后半）。三态各自出声：
             取回了 ⇒ 逐例读数；文件不见了 / 本轮未记 ⇒ 点名，不静默省略。 -->
        <p v-if="auditRunState === 'attached'" class="proposal-metric">
          {{ t('skillEvo.auditRun') }} · {{ auditRun?.at }} ·
          {{ t('skillEvo.auditRunCases') }}:
          <span v-for="(reading, task) in auditRunCases" :key="task">
            {{ task }} {{ reading.baseline }}→{{ reading.candidate }}{{ reading.candidate_failed ? '✗' : '' }}
          </span>
        </p>
        <p v-if="auditRunNote" class="proposal-metric">{{ auditRunNote }}</p>
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
        <div class="ab-verify">
          <div class="ab-verify-head">
            <span class="evo-diff-title">{{ t('skillEvo.abVerify') }}</span>
            <GlassButton
              variant="secondary"
              size="sm"
              :disabled="abLoading !== ''"
              @click="runAbArm('simulated')"
            >
              {{ t('skillEvo.abRunSimulated') }}
            </GlassButton>
            <GlassButton
              variant="secondary"
              size="sm"
              :disabled="abLoading !== ''"
              @click="runAbArm('real_agent')"
            >
              {{ t('skillEvo.abRunReal') }}
            </GlassButton>
          </div>
          <p class="proposal-metric">{{ t('skillEvo.abHint') }}</p>
          <p v-if="abError" class="ab-error">{{ abError }}</p>
          <div v-for="report in abReportRows" :key="report.executor_kind" class="ab-arm">
            <div class="ab-arm-title">
              {{ t('skillEvo.abExecutor') }}:
              {{
                report.executor_kind === 'real_agent'
                  ? t('skillEvo.abKindReal')
                  : t('skillEvo.abKindSimulated')
              }}
              <span class="proposal-metric">
                · {{ t('skillEvo.abMetricN') }} {{ report.n }}
                · {{ t('skillEvo.abMetricBaseline') }} {{ report.baseline_avg }}
                · {{ t('skillEvo.abMetricCandidate') }} {{ report.candidate_avg }}
                · {{ t('skillEvo.abMetricDelta') }}
                  {{ report.delta >= 0 ? '+' : '' }}{{ report.delta }}
              </span>
            </div>
            <table class="ab-table">
              <thead>
                <tr>
                  <th>{{ t('skillEvo.abTaskCol') }}</th>
                  <th>{{ t('skillEvo.baseline') }}</th>
                  <th>{{ t('skillEvo.improved') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in report.per_task" :key="row.task_input">
                  <td>{{ row.task_input }}</td>
                  <td>{{ row.baseline }}</td>
                  <td>{{ row.candidate }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
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
import * as governanceApi from '@/api/modules/governance'
import type { EvolutionSettings, ProposalSummary, EvolutionProposal, AbReportData, ArmExecutorKind } from '@/api/modules/text-evolution'
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
  // 后端对账读数（单点 `SkillService.availabilityFor`）：`enabled` 是运营开关，
  // `available` 是"这条真能变成一个动得了的执行体"——两件事，两格都要显示得出。
  available?: boolean
  unavailable_reason?: string
  execution_count?: number
  usage?: SkillUsage
  _toggling?: boolean
  _pinning?: boolean
  _pushing?: boolean
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
const harnessQuery = ref('')
const domainHarnesses = ref<skillPoolApi.DomainHarness[]>([])
const harnessLoading = ref(false)
const adoptTargetId = ref('')
const skillOptions = computed(() =>
  skills.value.map((s) => ({ value: s.id, label: s.name })),
)

async function adoptHarness(item: skillPoolApi.DomainHarness) {
  if (!adoptTargetId.value) {
    message.warning(t('skillEvo.adoptTarget'))
    return
  }
  try {
    await evolutionApi.adoptDomainHarness(
      props.agentId, item.skill_id, adoptTargetId.value,
    )
    message.success(t('skillEvo.adoptSuccess'))
    openProposals()
  } catch (err: any) {
    const detail = err?.response?.data?.detail || err?.message
    message.error(detail || t('skillEvo.adoptError'))
  }
}

async function loadDomainHarnesses() {
  harnessLoading.value = true
  try {
    const res = await skillPoolApi.searchAgentDomainHarnesses(props.agentId, {
      query: harnessQuery.value,
      limit: 5,
    })
    const data: any = (res as any)?.data ?? res
    domainHarnesses.value = Array.isArray(data) ? data : data?.items ?? []
  } catch {
    domainHarnesses.value = []
  } finally {
    harnessLoading.value = false
  }
}

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
    if (!adoptTargetId.value && skills.value.length) {
      adoptTargetId.value = skills.value[0].id
    }
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
    await skillPoolApi.enableSkill(skill.id, enabled, props.agentId)
    skill.enabled = enabled
    message.success(enabled ? t('skill.enabledSuccess') : t('skill.disabledSuccess'))
  } catch (err: any) {
    const msg = err?.response?.data?.error || err?.message || t('skill.toggleError')
    message.error(msg)
  } finally {
    skill._toggling = false
  }
}

/** 三层库需求 3：agent 私库技能→我的用户私库（经确认队列，非直接复制）。 */
async function pushToMyLibrary(skill: Skill) {
  skill._pushing = true
  try {
    await skillPoolApi.createSkillTransfer({
      transfer_type: 'agent_to_user',
      skill_id: skill.id,
      src_pool: 'agent',
      src_owner: props.agentId,
    })
    message.success(t('skill.pushSubmitted'))
  } catch (err: any) {
    const msg = err?.response?.data?.detail || err?.response?.data?.error || err?.message || t('skill.pushError')
    message.error(msg)
  } finally {
    skill._pushing = false
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

// §6-95 后半：那次进化的审计运行在详情面被读出来。三态各自出声——
// 取回了 ⇒ 逐例读数；`missing` ⇒ 明说"文件取不回"；`none_recorded` ⇒ 明说"本轮未记"。
// 静默省略等于把审计面的缺失洗成"看起来没有这回事"，审批人无从分辨。
const auditRunState = computed(() => proposalDetail.value?.evolution_run_status ?? '')
const auditRun = computed(() => proposalDetail.value?.evolution_run ?? null)
const auditRunCases = computed(() => auditRun.value?.holdout_cases ?? {})
const auditRunNote = computed(() => {
  if (auditRunState.value === 'missing') return t('skillEvo.auditRunMissing')
  if (auditRunState.value === 'none_recorded') return t('skillEvo.auditRunNoneRecorded')
  if (auditRunState.value === 'attached' && auditRun.value?.judge_available === false) {
    return t('skillEvo.auditRunJudgeDown')
  }
  return ''
})

// 双臂核验：模拟面与真 agent 轨迹面各占一栏，永不合并成一个数字——
// 两个面量的是不同的事，混标会让审批人拿模拟分当线上证据（不可逆的是解释）。
const abReports = ref<Record<ArmExecutorKind, AbReportData | null>>({
  simulated: null,
  real_agent: null,
})
const abLoading = ref<ArmExecutorKind | ''>('')
const abError = ref('')

/** 已跑出来的臂（最多两栏，各带自己的来源标签；两栏并存才看得出两个面在说不同的话）。 */
const abReportRows = computed<AbReportData[]>(() =>
  [abReports.value.simulated, abReports.value.real_agent].filter(
    (r): r is AbReportData => !!r,
  ),
)

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
      // a-input-number 清空后是 null——钳到默认,避免后端 422
      iterations: evolveIterations.value || 5,
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
    if (data.real_trajectory_fallback) {
      message.warning(t('skillEvo.realTrajectoryFallback', {
        reason: data.real_trajectory_fallback,
      }))
    }
    if (data.proposal?.requires_manual_review) {
      message.info(t('skillEvo.manualReviewRequired'))
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
    // 每开一条提案都清空上一臂的读数：留在屏上就等于把 A 提案的核验结果挂到 B 提案上
    resetAbReports()
    detailVisible.value = true
  } catch (err: any) {
    const msg = err?.response?.data?.error || err?.message || t('skillEvo.loadError')
    message.error(msg)
  }
}

function resetAbReports() {
  abReports.value = { simulated: null, real_agent: null }
  abLoading.value = ''
  abError.value = ''
}

async function runAbArm(kind: ArmExecutorKind) {
  const detail = proposalDetail.value
  if (!detail) return
  // 详情面里正文是可选字段（列表页为省带宽不剥它）；没有候选正文就没有"双臂"可跑，
  // 直接说明，而不是拿空串去撞后端 422
  const candidate = (detail.improved_text || '').trim()
  if (!candidate) {
    abError.value = t('skillEvo.abNoCandidate')
    return
  }
  abLoading.value = kind
  abError.value = ''
  try {
    const res = await evolutionApi.abCompareSkills(props.agentId, {
      skill_id: detail.skill_id,
      candidate_text: candidate,
      real_trajectory: kind === 'real_agent',
    })
    const report = ((res as any)?.data ?? res) as AbReportData
    // 来源以**报告**为准，不按请求参数回填：服务端回落成模拟面时，标签必须跟着事实走
    if (report.executor_kind === 'real_agent') abReports.value.real_agent = report
    else abReports.value.simulated = report
    if (report.executor_kind !== kind) {
      abError.value = t('skillEvo.abKindMismatch')
    }
  } catch (err: any) {
    abError.value = err?.response?.data?.detail
      || err?.response?.data?.error
      || err?.message
      || t('skillEvo.abFailed')
  } finally {
    abLoading.value = ''
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

// ── 技能合并审批面（P1-2：RSI 产计划、本处批准/拒绝执行）──

const consolidationVisible = ref(false)
const consolidationLoading = ref(false)
const consolidationBusy = ref('')
const consolidationPlans = ref<skillPoolApi.ConsolidationPlan[]>([])

function basisLabel(basis?: string): string {
  const map: Record<string, string> = {
    identity: t('skillEvo.consolidationBasisIdentity'),
    structure: t('skillEvo.consolidationBasisStructure'),
    name_prefix: t('skillEvo.consolidationBasisNamePrefix'),
  }
  return (basis && map[basis]) || basis || ''
}

function basisColor(basis?: string): string {
  return basis === 'identity' ? 'green' : basis === 'structure' ? 'orange' : 'default'
}

async function openConsolidation() {
  consolidationVisible.value = true
  await refreshConsolidation()
}

async function refreshConsolidation() {
  consolidationLoading.value = true
  try {
    const res = await skillPoolApi.listConsolidationPlans(props.agentId)
    const data: any = (res as any)?.data ?? res
    // 只展示待审件（后端落盘仓含已批/已拒的历史条目）
    consolidationPlans.value = (Array.isArray(data) ? data : []).filter(
      (p: any) => !p?.status || p.status === 'pending',
    )
  } catch (err: any) {
    const msg = err?.response?.data?.detail || err?.response?.data?.error || err?.message
      || t('skillEvo.consolidationError')
    message.error(msg)
  } finally {
    consolidationLoading.value = false
  }
}

async function decideConsolidation(p: skillPoolApi.ConsolidationPlan, approve: boolean) {
  consolidationBusy.value = p.umbrella
  try {
    if (approve) await skillPoolApi.approveConsolidation(props.agentId, p.umbrella)
    else await skillPoolApi.rejectConsolidation(props.agentId, p.umbrella)
    message.success(
      approve ? t('skillEvo.consolidationApproved') : t('skillEvo.consolidationRejected'),
    )
    await refreshConsolidation()
    await refreshSkills()
  } catch (err: any) {
    const msg = err?.response?.data?.detail || err?.response?.data?.error || err?.message
      || t('skillEvo.consolidationError')
    message.error(msg)
  } finally {
    consolidationBusy.value = ''
  }
}

// ── 归档与回滚（工单 011：读面在 governance，写面同样）──

const archiveVisible = ref(false)
const archiveLoading = ref(false)
const rollingBack = ref(false)
const archiveSkillId = ref('')
const archiveEntries = ref<governanceApi.SkillArchiveEntry[]>([])
const archiveResult = ref('')

function formatArchivedAt(stamp?: number): string {
  if (!stamp) return '-'
  return new Date(stamp * 1000).toLocaleString()
}

async function openArchive(skillId: string) {
  archiveSkillId.value = skillId
  archiveVisible.value = true
  archiveResult.value = ''
  await refreshArchives()
}

async function refreshArchives() {
  archiveLoading.value = true
  try {
    const res = await governanceApi.getSkillArchives(archiveSkillId.value, props.agentId)
    const payload: any = (res as any)?.data ?? res
    const entries = payload?.archives ?? payload?.data?.archives ?? []
    archiveEntries.value = Array.isArray(entries) ? entries : []
  } catch (err: any) {
    archiveEntries.value = []
    const msg = err?.response?.data?.detail || err?.response?.data?.error || err?.message
      || t('skillEvo.archiveLoadError')
    message.error(msg)
  } finally {
    archiveLoading.value = false
  }
}

async function confirmRollback() {
  rollingBack.value = true
  try {
    const res = await governanceApi.rollbackSkill(
      archiveSkillId.value, currentOperator(), props.agentId,
    )
    const payload: any = (res as any)?.data ?? res
    const left = payload?.archives_left ?? 0
    archiveResult.value = t('skillEvo.rollbackDone', { left })
    message.success(archiveResult.value)
    await refreshArchives()
    await refreshSkills()
  } catch (err: any) {
    const msg = err?.response?.data?.detail || err?.response?.data?.error || err?.message
      || t('skillEvo.rollbackError')
    message.error(msg)
  } finally {
    rollingBack.value = false
  }
}

/** 回滚留痕要记"谁按的"：取当前登录身份，取不到给稳定占位而不是空串。 */
function currentOperator(): string {
  try {
    const raw = localStorage.getItem('auth_user') || localStorage.getItem('user')
    if (raw) {
      const parsed = JSON.parse(raw)
      const name = parsed?.username || parsed?.user_id || parsed?.id
      if (name) return String(name)
    }
  } catch {
    // 非浏览器/脏值：落到占位
  }
  return 'operator'
}

onMounted(() => {
  refreshSkills()
  loadDomainHarnesses()
})

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

.domain-harness-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.domain-harness-title {
  font-weight: 600;
}

.domain-harness-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.domain-harness-item {
  border: 1px solid var(--glass-border, rgba(255, 255, 255, 0.12));
  border-radius: 8px;
  padding: 8px 10px;
}

.domain-harness-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.domain-harness-version,
.domain-harness-desc,
.domain-harness-empty {
  color: var(--text-secondary, #888);
  font-size: 12px;
}

.domain-harness-desc {
  margin-top: 4px;
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

.ab-verify {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--nr-glass-border);
}

.ab-verify-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.ab-error {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--nr-text-secondary);
}

.ab-arm {
  margin-top: 10px;
}

.ab-arm-title {
  font-size: 12px;
  color: var(--nr-text-primary);
}

.ab-table {
  width: 100%;
  font-size: 12px;
  border-collapse: collapse;
}

.ab-table th,
.ab-table td {
  padding: 2px 6px;
  text-align: left;
  color: var(--nr-text-secondary);
  border-bottom: 1px solid var(--nr-glass-border);
}

.consolidation-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.consolidation-members {
  word-break: break-all;
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

<script setup lang="ts">
/**
 * RSI 进化审批面（工单 011）
 *
 * 这页存在的理由：自动调整失效时 RSI 会升级到人工提案，但提案此前只有 PENDING
 * 可见、且批准动作作用在"最后构造的那个 agent"上 —— 人工通道等于不存在。
 * 所以本页把三件事摆明：选哪个 agent、提案现在什么状态、批准之后是否真的生效。
 *
 * 部署阶段（rsi_phase）在此只读：写仍归 SettingPage 的治理卡片，两处可改迟早漂移。
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassCard from '@/components/GlassCard.vue'
import { useAuthStore } from '@/stores/auth'
import {
  approveRsiProposal,
  getRsiStatus,
  listRsiProposals,
  rejectRsiProposal,
  type ProposalStateFilter,
  type RsiApproveEvidence,
  type RsiProposal,
  type RsiStatus,
} from '@/api/modules/rsiGovernance'

const { t } = useI18n()
const auth = useAuthStore()

const FILTERS: ProposalStateFilter[] = ['all', 'pending', 'applied', 'rejected', 'rolled_back']

const agentId = ref('')
const stateFilter = ref<ProposalStateFilter>('all')
const status = ref<RsiStatus | null>(null)
const proposals = ref<RsiProposal[]>([])
const loading = ref(false)
/** 后端 503 的原因原文；不咽成"没有提案" */
const notReady = ref('')
/** 批准后的生效证据：proposal_id → { 装进去的技能 id, 注册表是否命中 } */
const evidence = ref<Record<string, { skillId: string; hit: boolean }>>({})
/** manifest 缺 tool_sequence 时由批准人补交（逗号分隔） */
const sequenceDraft = ref<Record<string, string>>({})

const approver = computed(() => auth.user?.username || 'admin')

/** 状态筛选的显示名 —— 键保持 `section.key` 两层结构（语言包一致性守卫的约定） */
const STATE_KEYS: Record<ProposalStateFilter, string> = {
  all: 'stateAll',
  pending: 'statePending',
  applied: 'stateApplied',
  rejected: 'stateRejected',
  rolled_back: 'stateRolledBack',
}

function stateLabel(item: ProposalStateFilter): string {
  return t(`rsiGovernance.${STATE_KEYS[item]}`)
}

/**
 * 参数活性读数（Issue #289 · 004 M3）的取值文案映射。
 *
 * `no_data` / `sparse` / `never_proposed` 必须各有一条独立文案 —— 折叠成
 * 同一个"未知"就把"判不了"和"从未提名"混成一件事，正是本仓在 success 三态上
 * 修过的同一病灶。
 */
const ACTIVITY_KEYS: Record<string, string> = {
  moving: 'paramActivityMoving',
  sparse: 'paramActivitySparse',
  never_proposed: 'paramActivityNeverProposed',
  no_data: 'paramActivityNoData',
}

function activityLabel(value: string | undefined): string {
  if (!value) return t('rsiGovernance.paramActivityNoData')
  return t(`rsiGovernance.${ACTIVITY_KEYS[value] || 'paramActivityNoData'}`)
}

/**
 * 响应拆包。
 *
 * `api` 的响应拦截器返回 `response.data`（即 `{code, data}` 这个 body），
 * 而声明处仍按 `ApiResponse<T>` 泛型写 —— 两者对不上，于是本仓库既有页面
 * 一律做"两层或一层都试"的拆包（见 SettingPage 的 `?.data?.data ?? ?.data`）。
 * 这里跟随同一口径，不再自造第三种解释。
 */
function unwrap<T>(res: unknown): T {
  const box = res as { data?: { data?: T } | T } | undefined
  const nested = (box?.data as { data?: T } | undefined)?.data
  return (nested ?? box?.data) as T
}

function errorText(err: unknown): string {
  const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return detail || (err as Error)?.message || String(err)
}

function hasExecutableSequence(proposal: RsiProposal): boolean {
  return /tool_sequence\s*:/.test(String(proposal.content || ''))
}

async function load() {
  loading.value = true
  notReady.value = ''
  const scoped = agentId.value || undefined
  try {
    const [statusResp, listResp] = await Promise.all([
      getRsiStatus(scoped),
      listRsiProposals({ state: stateFilter.value, agentId: scoped }),
    ])
    status.value = unwrap<RsiStatus>(statusResp)
    proposals.value = unwrap<{ proposals: RsiProposal[] }>(listResp).proposals
  } catch (err) {
    status.value = null
    proposals.value = []
    notReady.value = errorText(err)
  } finally {
    loading.value = false
  }
}

async function approve(proposal: RsiProposal) {
  const sequence = (sequenceDraft.value[proposal.proposal_id] || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
  try {
    const resp = await approveRsiProposal(proposal.proposal_id, {
      approvedBy: approver.value,
      toolSequence: sequence.length ? sequence : undefined,
      agentId: agentId.value || undefined,
    })
    const data = unwrap<RsiApproveEvidence>(resp)
    evidence.value = {
      ...evidence.value,
      [proposal.proposal_id]: { skillId: data.applied_skill_id || '', hit: !!data.registry_hit },
    }
    message.success(t('rsiGovernance.approveOk'))
    await load()
  } catch (err) {
    // 后端拒绝（not_supported / 回灌未成功）必须原样出声，不得记成已批准
    message.error(`${t('rsiGovernance.approveFailed')}：${errorText(err)}`)
  }
}

async function reject(proposal: RsiProposal) {
  try {
    await rejectRsiProposal(proposal.proposal_id, {
      reason: t('rsiGovernance.rejectReason'),
      agentId: agentId.value || undefined,
    })
    message.success(t('rsiGovernance.rejectOk'))
    await load()
  } catch (err) {
    message.error(`${t('rsiGovernance.rejectFailed')}：${errorText(err)}`)
  }
}

onMounted(load)
</script>

<template>
  <div class="rsi-governance-page">
    <GlassCard :title="t('rsiGovernance.title')">
      <p class="rsi-hint">{{ t('rsiGovernance.hint') }}</p>

      <div class="rsi-toolbar">
        <label>
          {{ t('rsiGovernance.agentLabel') }}
          <a-input
            v-model:value="agentId"
            data-testid="rsi-agent"
            :placeholder="t('rsiGovernance.agentPlaceholder')"
            class="rsi-agent-input"
          />
        </label>
        <label>
          {{ t('rsiGovernance.stateLabel') }}
          <a-select v-model:value="stateFilter" data-testid="rsi-state" class="rsi-state-select">
            <a-select-option v-for="item in FILTERS" :key="item" :value="item">
              {{ stateLabel(item) }}
            </a-select-option>
          </a-select>
        </label>
        <a-button data-testid="rsi-reload" :loading="loading" @click="load">
          {{ t('rsiGovernance.reload') }}
        </a-button>
      </div>

      <p v-if="notReady" class="rsi-not-ready" data-testid="rsi-not-ready">
        {{ t('rsiGovernance.notReady') }}：{{ notReady }}
      </p>

      <div v-if="status" class="rsi-status" data-testid="rsi-status">
        <span>{{ t('rsiGovernance.phaseLabel') }}:&nbsp;<a-tag data-testid="rsi-phase">{{ status.deployment_phase }}</a-tag></span>
        <span>
          {{ t('rsiGovernance.verdictLabel') }}:
          <a-tag>{{ status.phase_verdict?.state || '—' }}</a-tag>
          <em>{{ status.phase_verdict?.reason }}</em>
        </span>
        <!-- 落盘失败不得被读成"已晋升"（工单 005 的两态） -->
        <span v-if="status.phase_advanced" data-testid="rsi-persisted">
          {{ status.phase_persisted ? t('rsiGovernance.persistedYes') : t('rsiGovernance.persistedNo') }}
        </span>
        <span data-testid="rsi-pass-rate">
          {{ t('rsiGovernance.passRateLabel') }}: {{ (status.candidates?.pass_rate ?? 0).toFixed(2) }}
        </span>
        <span v-if="status.escalation?.verdict" data-testid="rsi-escalation">
          {{ t('rsiGovernance.escalationLabel') }}: {{ status.escalation.verdict.state }}
          <em>{{ status.escalation.verdict.reason }}</em>
        </span>
        <!-- 回执负债读数（Issue #289 · 003）：账本新增两列而界面看不到，
             就是"只写不读的字段"（AGENTS.md §2 功能与升级改造红线）。 -->
        <span v-if="status.debt" data-testid="rsi-debt">
          {{ t('rsiGovernance.debtLabel') }}:
          <a-tag data-testid="rsi-debt-outstanding">
            {{ status.debt.available === false
              ? t('rsiGovernance.paramActivityNoData')
              : ((status.debt.outstanding ?? 0) > 0 ? status.debt.outstanding : t('rsiGovernance.debtNone')) }}
          </a-tag>
          <em data-testid="rsi-debt-gate">
            {{ status.debt.next_step?.allow
              ? t('rsiGovernance.debtGateAllow')
              : `${t('rsiGovernance.debtGateBlock')}·${status.debt.next_step?.reason || '—'}` }}
          </em>
          <em v-if="status.debt.unknown_rows" data-testid="rsi-debt-legacy">
            {{ t('rsiGovernance.debtUnknownRows') }}: {{ status.debt.unknown_rows }}
          </em>
          <em v-if="status.debt.last_write_failure" data-testid="rsi-debt-write-failure">
            {{ t('rsiGovernance.debtWriteFailure') }}: {{ status.debt.last_write_failure }}
          </em>
        </span>
        <!-- 参数活性读数（Issue #289 · 004 M3）：三态不折叠，缺一态即看不到
             "从未提名"与"判不了"的区别。 -->
        <span v-if="status.parameter_activity" data-testid="rsi-param-activity">
          {{ t('rsiGovernance.paramActivityLabel') }}:
          <a-tag data-testid="rsi-param-activity-overall">
            {{ activityLabel(status.parameter_activity.overall) }}
          </a-tag>
        </span>
      </div>
    </GlassCard>

    <GlassCard :title="t('rsiGovernance.queueTitle')">
      <p v-if="!proposals.length && !notReady" class="rsi-hint" data-testid="rsi-empty">
        {{ t('rsiGovernance.empty') }}
      </p>
      <table class="rsi-table" data-testid="rsi-queue">
        <thead>
          <tr>
            <th>{{ t('rsiGovernance.colTarget') }}</th>
            <th>{{ t('rsiGovernance.colType') }}</th>
            <th>{{ t('rsiGovernance.colRisk') }}</th>
            <th>{{ t('rsiGovernance.colStatus') }}</th>
            <th>{{ t('rsiGovernance.colAction') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in proposals" :key="p.proposal_id" class="rsi-row">
            <td>{{ p.target }}</td>
            <td>{{ p.proposal_type }}</td>
            <td><a-tag>{{ p.risk_level }}</a-tag></td>
            <td data-testid="rsi-row-status">{{ p.status }}</td>
            <td>
              <template v-if="p.status === 'pending'">
                <a-input
                  v-if="!hasExecutableSequence(p)"
                  v-model:value="sequenceDraft[p.proposal_id]"
                  data-testid="rsi-sequence-input"
                  :placeholder="t('rsiGovernance.sequencePlaceholder')"
                  class="rsi-sequence-input"
                />
                <a-button size="small" data-testid="rsi-approve" @click="approve(p)">
                  {{ t('rsiGovernance.approve') }}
                </a-button>
                <a-button size="small" data-testid="rsi-reject" @click="reject(p)">
                  {{ t('rsiGovernance.reject') }}
                </a-button>
              </template>
              <span v-if="evidence[p.proposal_id]" data-testid="rsi-evidence">
                {{ evidence[p.proposal_id].skillId }}
                {{ evidence[p.proposal_id].hit
                  ? t('rsiGovernance.evidenceHit')
                  : t('rsiGovernance.evidenceMiss') }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </GlassCard>
  </div>
</template>

<style scoped>
.rsi-governance-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.rsi-hint {
  opacity: 0.7;
  margin: 0 0 12px;
}
.rsi-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: flex-end;
}
.rsi-toolbar label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
}
.rsi-agent-input {
  width: 180px;
}
.rsi-state-select,
.rsi-sequence-input {
  width: 150px;
}
.rsi-sequence-input {
  width: 200px;
  margin-right: 6px;
}
.rsi-not-ready {
  margin: 12px 0 0;
  color: var(--color-warning, #b8860b);
}
.rsi-status {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-top: 12px;
  font-size: 13px;
}
.rsi-status em {
  opacity: 0.7;
  font-style: normal;
}
.rsi-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.rsi-table th,
.rsi-table td {
  text-align: left;
  padding: 8px;
  border-bottom: 1px solid rgba(128, 128, 128, 0.2);
  vertical-align: top;
}
</style>

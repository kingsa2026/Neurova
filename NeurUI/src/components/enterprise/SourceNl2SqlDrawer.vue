<template>
  <a-drawer
    :open="open"
    :title="`${t('ontology.nl2sqlTitle')} — ${sourceId}`"
    width="760px"
    :destroy-on-close="true"
    @close="emit('close')"
  >
    <!-- 问数入口（P1-4）：门控/权限由后端裁决，403/未开闸在这里如实转述 -->
    <div class="ask-bar">
      <a-input
        v-model:value="question"
        size="sm"
        class="ask-input"
        :placeholder="t('ontology.nl2sqlAskPlaceholder')"
        data-testid="nl2sql-question"
        @press-enter="ask"
      />
      <GlassButton size="sm" variant="primary" :loading="asking" data-testid="nl2sql-ask" @click="ask">
        {{ t('ontology.nl2sqlAskBtn') }}
      </GlassButton>
      <GlassButton
        v-if="isAdmin"
        size="sm"
        variant="secondary"
        :loading="distilling"
        data-testid="nl2sql-patterns"
        @click="distillPatterns"
      >{{ t('ontology.nl2sqlPatternsBtn') }}</GlassButton>
    </div>

    <!-- 门控/权限 403 走 answer 的 refused 通道如实转述，不另设静默提示 -->

    <!-- 答案：状态诚实三态（ok / refused / error），SQL 与步骤始终随行 -->
    <div v-if="answer" class="answer-block" data-testid="nl2sql-answer">
      <div class="answer-head">
        <a-tag v-if="answer.status === 'ok'" color="green">{{ t('ontology.nl2sqlRows') }}: {{ answer.row_count }}</a-tag>
        <a-tag v-else-if="answer.status === 'refused'" color="orange">{{ t('ontology.nl2sqlRefused') }}</a-tag>
        <a-tag v-else color="red">{{ t('ontology.nl2sqlLoadFailed') }}</a-tag>
        <a-tag v-if="answer.status === 'ok' && answer.truncated" color="orange">
          {{ t('ontology.nl2sqlTruncated') }}
        </a-tag>
        <a-tag v-if="answer.status === 'ok' && answer.row_count === 0" color="default">
          {{ t('ontology.nl2sqlEmptyResult') }}
        </a-tag>
      </div>
      <p v-if="answer.explanation" class="explanation">{{ answer.explanation }}</p>
      <p v-if="answer.reason" class="reason" data-testid="nl2sql-reason">{{ answer.reason }}</p>
      <pre v-if="answer.sql" class="sql-block mono" data-testid="nl2sql-sql">{{ answer.sql }}</pre>
      <ol v-if="answer.steps?.length" class="steps" data-testid="nl2sql-steps">
        <li v-for="(step, index) in answer.steps" :key="index">{{ step }}</li>
      </ol>
      <a-table
        v-if="answer.rows?.length"
        :columns="rowColumns"
        :data-source="answer.rows"
        row-key="__row_index"
        size="small"
        :pagination="answer.rows.length > 20 ? { pageSize: 20 } : false"
        class="rows-table"
        data-testid="nl2sql-rows"
      />
    </div>

    <!-- 历史（P2-3 审计面）：问题/SQL/状态/行数 -->
    <div class="history-block">
      <h4 class="history-title">{{ t('ontology.nl2sqlHistoryTitle') }}</h4>
      <a-spin :spinning="historyLoading">
        <div v-if="history.length" class="history-list" data-testid="nl2sql-history">
          <div v-for="row in history" :key="row.query_id" class="history-row">
            <a-tag :color="historyColor(row.status)" class="history-status">{{ row.status }}</a-tag>
            <span class="history-question" :title="row.question">{{ row.question }}</span>
            <span class="mono history-sql" :title="row.sql_text">{{ row.sql_text || '—' }}</span>
            <span class="history-count">{{ row.row_count }}</span>
          </div>
        </div>
        <a-empty v-else-if="!historyLoading" :description="t('ontology.nl2sqlHistoryEmpty')" />
      </a-spin>
    </div>
  </a-drawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassButton from '@/components/GlassButton.vue'
import {
  askNl2Sql,
  listNl2SqlHistory,
  suggestNl2SqlPatterns,
} from '@/api/modules/ontology'
import type { Nl2SqlAnswer, Nl2SqlHistoryRow } from '@/types/ontology'

const props = defineProps<{ open: boolean; sourceId: string; isAdmin: boolean }>()
const emit = defineEmits<{ (e: 'close'): void }>()
const { t } = useI18n()

const asking = ref(false)
const distilling = ref(false)
const historyLoading = ref(false)
const question = ref('')
const answer = ref<Nl2SqlAnswer | null>(null)
const history = ref<Nl2SqlHistoryRow[]>([])

const rowColumns = computed(() => {
  const first = answer.value?.rows?.[0]
  if (!first) return []
  return Object.keys(first).map((key) => ({
    key,
    title: key,
    dataIndex: key,
  }))
})

function historyColor(status: string): string {
  if (status === 'ok') return 'green'
  if (status === 'refused') return 'orange'
  return 'red'
}

async function ask() {
  const text = question.value.trim()
  if (!text) return
  asking.value = true
  try {
    const res = await askNl2Sql(props.sourceId, text)
    answer.value = res.data ?? null
    await loadHistory()
  } catch (e: any) {
    // 403（门控/权限）与 400（校验拒）都如实转述后端 detail，不吞成通用错误
    const detail = e?.response?.data?.detail
    answer.value = {
      answerable: false, sql: '', explanation: '', rows: [], row_count: 0,
      truncated: false, steps: [], status: 'refused',
      reason: typeof detail === 'string' ? detail : t('ontology.nl2sqlLoadFailed'),
    }
  } finally {
    asking.value = false
  }
}

async function distillPatterns() {
  distilling.value = true
  try {
    const res: any = await suggestNl2SqlPatterns(props.sourceId)
    const count = res?.data?.patterns_suggested ?? 0
    message.success(`${t('ontology.nl2sqlPatternsBtn')}: ${count}`)
    await loadHistory()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || t('ontology.nl2sqlLoadFailed'))
  } finally {
    distilling.value = false
  }
}

async function loadHistory() {
  historyLoading.value = true
  try {
    const res = await listNl2SqlHistory(props.sourceId)
    history.value = res.data?.items ?? []
  } catch {
    history.value = []
  } finally {
    historyLoading.value = false
  }
}

watch(() => props.open, (open) => {
  if (open) {
    answer.value = null
    question.value = ''
    void loadHistory()
  }
})
</script>

<style scoped>
.ask-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.ask-input {
  flex: 1;
}
.answer-block {
  padding: 10px 12px;
  border: 1px solid var(--nr-border, rgba(128, 128, 128, 0.25));
  border-radius: 10px;
  margin-bottom: 14px;
}
.answer-head {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
.explanation {
  margin: 0 0 6px;
  font-size: 13px;
}
.reason {
  margin: 0 0 6px;
  font-size: 12px;
  color: var(--nr-text-secondary, inherit);
}
.sql-block {
  margin: 0 0 8px;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--nr-surface, rgba(128, 128, 128, 0.08));
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
}
.steps {
  margin: 0 0 8px;
  padding-left: 18px;
  font-size: 12px;
  color: var(--nr-text-secondary, inherit);
}
.rows-table {
  margin-bottom: 4px;
}
.history-block {
  margin-top: 6px;
}
.history-title {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 600;
}
.history-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.history-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  padding: 6px 8px;
  border: 1px solid var(--nr-border, rgba(128, 128, 128, 0.25));
  border-radius: 8px;
}
.history-question {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.history-sql {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--nr-text-secondary, inherit);
}
.history-count {
  min-width: 32px;
  text-align: right;
}
.mono {
  font-family: var(--nr-font-mono, monospace);
}
</style>

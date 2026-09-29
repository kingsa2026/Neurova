<template>
  <a-modal :open="open" :title="t('channel.migrateDialogTitle')" :footer="null"
    @cancel="dismissMigration">
    <a-spin :spinning="loading">
      <!-- 没有可迁的源：诚实说明，不给假动作（不渲染提交按钮） -->
      <div v-if="!loading && sources.length === 0" data-testid="migration-no-sources">
        <p class="nr-mig-empty-title">{{ t('channel.migrateNoSources') }}</p>
        <p class="nr-mig-empty-hint">{{ t('channel.migrateNoSourcesHint') }}</p>
      </div>

      <template v-else>
        <div class="nr-mig-field">
          <label class="nr-mig-label">{{ t('channel.migrateSource') }}</label>
          <a-select class="source-select" :value="sourceId" style="width: 100%"
            :placeholder="t('channel.migrateSourcePlaceholder')" :options="sourceOptions"
            @change="pickSource" />
        </div>

        <!-- 渠道面只在选定源之后出现：没选源就没有"要迁哪些"这个问题 -->
        <div v-if="sourceId" class="nr-mig-field" data-testid="migration-channels">
          <label class="nr-mig-label">
            {{ t('channel.migrateChannels') }}
            <button class="nr-mig-all" data-testid="migration-select-all" @click="toggleAll">
              {{ allPicked ? t('channel.migrateSelectNone') : t('channel.migrateSelectAll') }}
            </button>
          </label>
          <div class="nr-mig-checks">
            <a-checkbox v-for="name in availableChannels" :key="name" class="chk"
              :data-value="name" :checked="picked.includes(name)" @change="toggleOne(name)">
              {{ name }}
            </a-checkbox>
          </div>
        </div>

        <!-- 失败诚实点名：403（仅属主/管理员）与 409（冲突）都不是"网络错误"。
             归因留在**确认发生的那一屏**（本弹层），而不是背后的页面。 -->
        <p v-if="errorText" class="nr-mig-error" data-testid="migrate-error">{{ errorText }}</p>

        <!-- 提交：未选源或未勾任何渠道时禁用，避免"点了没反应" -->
        <div class="nr-mig-footer">
          <GlassButton variant="ghost" @click="dismissMigration">{{ t('common.cancel') }}</GlassButton>
          <GlassButton variant="primary" data-testid="migration-confirm"
            :disabled="!sourceId || picked.length === 0 || submitting" @click="submit">
            {{ submitting ? t('channel.migrating') : t('channel.migrateConfirm') }}
          </GlassButton>
        </div>
      </template>
    </a-spin>
  </a-modal>
</template>

<script setup lang="ts">
/**
 * 存量渠道迁移弹层（Issue #326 用户口径第 1、2、3 条）。
 *
 * 为什么要有这一层：迁移是不可逆的归属变更（源表清空、目标表接收），
 * 而此前两页的入口都是**一键把 default 整表搬走** —— 源不可选、渠道也不可选。
 * 后端 `channel_types` 早就支持收窄，缺的只是把选择权摆到用户面前。
 *
 * 源清单取自服务端读面（`listChannelMigrationSources`），不前端硬编码 `default`：
 * 归属门在服务端（非属主看不见、无主仅 admin），前端自己猜源只会把
 * 「列出来点下去 403」的假选项摆给用户。
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import GlassButton from '@/components/GlassButton.vue'
import {
  listChannelMigrationSources, migrateAgentChannelConfigs,
} from '@/api/modules/channel-configs'

const props = defineProps<{ open: boolean; targetAgentId: string }>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'migrated', payload: { from: string; to: string; channels: string[] }): void
}>()

const { t } = useI18n()

interface MigrationSource {
  agent_id: string
  channels: string[]
}

const loading = ref(false)
const submitting = ref(false)
const sources = ref<MigrationSource[]>([])
const sourceId = ref('')
const picked = ref<string[]>([])
const errorText = ref('')

const sourceOptions = computed(() => sources.value.map((s) => ({
  value: s.agent_id,
  label: `${s.agent_id} · ${s.channels.length}`,
})))

const availableChannels = computed(
  () => sources.value.find((s) => s.agent_id === sourceId.value)?.channels ?? [],
)
const allPicked = computed(
  () => availableChannels.value.length > 0 && picked.value.length === availableChannels.value.length,
)

async function loadSources() {
  loading.value = true
  sourceId.value = ''
  picked.value = []
  errorText.value = ''
  try {
    const res: any = await listChannelMigrationSources(props.targetAgentId)
    const list = res?.data?.sources ?? res?.sources ?? []
    sources.value = Array.isArray(list) ? list : []
  } catch {
    // 拉不到就是拉不到：不拿「没有可迁的源」掩盖一次失败的请求
    sources.value = []
  } finally {
    loading.value = false
  }
}

function pickSource(value: unknown) {
  sourceId.value = String(value ?? '')
  picked.value = []
  errorText.value = ''
}

function toggleOne(name: string) {
  picked.value = picked.value.includes(name)
    ? picked.value.filter((n) => n !== name)
    : [...picked.value, name]
}

function toggleAll() {
  picked.value = allPicked.value ? [] : [...availableChannels.value]
}

function dismissMigration() {
  emit('close')
}

async function submit() {
  const from = sourceId.value
  if (!from || picked.value.length === 0 || submitting.value) return
  const channels = [...picked.value]
  submitting.value = true
  errorText.value = ''
  try {
    const res: any = await migrateAgentChannelConfigs(from, props.targetAgentId, channels)
    const data = res?.data ?? res
    // 回报**服务端返回的** migrated，不是本地勾选集合：两者在并发下不等
    // （列源与提交之间源表可能已被改动），屏幕与提示必须来自唯一事实源。
    const moved: string[] = Array.isArray(data?.migrated) ? data.migrated : channels
    emit('migrated', { from, to: props.targetAgentId, channels: moved })
  } catch (e: any) {
    // 原样说出原因：409（目标已有同渠道 / 身份冲突）与 403（非属主）
    // 都不是"网络错误"，笼统的"出错了"会诱导用户以为是偶发问题。
    const detail = e?.response?.data?.detail
    errorText.value = t('channel.migrateFailed', {
      reason: String(detail || e?.message || ''),
    })
  } finally {
    submitting.value = false
  }
}

watch(() => props.open, (open) => { if (open) loadSources() }, { immediate: true })
</script>

<style scoped>
.nr-mig-field { margin-bottom: 16px; }
.nr-mig-label {
  display: flex; align-items: center; justify-content: space-between;
  font-size: 13px; color: var(--nr-text-secondary); margin-bottom: 8px;
}
.nr-mig-all {
  background: none; border: none; cursor: pointer; padding: 0;
  color: var(--nr-accent, #6366f1); font-size: 12px;
}
.nr-mig-checks { display: flex; flex-wrap: wrap; gap: 12px; }
.nr-mig-footer { display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px; }
.nr-mig-empty-title { font-size: 14px; font-weight: 600; color: var(--nr-text-primary); }
.nr-mig-empty-hint { font-size: 12px; color: var(--nr-text-tertiary); }
.nr-mig-error { font-size: 12px; color: var(--nr-color-danger, #e11d48); margin-top: 12px; }
</style>

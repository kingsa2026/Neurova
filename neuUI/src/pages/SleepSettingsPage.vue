<template>
  <div class="pg">
    <div class="hd glass-effect">
      <div class="hd-left">
        <SettingOutlined :style="{ color: '#6366f1' }" />
        <h2 class="t">睡眠设置</h2>
      </div>
      <div class="hd-right">
        <a-select
          :value="agentId"
          style="width: 200px"
          placeholder="选择 Agent"
          @change="handleAgentChange"
        >
          <a-select-option
            v-for="agent in agentOptions"
            :key="agent.id || agent.agent_id"
            :value="agent.id || agent.agent_id"
          >
            {{ agent.name }}
          </a-select-option>
        </a-select>
        <a-button type="primary" @click="saveSettings" :loading="saving">
          <CheckOutlined /> 保存设置
        </a-button>
      </div>
    </div>

    <div class="settings-grid">
      <!-- 睡眠阶段时间 -->
      <div class="setting-card glass-effect">
        <div class="card-header">
          <ClockCircleOutlined />
          <h3>睡眠阶段时间</h3>
        </div>
        <a-form layout="vertical">
          <a-form-item label="空闲进入浅睡 (分钟)">
            <a-input-number
              v-model:value="settings.idle_to_light_minutes"
              :min="1"
              :max="120"
              style="width: 100%"
            />
          </a-form-item>
          <a-form-item label="浅睡进入眼动期 (分钟)">
            <a-input-number
              v-model:value="settings.light_to_rem_minutes"
              :min="1"
              :max="120"
              style="width: 100%"
            />
          </a-form-item>
          <a-form-item label="眼动期进入深睡 (分钟)">
            <a-input-number
              v-model:value="settings.rem_to_deep_minutes"
              :min="1"
              :max="120"
              style="width: 100%"
            />
          </a-form-item>
        </a-form>
      </div>

      <!-- 记忆合并 -->
      <div class="setting-card glass-effect">
        <div class="card-header">
          <MergeCellsOutlined />
          <h3>记忆合并</h3>
        </div>
        <a-form layout="vertical">
          <a-form-item label="记忆合并相似度阈值">
            <div class="slider-container">
              <a-slider
                v-model:value="settings.memory_merge_threshold"
                :min="0.5"
                :max="0.99"
                :step="0.01"
                :tooltip-formatter="(v) => `${Math.round(v * 100)}%`"
              />
              <span class="slider-value">{{ Math.round(settings.memory_merge_threshold * 100) }}%</span>
            </div>
          </a-form-item>
          <a-form-item label="记忆冲突解决方式">
            <a-select v-model:value="settings.conflict_resolution" style="width: 100%">
              <a-select-option value="latest">最新为准</a-select-option>
              <a-select-option value="count">数量为准</a-select-option>
              <a-select-option value="consensus">共识机制</a-select-option>
              <a-select-option value="importance">重要性优先</a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item>
            <a-switch
              v-model:checked="settings.memory_consolidation_enabled"
              checked-children="启用"
              un-checked-children="禁用"
            />
            <span class="switch-label">睡眠期间自动整合记忆</span>
          </a-form-item>
        </a-form>
      </div>

      <!-- 睡眠计划 -->
      <div class="setting-card glass-effect">
        <div class="card-header">
          <CalendarOutlined />
          <h3>睡眠计划</h3>
        </div>
        <a-form layout="vertical">
          <a-form-item>
            <a-switch
              v-model:checked="settings.sleep_schedule.enabled"
              checked-children="启用"
              un-checked-children="禁用"
            />
            <span class="switch-label">定时睡眠</span>
          </a-form-item>
          <a-form-item label="入睡时间">
            <a-time-picker
              v-model:value="sleepTime"
              format="HH:mm"
              style="width: 100%"
              placeholder="选择入睡时间"
            />
          </a-form-item>
          <a-form-item label="唤醒时间">
            <a-time-picker
              v-model:value="wakeTime"
              format="HH:mm"
              style="width: 100%"
              placeholder="选择唤醒时间"
            />
          </a-form-item>
        </a-form>
      </div>

      <!-- 高级设置 -->
      <div class="setting-card glass-effect">
        <div class="card-header">
          <ToolOutlined />
          <h3>高级设置</h3>
        </div>
        <a-form layout="vertical">
          <a-form-item>
            <a-switch
              v-model:checked="settings.auto_cleanup_enabled"
              checked-children="启用"
              un-checked-children="禁用"
            />
            <span class="switch-label">自动清理旧梦境</span>
          </a-form-item>
          <a-form-item label="最大保存梦境日志数">
            <a-input-number
              v-model:value="settings.max_dream_logs"
              :min="10"
              :max="1000"
              style="width: 100%"
            />
          </a-form-item>
          <a-form-item>
            <a-switch
              v-model:checked="settings.dream_analysis_enabled"
              checked-children="启用"
              un-checked-children="禁用"
            />
            <span class="switch-label">梦境分析与洞察</span>
          </a-form-item>
        </a-form>
      </div>
    </div>

    <!-- 冲突解决说明 -->
    <div class="explanation-card glass-effect" v-if="showConflictExplanation">
      <div class="explanation-header">
        <InfoCircleOutlined />
        <h4>冲突解决方式说明</h4>
      </div>
      <div class="explanation-content">
        <div class="explanation-item">
          <div class="explanation-title">最新为准</div>
          <div class="explanation-desc">保留最后创建或修改的记忆，丢弃较早的冲突记忆</div>
        </div>
        <div class="explanation-item">
          <div class="explanation-title">数量为准</div>
          <div class="explanation-desc">根据记忆被引用或使用的次数来决定保留哪个记忆</div>
        </div>
        <div class="explanation-item">
          <div class="explanation-title">共识机制</div>
          <div class="explanation-desc">合并多个冲突记忆的共同点，生成一个新的综合记忆</div>
        </div>
        <div class="explanation-item">
          <div class="explanation-title">重要性优先</div>
          <div class="explanation-desc">根据记忆的重要性评分和情感强度来决定保留哪个记忆</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  SettingOutlined, CheckOutlined, ClockCircleOutlined,
  MergeCellsOutlined, CalendarOutlined, ToolOutlined, InfoCircleOutlined
} from '@ant-design/icons-vue'
import dayjs from 'dayjs'
import { sleepAPI, type SleepSettings } from '@/api/modules/sleep'
import { useAgentPage } from '@/composables/useAgentPage'

const router = useRouter()

const { agentId, agentStore, initAgent } = useAgentPage('/agent/:agentId/sleep/settings', () => loadData())

const agentOptions = computed(() => agentStore.agentOptions)

function handleAgentChange(newAgentId: string) {
  agentStore.setCurrentAgent(newAgentId)
  router.push(`/agent/${newAgentId}/sleep/settings`)
}

const saving = ref(false)
const settings = ref<SleepSettings>({
  agent_id: 'default',
  idle_to_light_minutes: 5,
  light_to_rem_minutes: 15,
  rem_to_deep_minutes: 30,
  memory_merge_threshold: 0.8,
  conflict_resolution: 'latest',
  auto_cleanup_enabled: true,
  max_dream_logs: 100,
  dream_analysis_enabled: true,
  memory_consolidation_enabled: true,
  sleep_schedule: {
    enabled: false,
    sleep_time: '23:00',
    wake_time: '07:00',
  },
})

const sleepTime = ref<dayjs.Dayjs | null>(null)
const wakeTime = ref<dayjs.Dayjs | null>(null)

const showConflictExplanation = computed(() => {
  return settings.value.conflict_resolution !== ''
})

watch(() => settings.value.sleep_schedule.sleep_time, (val) => {
  sleepTime.value = val ? dayjs(val, 'HH:mm') : null
})
watch(() => settings.value.sleep_schedule.wake_time, (val) => {
  wakeTime.value = val ? dayjs(val, 'HH:mm') : null
})
watch(sleepTime, (val) => {
  settings.value.sleep_schedule.sleep_time = val ? val.format('HH:mm') : '23:00'
})
watch(wakeTime, (val) => {
  settings.value.sleep_schedule.wake_time = val ? val.format('HH:mm') : '07:00'
})

async function loadData() {
  try {
    const data = await sleepAPI.getSettings(agentId.value)
    settings.value = data
    sleepTime.value = dayjs(data.sleep_schedule.sleep_time, 'HH:mm')
    wakeTime.value = dayjs(data.sleep_schedule.wake_time, 'HH:mm')
  } catch (error) {
    console.error('加载睡眠设置失败:', error)
  }
}

async function saveSettings() {
  saving.value = true
  try {
    await sleepAPI.updateSettings(agentId.value, settings.value)
    message.success('设置已保存')
  } catch (error) {
    message.error('保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await initAgent()
  loadData()
})
</script>

<style scoped>
.pg { display: flex; flex-direction: column; gap: 14px; }

.hd { padding: 16px 24px; border-radius: 12px; display: flex; justify-content: space-between; align-items: center; }
.hd-left { display: flex; align-items: center; gap: 12px; }
.hd-right { display: flex; gap: 12px; }
.t { font-size: 1.2rem; color: #e2e8f0; margin: 0; }

.settings-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; }

.setting-card { padding: 24px; border-radius: 12px; }
.card-header { display: flex; align-items: center; gap: 12px; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid rgba(255,255,255,0.05); }
.card-header h3 { color: #e2e8f0; margin: 0; font-size: 1.1rem; }
.card-header svg { font-size: 1.3rem; color: #6366f1; }

.slider-container { display: flex; align-items: center; gap: 16px; }
.slider-container .ant-slider { flex: 1; }
.slider-value { color: #6366f1; font-weight: 600; min-width: 50px; text-align: right; }

.switch-label { margin-left: 12px; color: rgba(255, 255, 255, 0.75); }

.explanation-card { padding: 20px; border-radius: 12px; }
.explanation-header { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }
.explanation-header h4 { color: #e2e8f0; margin: 0; font-size: 1rem; }
.explanation-header svg { color: #6366f1; font-size: 1.2rem; }
.explanation-content { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }
.explanation-item { padding: 16px; background: rgba(255, 255, 255, 0.03); border-radius: 8px; }
.explanation-title { color: #6366f1; font-weight: 600; margin-bottom: 6px; }
.explanation-desc { color: rgba(255, 255, 255, 0.6); font-size: 0.85rem; line-height: 1.5; }

@media (max-width: 992px) {
  .settings-grid { grid-template-columns: 1fr; }
  .explanation-content { grid-template-columns: 1fr; }
}
</style>

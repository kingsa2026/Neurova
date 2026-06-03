<template>
  <div >
    <div >
      <h2 >
        <MedicineBoxOutlined :style="{ color: '#6366f1' }" /> 睡眠管理
      </h2>
    </div>
    <div >
      <div >状态<b >{{ sleepStatus }}</b></div>
      <div >今日<b >{{ todayHours }}h</b></div>
      <div >唤醒<b >{{ wakeCount }}</b></div>
    </div>
    <div >
      <div >
        <h4>睡眠模式配置</h4>
        <div >
          <span>启用睡眠</span>
          <a-switch :checked="sleepOn" @change="(v: boolean) => sleepOn = v" />
        </div>
        <div >
          <span>睡眠窗口</span>
          <a-time-picker />
          <span>-</span>
          <a-time-picker />
        </div>
      </div>
      <div >
        <h4>唤醒规则</h4>
        <div v-for="r in rules" :key="r.id" >
          <div  :style="{ background: r.color }" />
          <div>
            <span >{{ r.name }}</span>
            <span >{{ r.desc }}</span>
          </div>
          <a-switch v-model:checked="r.on" size="small" />
        </div>
      </div>
    </div>
    <div >
      <h4>睡眠历史</h4>
      <div >
        <div v-for="d in dailys" :key="d.day" >
          <div  :style="{ height: d.hrs * 12 + 'px' }" />
          <span>{{ d.day }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { MedicineBoxOutlined } from '@ant-design/icons-vue'
import { sleepAPI } from '@/api/modules/sleep'
import { useAgentPage } from '@/composables/useAgentPage'
const { agentId, initAgent } = useAgentPage('/agent/:agentId/sleep', () => loadSleepData())
const sleepOn = ref(true)
const sleepStatus = ref('清醒')
const todayHours = ref(3)
const wakeCount = ref(5)
const rules = ref([
  { id: '1', name: '定时唤醒', desc: '每日 08:00 自动唤醒', on: true, color: '#3b82f6' },
  { id: '2', name: '优先级唤醒', desc: '高优先级任务可唤醒', on: true, color: '#ef4444' },
  { id: '3', name: '事件唤醒', desc: '新消息达到阈值唤醒', on: false, color: '#f59e0b' },
])
const dailys = ref([
  { day: '05-15', hrs: 2 },
  { day: '05-16', hrs: 4 },
  { day: '05-17', hrs: 3 },
  { day: '05-18', hrs: 5 },
  { day: '05-19', hrs: 2.5 },
  { day: '05-20', hrs: 3 },
  { day: '05-21', hrs: 1.5 },
])
const stageNames: Record<string, string> = {
  active: '活跃', light: '浅睡', rem: 'REM', deep: '深睡', hibernate: '休眠',
}
async function loadSleepData() {
  try {
    const [statusRes, settingsRes] = await Promise.allSettled([
      sleepAPI.getStatus(agentId.value),
      sleepAPI.getSettings(agentId.value),
    ])
    if (statusRes.status === 'fulfilled' && statusRes.value?.data) {
      const d = statusRes.value.data
      sleepStatus.value = stageNames[d.stage] || d.stage_name || d.stage || '清醒'
      if (d.duration_seconds) todayHours.value = Math.round(d.duration_seconds / 3600 * 10) / 10
    }
    if (settingsRes.status === 'fulfilled' && settingsRes.value?.data) {
      const s = settingsRes.value.data
      if (s.sleep_schedule?.enabled !== undefined) sleepOn.value = s.sleep_schedule.enabled
    }
  } catch { /* 使用默认数据 */ }
}
onMounted(async () => {
  await initAgent()
  loadSleepData()
})
</script>
<style scoped>
.pg { display: flex; flex-direction: column; gap: 14px; }
.hd { padding: 16px 24px; border-radius: 12px; }
.t { font-size: 1.2rem; color: #e2e8f0; margin: 0; display: flex; align-items: center; gap: 8px; }
.sr { display: flex; gap: 12px; }
.s { flex: 1; padding: 14px 18px; border-radius: 10px; display: flex; justify-content: space-between; align-items: center; color: rgba(255,255,255,0.5); font-size: .85rem; }
.s b { font-size: 1.4rem; }
.c1 { color: #6366f1; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.card { padding: 20px; border-radius: 12px; }
.card h4 { color: #e2e8f0; margin: 0 0 16px; }
.sw { display: flex; justify-content: space-between; align-items: center; padding: 12px 0; border-bottom: 1px solid rgba(255,255,255,0.04); color: rgba(255,255,255,0.65); }
.r { display: flex; align-items: center; gap: 10px; padding: 12px 0; border-bottom: 1px solid rgba(255,255,255,0.04); }
.rd { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.rn { color: #e2e8f0; font-size: .85rem; display: block; }
.rdd { color: rgba(255,255,255,0.3); font-size: .72rem; }
.hist { padding: 20px; border-radius: 12px; }
.hist h4 { color: #e2e8f0; margin: 0 0 16px; }
.hbar { display: flex; align-items: flex-end; gap: 16px; height: 80px; }
.hb { display: flex; flex-direction: column; align-items: center; gap: 4px; }
.hbf { width: 20px; background: linear-gradient(#6366f1, #8b5cf6); border-radius: 4px 4px 0 0; min-height: 4px; }
.hb span { color: rgba(255,255,255,0.3); font-size: .68rem; }
@media (max-width: 768px) { .grid { grid-template-columns: 1fr } }
</style>
 
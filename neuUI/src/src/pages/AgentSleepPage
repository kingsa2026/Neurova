&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h2 &gt;
        &lt;MedicineBoxOutlined :style="{ color: '#6366f1' }" /&gt; 睡眠管理
      &lt;/h2&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;div &gt;状态&lt;b &gt;{{ sleepStatus }}&lt;/b&gt;&lt;/div&gt;
      &lt;div &gt;今日&lt;b &gt;{{ todayHours }}h&lt;/b&gt;&lt;/div&gt;
      &lt;div &gt;唤醒&lt;b &gt;{{ wakeCount }}&lt;/b&gt;&lt;/div&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;div &gt;
        &lt;h4&gt;睡眠模式配置&lt;/h4&gt;
        &lt;div &gt;
          &lt;span&gt;启用睡眠&lt;/span&gt;
          &lt;a-switch :checked="sleepOn" @change="(v: boolean) =&gt; sleepOn = v" /&gt;
        &lt;/div&gt;
        &lt;div &gt;
          &lt;span&gt;睡眠窗口&lt;/span&gt;
          &lt;a-time-picker /&gt;
          &lt;span&gt;-&lt;/span&gt;
          &lt;a-time-picker /&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;div &gt;
        &lt;h4&gt;唤醒规则&lt;/h4&gt;
        &lt;div v-for="r in rules" :key="r.id" &gt;
          &lt;div  :style="{ background: r.color }" /&gt;
          &lt;div&gt;
            &lt;span &gt;{{ r.name }}&lt;/span&gt;
            &lt;span &gt;{{ r.desc }}&lt;/span&gt;
          &lt;/div&gt;
          &lt;a-switch v-model:checked="r.on" size="small" /&gt;
        &lt;/div&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;h4&gt;睡眠历史&lt;/h4&gt;
      &lt;div &gt;
        &lt;div v-for="d in dailys" :key="d.day" &gt;
          &lt;div  :style="{ height: d.hrs * 12 + 'px' }" /&gt;
          &lt;span&gt;{{ d.day }}&lt;/span&gt;
        &lt;/div&gt;
      &lt;/div&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref, onMounted } from 'vue'
import { MedicineBoxOutlined } from '@ant-design/icons-vue'
import { sleepAPI } from '@/api/modules/sleep'
import { useAgentPage } from '@/composables/useAgentPage'
const { agentId, initAgent } = useAgentPage('/agent/:agentId/sleep', () =&gt; loadSleepData())
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
const stageNames: Record&lt;string, string&gt; = {
  active: '活跃', light: '浅睡', rem: 'REM', deep: '深睡', hibernate: '休眠',
}
async function loadSleepData() {
  try {
    const [statusRes, settingsRes] = await Promise.allSettled([
      sleepAPI.getStatus(agentId.value),
      sleepAPI.getSettings(agentId.value),
    ])
    if (statusRes.status === 'fulfilled' &amp;&amp; statusRes.value?.data) {
      const d = statusRes.value.data
      sleepStatus.value = stageNames[d.stage] || d.stage_name || d.stage || '清醒'
      if (d.duration_seconds) todayHours.value = Math.round(d.duration_seconds / 3600 * 10) / 10
    }
    if (settingsRes.status === 'fulfilled' &amp;&amp; settingsRes.value?.data) {
      const s = settingsRes.value.data
      if (s.sleep_schedule?.enabled !== undefined) sleepOn.value = s.sleep_schedule.enabled
    }
  } catch { /* 使用默认数据 */ }
}
onMounted(async () =&gt; {
  await initAgent()
  loadSleepData()
})
&lt;/script&gt;
&lt;style scoped&gt;
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
&lt;/style&gt;
&nbsp;
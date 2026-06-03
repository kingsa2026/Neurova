<template>
  <div >
    <div >
      <h2 >
        <SmileOutlined :style="{ color: '#a78bfa' }" /> 人格配置
      </h2>
    </div>
    <div >
      <div >
        <h4>OCEAN 五维度</h4>
        <div v-for="d in dims" :key="d.name" >
          <span >{{ d.name }}</span>
          <span >{{ d.desc }}</span>
          <div >
            <div  :style="{ width: d.val + '%', background: d.color }" />
            <span>{{ d.val }}%</span>
          </div>
        </div>
      </div>
      <div >
        <h4>MBTI 类型</h4>
        <div >
          <div  style="background: linear-gradient(135deg, #a78bfa, #6366f1)">
            {{ mbti }}
          </div>
          <h3>建筑师</h3>
          <p>富有战略思维，擅长系统规划和长期愿景</p>
        </div>
        <div >
          <h5>预设模板</h5>
          <div >
            <div v-for="p in presets" :key="p" >{{ p }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { request } from '@/api'
import { SmileOutlined } from '@ant-design/icons-vue'
import { useAgentPage } from '@/composables/useAgentPage'
const dims = ref([
  { name: '开放性', desc: '对新鲜事物的接受度', val: 50, color: '#3b82f6' },
  { name: '尽责性', desc: '自律和责任心', val: 50, color: '#34d399' },
  { name: '外向性', desc: '社交活跃度', val: 50, color: '#f59e0b' },
  { name: '宜人性', desc: '合作与同理心', val: 50, color: '#a78bfa' },
  { name: '情绪稳定性', desc: '情绪调节能力', val: 50, color: '#ef4444' },
])
const mbti = ref('--')
const presets = ['专业顾问', '创意伙伴', '技术专家', '导师教练']
const loadData = async () => {
  try {
    const res = await request.get(`/agents/${agentId.value}/personality`)
    if (res.code === 0 && res.data) {
      const d = res.data
      if (d.ocean) {
        const keys = ['openness', 'conscientiousness', 'extraversion', 'agreeableness', 'neuroticism']
        dims.value = dims.value.map((dd, i) => ({
          ...dd,
          val: Math.round((d.ocean[keys[i]] || 0.5) * 100),
        }))
      }
      if (d.mbti_type) mbti.value = d.mbti_type
    }
  } catch { /* fallback to defaults */ }
}
const { agentId, initAgent } = useAgentPage('/agent/:agentId/personality', () => loadData())
onMounted(async () => {
  await initAgent()
  loadData()
})
</script>
<style scoped>
.pg { display: flex; flex-direction: column; gap: 14px; }
.hd { padding: 16px 24px; border-radius: 12px; }
.t { font-size: 1.2rem; color: #e2e8f0; margin: 0; display: flex; align-items: center; gap: 8px; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.card { padding: 20px; border-radius: 12px; }
.card h4 { color: #e2e8f0; margin: 0 0 16px; }
.dim { margin-bottom: 14px; }
.dn { color: #e2e8f0; font-size: 0.9rem; display: block; }
.dd { color: rgba(255,255,255,0.3); font-size: 0.72rem; display: block; margin: 2px 0 4px; }
.dbar { display: flex; align-items: center; gap: 8px; }
.dbf { height: 6px; border-radius: 3px; min-width: 20px; }
.dbar span { color: rgba(255,255,255,0.3); font-size: 0.7rem; }
.mbti { text-align: center; margin-bottom: 16px; }
.mbadge { width: 64px; height: 64px; border-radius: 16px; display: flex; align-items: center; justify-content: center; color: #fff; font-size: 1.1rem; font-weight: 700; margin: 0 auto 10px; }
.mbti h3 { color: #e2e8f0; margin: 0 0 4px; }
.mbti p { color: rgba(255,255,255,0.4); font-size: 0.82rem; margin: 0; }
.presets h5 { color: rgba(255,255,255,0.5); margin: 0 0 8px; font-size: 0.85rem; }
.preset-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.preset { padding: 10px; border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; color: rgba(255,255,255,0.5); font-size: 0.82rem; text-align: center; cursor: pointer; }
.preset:hover { border-color: #a78bfa; color: #a78bfa; }
@media (max-width: 768px) { .grid { grid-template-columns: 1fr } }
</style>
 
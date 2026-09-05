&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h2 &gt;
        &lt;SmileOutlined :style="{ color: '#a78bfa' }" /&gt; 人格配置
      &lt;/h2&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;div &gt;
        &lt;h4&gt;OCEAN 五维度&lt;/h4&gt;
        &lt;div v-for="d in dims" :key="d.name" &gt;
          &lt;span &gt;{{ d.name }}&lt;/span&gt;
          &lt;span &gt;{{ d.desc }}&lt;/span&gt;
          &lt;div &gt;
            &lt;div  :style="{ width: d.val + '%', background: d.color }" /&gt;
            &lt;span&gt;{{ d.val }}%&lt;/span&gt;
          &lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;div &gt;
        &lt;h4&gt;MBTI 类型&lt;/h4&gt;
        &lt;div &gt;
          &lt;div  style="background: linear-gradient(135deg, #a78bfa, #6366f1)"&gt;
            {{ mbti }}
          &lt;/div&gt;
          &lt;h3&gt;建筑师&lt;/h3&gt;
          &lt;p&gt;富有战略思维，擅长系统规划和长期愿景&lt;/p&gt;
        &lt;/div&gt;
        &lt;div &gt;
          &lt;h5&gt;预设模板&lt;/h5&gt;
          &lt;div &gt;
            &lt;div v-for="p in presets" :key="p" &gt;{{ p }}&lt;/div&gt;
          &lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
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
const loadData = async () =&gt; {
  try {
    const res = await request.get(`/agents/${agentId.value}/personality`)
    if (res.code === 0 &amp;&amp; res.data) {
      const d = res.data
      if (d.ocean) {
        const keys = ['openness', 'conscientiousness', 'extraversion', 'agreeableness', 'neuroticism']
        dims.value = dims.value.map((dd, i) =&gt; ({
          ...dd,
          val: Math.round((d.ocean[keys[i]] || 0.5) * 100),
        }))
      }
      if (d.mbti_type) mbti.value = d.mbti_type
    }
  } catch { /* fallback to defaults */ }
}
const { agentId, initAgent } = useAgentPage('/agent/:agentId/personality', () =&gt; loadData())
onMounted(async () =&gt; {
  await initAgent()
  loadData()
})
&lt;/script&gt;
&lt;style scoped&gt;
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
&lt;/style&gt;
&nbsp;
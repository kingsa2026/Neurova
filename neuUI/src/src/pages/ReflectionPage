&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h2 &gt;&lt;SyncOutlined :style="{color:'#34d399'}" /&gt; 反思管理&lt;/h2&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;div &gt;反思记录&lt;b &gt;{{ stats.total }}&lt;/b&gt;&lt;/div&gt;
      &lt;div &gt;改进建议&lt;b &gt;{{ stats.suggestions }}&lt;/b&gt;&lt;/div&gt;
      &lt;div &gt;深度评估&lt;b &gt;{{ stats.status }}&lt;/b&gt;&lt;/div&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;div v-for="r in items" :key="r.id" &gt;
        &lt;div &gt;
          &lt;a-tag :color="r.tc"&gt;{{ r.tag }}&lt;/a-tag&gt;
          &lt;span &gt;{{ r.date }}&lt;/span&gt;
        &lt;/div&gt;
        &lt;h4&gt;{{ r.title }}&lt;/h4&gt;
        &lt;p&gt;{{ r.desc }}&lt;/p&gt;
        &lt;div &gt;
          &lt;span&gt;深度：&lt;b :style="{color:r.lv&gt;3?'#34d399':'#fbbf24'}"&gt;{{ '★'.repeat(r.lv) }}{{ '☆'.repeat(5-r.lv) }}&lt;/b&gt;&lt;/span&gt;
        &lt;/div&gt;
      &lt;/div&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref, computed, onMounted } from 'vue'
import { request } from '@/api'
import { useAgentPage } from '@/composables/useAgentPage'
import { SyncOutlined } from '@ant-design/icons-vue'
const { agentId, agentStore, initAgent } = useAgentPage('/agent/:agentId/reflection', () =&gt; loadData())
const stats = ref({ total: 67, suggestions: 34, status: '中' })
const items = ref([
  {id:1,title:'RAG 检索准确率反思',desc:'今日文档检索准确率 78%，低于目标 90%。原因：向量模型对中文长文本效果不佳，建议切换到 BGE 模型',tag:'检索',tc:'blue',lv:4,date:'05-20'},
  {id:2,title:'对话流畅度评估',desc:'今日多轮对话平均延迟 1.2s，用户满意度 92%。可优化点：减少记忆检索次数，增加缓存',tag:'对话',tc:'purple',lv:3,date:'05-19'},
  {id:3,title:'代码生成质量回顾',desc:'本周代码生成正确率 85%，比上周提升 5%。改进点：增加代码审查步骤',tag:'技能',tc:'green',lv:4,date:'05-18'},
  {id:4,title:'资源消耗反思',desc:'Token 日消耗 1.2M，超出预算 20%。建议优化 prompt 长度和实施缓存策略',tag:'资源',tc:'orange',lv:3,date:'05-17'},
])
async function loadData() {
  try {
    const res = await request.get(`/agents/${agentId.value}/reflection`)
    if (res.code === 0 &amp;&amp; res.data) {
      if (res.data.items?.length) items.value = res.data.items
      if (res.data.stats) stats.value = res.data.stats
    }
  } catch { /* 使用静态数据 */ }
}
onMounted(async () =&gt; {
  await initAgent()
  loadData()
})
&lt;/script&gt;
&lt;style scoped&gt;
.pg{display:flex;flex-direction:column;gap:14px;}
.hd{padding:16px 24px;border-radius:12px;}
.t{font-size:1.2rem;color:#e2e8f0;margin:0;display:flex;align-items:center;gap:8px;}
.sr{display:flex;gap:12px;}
.s{flex:1;padding:14px 18px;border-radius:10px;display:flex;justify-content:space-between;align-items:center;color:rgba(255,255,255,0.5);font-size:.85rem;}
.s b{font-size:1.4rem;}.c1{color:#34d399;}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:14px;}
.card{padding:20px;border-radius:12px;cursor:pointer;}
.card h4{color:#e2e8f0;margin:8px 0;}
.card p{color:rgba(255,255,255,0.45);font-size:0.85rem;margin:0 0 10px;}
.ct{display:flex;justify-content:space-between;}
.cd{color:rgba(255,255,255,0.25);font-size:0.75rem;}
.cb{color:rgba(255,255,255,0.35);font-size:0.82rem;}
@media(max-width:768px){.grid{grid-template-columns:1fr}}
&lt;/style&gt;
&nbsp;
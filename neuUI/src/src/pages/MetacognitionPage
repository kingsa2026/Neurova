&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h2 &gt;&lt;EyeOutlined :style="{color:'#8b5cf6'}" /&gt; 元认知&lt;/h2&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;div &gt;思考步骤&lt;b &gt;{{ stats.total }}&lt;/b&gt;&lt;/div&gt;
      &lt;div &gt;自我评估&lt;b &gt;{{ stats.evaluations }}&lt;/b&gt;&lt;/div&gt;
      &lt;div &gt;优化建议&lt;b &gt;{{ stats.suggestions }}&lt;/b&gt;&lt;/div&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;a-timeline mode="left"&gt;
        &lt;a-timeline-item v-for="it in items" :key="it.id"&gt;
          &lt;template #dot&gt;&lt;span  :style="{background:it.color}"&gt;&lt;/span&gt;&lt;/template&gt;
          &lt;div &gt;
            &lt;div &gt;{{ it.title }}&lt;/div&gt;
            &lt;div &gt;
              &lt;a-tag :color="it.tc" size="small"&gt;{{ it.type }}&lt;/a-tag&gt;
              &lt;span &gt;{{ it.time }}&lt;/span&gt;
            &lt;/div&gt;
          &lt;/div&gt;
        &lt;/a-timeline-item&gt;
      &lt;/a-timeline&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref, computed, onMounted } from 'vue'
import { request } from '@/api'
import { useAgentPage } from '@/composables/useAgentPage'
import { EyeOutlined } from '@ant-design/icons-vue'
const { agentId, agentStore, initAgent } = useAgentPage('/agent/:agentId/metacognition', () =&gt; loadData())
const stats = ref({ total: 892, evaluations: 45, suggestions: 12 })
const items = ref([
  {id:1,title:'分析用户查询意图，识别为"文档生成"类型',type:'分析',tc:'blue',color:'#3b82f6',time:'2分钟前'},
  {id:2,title:'制定执行计划：检索知识库→应用模板→生成文档→验证',type:'决策',tc:'purple',color:'#8b5cf6',time:'2分钟前'},
  {id:3,title:'评估自身能力：文档生成技能就绪，知识库覆盖完整',type:'评估',tc:'green',color:'#34d399',time:'1分钟前'},
  {id:4,title:'执行中发现知识库条目缺失，切换到搜索模式补充',type:'反思',tc:'orange',color:'#f59e0b',time:'30秒前'},
  {id:5,title:'生成文档后自检：格式正确，内容完整，建议添加引用链接',type:'优化',tc:'pink',color:'#f472b6',time:'刚刚'},
  {id:6,title:'总结：本次任务中知识库覆盖不足是主要瓶颈，已记录待改善',type:'总结',tc:'cyan',color:'#06b6d4',time:'刚刚'},
])
async function loadData() {
  try {
    const res = await request.get(`/agents/${agentId.value}/metacognition`)
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
.s b{font-size:1.4rem;}.c1{color:#8b5cf6;}
.tl{padding:24px;border-radius:12px;}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;}
.ti{padding:4px 0;}
.til{color:#e2e8f0;margin-bottom:6px;}
.tim{display:flex;align-items:center;gap:8px;}
.ts{color:rgba(255,255,255,0.25);font-size:0.75rem;}
&lt;/style&gt;
&nbsp;
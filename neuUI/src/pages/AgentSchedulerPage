&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h2 &gt;&lt;ClockCircleOutlined :style="{color:'#34d399'}"/&gt; 调度器&lt;/h2&gt;
      &lt;a-button type="primary" size="small"&gt;&lt;PlusOutlined/&gt;创建任务&lt;/a-button&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;div &gt;任务&lt;b &gt;{{ stats.total }}&lt;/b&gt;&lt;/div&gt;
      &lt;div &gt;执行中&lt;b &gt;{{ stats.running }}&lt;/b&gt;&lt;/div&gt;
      &lt;div &gt;成功率&lt;b &gt;{{ stats.successRate }}&lt;/b&gt;&lt;/div&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;a-table :columns="cols" :data-source="data" row-key="id" size="middle" :pagination="false"&gt;
        &lt;template #bodyCell="{column,record}"&gt;
          &lt;template v-if="column.key==='st'"&gt;
            &lt;a-tag :color="record.sc"&gt;{{ record.st }}&lt;/a-tag&gt;
          &lt;/template&gt;
          &lt;template v-if="column.key==='act'"&gt;
            &lt;a-space&gt;
              &lt;a-button type="link" size="small"&gt;运行&lt;/a-button&gt;
              &lt;a-button type="link" size="small"&gt;编辑&lt;/a-button&gt;
              &lt;a-popconfirm title="删除?"&gt;
                &lt;a-button type="link" size="small" danger&gt;删除&lt;/a-button&gt;
              &lt;/a-popconfirm&gt;
            &lt;/a-space&gt;
          &lt;/template&gt;
        &lt;/template&gt;
      &lt;/a-table&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref, onMounted } from 'vue'
import { request } from '@/api'
import { useAgentPage } from '@/composables/useAgentPage'
import { ClockCircleOutlined, PlusOutlined } from '@ant-design/icons-vue'
const { agentId, agentStore, initAgent } = useAgentPage('/agent/:agentId/scheduler', () =&gt; loadData())
const cols = [
  {title:'任务名',dataIndex:'name'},
  {title:'Cron',dataIndex:'cron'},
  {title:'状态',key:'st',width:80},
  {title:'上次执行',dataIndex:'last',width:160},
  {title:'操作',key:'act',width:200}
]
const stats = ref({ total: 16, running: 3, successRate: '96%' })
const data = ref([
  {id:'1',name:'知识库同步',cron:'0 */6 * * *',st:'运行中',sc:'green',last:'05-21 06:00'},
  {id:'2',name:'记忆清理',cron:'0 2 * * *',st:'已调度',sc:'blue',last:'05-21 02:00'},
  {id:'3',name:'健康检查',cron:'*/30 * * * *',st:'运行中',sc:'green',last:'05-21 11:30'},
  {id:'4',name:'日志归档',cron:'0 0 * * 0',st:'已暂停',sc:'default',last:'05-19 00:00'},
  {id:'5',name:'数据备份',cron:'0 4 * * *',st:'运行中',sc:'green',last:'05-21 04:00'},
  {id:'6',name:'模型更新检查',cron:'0 8 * * 1-5',st:'已调度',sc:'blue',last:'05-21 08:00'}
])
async function loadData() {
  try {
    const res = await request.get(`/agents/${agentId.value}/scheduler/tasks`)
    if (res.code === 0 &amp;&amp; res.data) {
      if (res.data.tasks?.length) data.value = res.data.tasks
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
.hd{display:flex;justify-content:space-between;align-items:center;padding:16px 24px;border-radius:12px;}
.t{font-size:1.2rem;color:#e2e8f0;margin:0;display:flex;align-items:center;gap:8px;}
.sr{display:flex;gap:12px;}
.s{flex:1;padding:14px 18px;border-radius:10px;display:flex;justify-content:space-between;align-items:center;color:rgba(255,255,255,0.5);font-size:.85rem;}
.s b{font-size:1.4rem;}.c1{color:#34d399;}
.tb{padding:20px;border-radius:12px;}
&lt;/style&gt;
&nbsp;
<template>
  <div >
    <div >
      <h2 ><ClockCircleOutlined :style="{color:'#34d399'}"/> 调度器</h2>
      <a-button type="primary" size="small"><PlusOutlined/>创建任务</a-button>
    </div>
    <div >
      <div >任务<b >{{ stats.total }}</b></div>
      <div >执行中<b >{{ stats.running }}</b></div>
      <div >成功率<b >{{ stats.successRate }}</b></div>
    </div>
    <div >
      <a-table :columns="cols" :data-source="data" row-key="id" size="middle" :pagination="false">
        <template #bodyCell="{column,record}">
          <template v-if="column.key==='st'">
            <a-tag :color="record.sc">{{ record.st }}</a-tag>
          </template>
          <template v-if="column.key==='act'">
            <a-space>
              <a-button type="link" size="small">运行</a-button>
              <a-button type="link" size="small">编辑</a-button>
              <a-popconfirm title="删除?">
                <a-button type="link" size="small" danger>删除</a-button>
              </a-popconfirm>
            </a-space>
          </template>
        </template>
      </a-table>
    </div>
  </div>
</template>
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { request } from '@/api'
import { useAgentPage } from '@/composables/useAgentPage'
import { ClockCircleOutlined, PlusOutlined } from '@ant-design/icons-vue'
const { agentId, agentStore, initAgent } = useAgentPage('/agent/:agentId/scheduler', () => loadData())
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
    if (res.code === 0 && res.data) {
      if (res.data.tasks?.length) data.value = res.data.tasks
      if (res.data.stats) stats.value = res.data.stats
    }
  } catch { /* 使用静态数据 */ }
}
onMounted(async () => {
  await initAgent()
  loadData()
})
</script>
<style scoped>
.pg{display:flex;flex-direction:column;gap:14px;}
.hd{display:flex;justify-content:space-between;align-items:center;padding:16px 24px;border-radius:12px;}
.t{font-size:1.2rem;color:#e2e8f0;margin:0;display:flex;align-items:center;gap:8px;}
.sr{display:flex;gap:12px;}
.s{flex:1;padding:14px 18px;border-radius:10px;display:flex;justify-content:space-between;align-items:center;color:rgba(255,255,255,0.5);font-size:.85rem;}
.s b{font-size:1.4rem;}.c1{color:#34d399;}
.tb{padding:20px;border-radius:12px;}
</style>
 
<template>
  <div class="pg">
    <div class="hd glass-effect">
      <h2 class="t"><SafetyOutlined :style="{color:'#ef4444'}"/> 规则管理</h2>
    </div>
    <div class="sr">
      <div class="s glass-effect">规则<b class="c1">{{ stats.total }}</b></div>
      <div class="s glass-effect">启用<b class="c1">{{ stats.enabled }}</b></div>
    </div>
    <div class="tb glass-effect">
      <a-table :columns="cols" :data-source="data" row-key="id" size="middle" :pagination="false">
        <template #bodyCell="{column,record}">
          <template v-if="column.key==='sw'">
            <a-switch v-model:checked="record.on" size="small"/>
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
import { SafetyOutlined } from '@ant-design/icons-vue'

const { agentId, agentStore, initAgent } = useAgentPage('/agent/:agentId/rules', () => loadData())

const cols = [
  {title:'名称',dataIndex:'name'},
  {title:'条件',dataIndex:'cond'},
  {title:'动作',dataIndex:'action'},
  {title:'优先级',dataIndex:'pri'},
  {title:'开关',key:'sw',width:70}
]

const stats = ref({ total: 24, enabled: 20 })
const data = ref([
  {id:'1',name:'敏感词过滤',cond:'输入含敏感词',action:'阻止发送+通知',pri:'高',on:true},
  {id:'2',name:'Token限额',cond:'日消耗>1M',action:'警告+限速',pri:'高',on:true},
  {id:'3',name:'大文件拦截',cond:'上传>50MB',action:'拒绝上传',pri:'中',on:true},
  {id:'4',name:'频率限制',cond:'每分钟>100次',action:'延迟处理',pri:'中',on:true},
  {id:'5',name:'非工作时间降级',cond:'22:00-06:00',action:'降低模型优先级',pri:'低',on:false},
  {id:'6',name:'异常检测',cond:'连续错误>5',action:'暂停服务+告警',pri:'高',on:true}
])

async function loadData() {
  try {
    const res = await request.get(`/agents/${agentId.value}/rules`)
    if (res.code === 0 && res.data) {
      if (res.data.rules?.length) data.value = res.data.rules
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
.hd{padding:16px 24px;border-radius:12px;}
.t{font-size:1.2rem;color:#e2e8f0;margin:0;display:flex;align-items:center;gap:8px;}
.sr{display:flex;gap:12px;}
.s{flex:1;padding:14px 18px;border-radius:10px;display:flex;justify-content:space-between;align-items:center;color:rgba(255,255,255,0.5);font-size:.85rem;}
.s b{font-size:1.4rem;}.c1{color:#ef4444;}
.tb{padding:20px;border-radius:12px;}
</style>

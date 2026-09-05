&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h2 &gt;&lt;SafetyOutlined :style="{color:'#ef4444'}"/&gt; 规则管理&lt;/h2&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;div &gt;规则&lt;b &gt;{{ stats.total }}&lt;/b&gt;&lt;/div&gt;
      &lt;div &gt;启用&lt;b &gt;{{ stats.enabled }}&lt;/b&gt;&lt;/div&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;a-table :columns="cols" :data-source="data" row-key="id" size="middle" :pagination="false"&gt;
        &lt;template #bodyCell="{column,record}"&gt;
          &lt;template v-if="column.key==='sw'"&gt;
            &lt;a-switch v-model:checked="record.on" size="small"/&gt;
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
import { SafetyOutlined } from '@ant-design/icons-vue'
const { agentId, agentStore, initAgent } = useAgentPage('/agent/:agentId/rules', () =&gt; loadData())
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
  {id:'2',name:'Token限额',cond:'日消耗&gt;1M',action:'警告+限速',pri:'高',on:true},
  {id:'3',name:'大文件拦截',cond:'上传&gt;50MB',action:'拒绝上传',pri:'中',on:true},
  {id:'4',name:'频率限制',cond:'每分钟&gt;100次',action:'延迟处理',pri:'中',on:true},
  {id:'5',name:'非工作时间降级',cond:'22:00-06:00',action:'降低模型优先级',pri:'低',on:false},
  {id:'6',name:'异常检测',cond:'连续错误&gt;5',action:'暂停服务+告警',pri:'高',on:true}
])
async function loadData() {
  try {
    const res = await request.get(`/agents/${agentId.value}/rules`)
    if (res.code === 0 &amp;&amp; res.data) {
      if (res.data.rules?.length) data.value = res.data.rules
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
.s b{font-size:1.4rem;}.c1{color:#ef4444;}
.tb{padding:20px;border-radius:12px;}
&lt;/style&gt;
&nbsp;
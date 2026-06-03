&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h2 &gt;
        &lt;HistoryOutlined :style="{ color: '#34d399' }" /&gt; 协作历史
      &lt;/h2&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;a-table :columns="cols" :data-source="list" row-key="id" size="middle" :pagination="{ pageSize: 10 }"&gt;
        &lt;template #bodyCell="{ column: c, record: r }"&gt;
          &lt;template v-if="c.key === 'st'"&gt;
            &lt;a-tag :color="r.sc"&gt;{{ r.st }}&lt;/a-tag&gt;
          &lt;/template&gt;
        &lt;/template&gt;
      &lt;/a-table&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref } from 'vue'
import { HistoryOutlined } from '@ant-design/icons-vue'
const cols = [
  { title: '协作名称', dataIndex: 'name' },
  { title: '模板', dataIndex: 'tmpl' },
  { title: '参与Agent', dataIndex: 'agents' },
  { title: '状态', key: 'st', width: 80 },
  { title: '开始时间', dataIndex: 'start', width: 160 },
  { title: '耗时', dataIndex: 'dur', width: 80 },
]
const list = ref([
  { id: '1', name: 'Q2报告审阅', tmpl: '文档审阅', agents: 'A,B,C', st: '已完成', sc: 'green', start: '05-18 14:00', dur: '2h' },
  { id: '2', name: '用户反馈分析', tmpl: '数据分析', agents: 'A,D', st: '进行中', sc: 'blue', start: '05-20 09:00', dur: '进行中' },
  { id: '3', name: 'API文档优化', tmpl: '文档审阅', agents: 'B,C', st: '已完成', sc: 'green', start: '05-15 10:00', dur: '1.5h' },
  { id: '4', name: '代码漏洞扫描', tmpl: '代码审查', agents: 'A,B,C,D', st: '已完成', sc: 'green', start: '05-12 08:00', dur: '4h' },
  { id: '5', name: '新功能头脑风暴', tmpl: '内容创作', agents: 'A,B,C', st: '中断', sc: 'orange', start: '05-19 15:00', dur: '-' },
])
&lt;/script&gt;
&lt;style scoped&gt;
.pg { display: flex; flex-direction: column; gap: 14px; }
.hd { padding: 16px 24px; border-radius: 12px; }
.t { font-size: 1.2rem; color: #e2e8f0; margin: 0; display: flex; align-items: center; gap: 8px; }
.tb { padding: 20px; border-radius: 12px; }
&lt;/style&gt;
&nbsp;
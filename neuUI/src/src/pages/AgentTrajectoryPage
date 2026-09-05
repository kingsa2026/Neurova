&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h2 &gt;
        &lt;HistoryOutlined :style="{ color: '#06b6d4' }" /&gt; 轨迹回放
      &lt;/h2&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;div &gt;轨迹&lt;b &gt;456&lt;/b&gt;&lt;/div&gt;
      &lt;div &gt;步骤&lt;b &gt;12K&lt;/b&gt;&lt;/div&gt;
      &lt;div &gt;异常&lt;b &gt;3&lt;/b&gt;&lt;/div&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;a-table :columns="cols" :data-source="list" row-key="id" size="middle" :pagination="{ pageSize: 8 }" /&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref } from 'vue'
import { HistoryOutlined } from '@ant-design/icons-vue'
const cols = [
  { title: 'ID', dataIndex: 'id', width: 80 },
  { title: 'Agent', dataIndex: 'agent' },
  { title: '任务', dataIndex: 'task' },
  { title: '步骤', dataIndex: 'sc', width: 80 },
  { title: '耗时', dataIndex: 'dur' },
  { title: '状态', dataIndex: 'st' },
]
const list = ref([
  { id: 'T001', agent: 'Agent-A', task: '文档生成', sc: 12, dur: '1.2s', st: '完成' },
  { id: 'T002', agent: 'Agent-B', task: '代码生成', sc: 8, dur: '0.8s', st: '完成' },
  { id: 'T003', agent: 'Agent-A', task: '语义搜索', sc: 15, dur: '2.1s', st: '完成' },
])
&lt;/script&gt;
&lt;style scoped&gt;
.pg { display: flex; flex-direction: column; gap: 14px; }
.hd { padding: 16px 24px; border-radius: 12px; }
.t { font-size: 1.2rem; color: #e2e8f0; margin: 0; display: flex; align-items: center; gap: 8px; }
.sr { display: flex; gap: 12px; }
.s { flex: 1; padding: 14px 18px; border-radius: 10px; display: flex; justify-content: space-between; align-items: center; color: rgba(255,255,255,0.5); font-size: .85rem; }
.s b { font-size: 1.4rem; }
.c1 { color: #06b6d4; }
.c2 { color: #ef4444; }
.tb { padding: 20px; border-radius: 12px; }
&lt;/style&gt;
&nbsp;
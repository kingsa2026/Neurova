&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h2 &gt;
        &lt;OrderedListOutlined :style="{ color: '#60a5fa' }" /&gt; 任务管理
      &lt;/h2&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;div &gt;总任务&lt;b &gt;{{ stats.total }}&lt;/b&gt;&lt;/div&gt;
      &lt;div &gt;已完成&lt;b &gt;{{ stats.done }}&lt;/b&gt;&lt;/div&gt;
      &lt;div &gt;进行中&lt;b &gt;{{ stats.inProgress }}&lt;/b&gt;&lt;/div&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;a-table :columns="cols" :data-source="data" row-key="id" size="middle" :pagination="{ pageSize: 8 }"&gt;
        &lt;template #bodyCell="{ column, record }"&gt;
          &lt;template v-if="column.key === 'st'"&gt;
            &lt;a-tag :color="record.sc"&gt;{{ record.st }}&lt;/a-tag&gt;
          &lt;/template&gt;
          &lt;template v-if="column.key === 'pg'"&gt;
            &lt;div &gt;
              &lt;div  :style="{ width: record.pg + '%' }" /&gt;
              &lt;span&gt;{{ record.pg }}%&lt;/span&gt;
            &lt;/div&gt;
          &lt;/template&gt;
        &lt;/template&gt;
      &lt;/a-table&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref } from 'vue'
import { OrderedListOutlined } from '@ant-design/icons-vue'
const stats = ref({ total: 89, done: 67, inProgress: 12 })
const cols = [
  { title: '任务名', dataIndex: 'name' },
  { title: '类型', dataIndex: 'type' },
  { title: '状态', key: 'st', width: 80 },
  { title: '进度', key: 'pg', width: 120 },
  { title: '截止', dataIndex: 'dl', width: 120 },
]
const data = ref([
  { id: '1', name: '知识库迁移至向量DB', type: '基础设施', st: '进行中', sc: 'blue', pg: 65, dl: '05-25' },
  { id: '2', name: 'API 文档更新', type: '文档', st: '已完成', sc: 'green', pg: 100, dl: '05-18' },
  { id: '3', name: '新技能集成测试', type: '测试', st: '进行中', sc: 'blue', pg: 40, dl: '05-28' },
  { id: '4', name: '性能基准测试', type: '测试', st: '规划中', sc: 'default', pg: 10, dl: '06-01' },
  { id: '5', name: '对话流优化', type: '优化', st: '进行中', sc: 'blue', pg: 80, dl: '05-22' },
  { id: '6', name: '安全审计', type: '安全', st: '已完成', sc: 'green', pg: 100, dl: '05-15' },
  { id: '7', name: '监控面板开发', type: '开发', st: '进行中', sc: 'blue', pg: 30, dl: '06-05' },
  { id: '8', name: '用户手册编写', type: '文档', st: '进行中', sc: 'blue', pg: 55, dl: '05-30' },
])
&lt;/script&gt;
&lt;style scoped&gt;
.pg { display: flex; flex-direction: column; gap: 14px; }
.hd { padding: 16px 24px; border-radius: 12px; }
.t { font-size: 1.2rem; color: #e2e8f0; margin: 0; display: flex; align-items: center; gap: 8px; }
.sr { display: flex; gap: 12px; }
.s { flex: 1; padding: 14px 18px; border-radius: 10px; display: flex; justify-content: space-between; align-items: center; color: rgba(255,255,255,0.5); font-size: .85rem; }
.s b { font-size: 1.4rem; }
.c1 { color: #60a5fa; }
.c2 { color: #34d399; }
.c3 { color: #8b5cf6; }
.tb { padding: 20px; border-radius: 12px; }
.bar { display: flex; align-items: center; gap: 8px; }
.bf { height: 6px; background: linear-gradient(90deg, #3b82f6, #8b5cf6); border-radius: 3px; }
.bar span { color: rgba(255,255,255,0.35); font-size: 0.75rem; }
&lt;/style&gt;
&nbsp;
&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h2 &gt;
        &lt;DashboardOutlined :style="{ color: '#34d399' }" /&gt; 基准测试
      &lt;/h2&gt;
      &lt;a-button type="primary" size="small"&gt;
        &lt;PlayCircleOutlined /&gt; 运行测试
      &lt;/a-button&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;div &gt;套件&lt;b &gt;{{ suites.length }}&lt;/b&gt;&lt;/div&gt;
      &lt;div &gt;运行&lt;b &gt;{{ runCount }}&lt;/b&gt;&lt;/div&gt;
      &lt;div &gt;均分&lt;b &gt;{{ avgScore }}&lt;/b&gt;&lt;/div&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;div v-for="s in suites" :key="s.id" &gt;
        &lt;h4&gt;{{ s.name }}&lt;/h4&gt;
        &lt;p&gt;{{ s.desc }}&lt;/p&gt;
        &lt;div &gt;
          &lt;span&gt;最近: {{ s.last }}&lt;/span&gt;
          &lt;a-button size="small" type="primary" ghost&gt;开始测试&lt;/a-button&gt;
        &lt;/div&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;h4&gt;最近结果&lt;/h4&gt;
      &lt;a-table :columns="rcols" :data-source="results" row-key="id" size="middle" :pagination="false" /&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref } from 'vue'
import { DashboardOutlined, PlayCircleOutlined } from '@ant-design/icons-vue'
const runCount = ref(67)
const avgScore = ref(87)
const suites = ref([
  { id: '1', name: '召回率测试', desc: '评估 Agent 记忆检索准确率', last: '05-20 得分 92' },
  { id: '2', name: '情感理解', desc: '评估情感识别和响应质量', last: '05-18 得分 85' },
  { id: '3', name: '全面评估', desc: '综合能力基准测试', last: '05-15 得分 88' },
  { id: '4', name: '代码生成', desc: '代码正确率和质量评估', last: '05-12 得分 83' },
  { id: '5', name: '对话质量', desc: '多轮对话一致性和准确性', last: '05-10 得分 91' },
])
const rcols = [
  { title: '测试套件', dataIndex: 'suite' },
  { title: '得分', dataIndex: 'score' },
  { title: '通过率', dataIndex: 'pass' },
  { title: '耗时', dataIndex: 'time' },
  { title: '日期', dataIndex: 'date' },
]
const results = ref([
  { id: '1', suite: '召回率测试', score: '92/100', pass: '94%', time: '12s', date: '05-20' },
  { id: '2', suite: '情感理解', score: '85/100', pass: '88%', time: '8s', date: '05-18' },
  { id: '3', suite: '全面评估', score: '88/100', pass: '91%', time: '45s', date: '05-15' },
  { id: '4', suite: '代码生成', score: '83/100', pass: '86%', time: '20s', date: '05-12' },
  { id: '5', suite: '对话质量', score: '91/100', pass: '95%', time: '15s', date: '05-10' },
])
&lt;/script&gt;
&lt;style scoped&gt;
.pg { display: flex; flex-direction: column; gap: 14px; }
.hd { display: flex; justify-content: space-between; align-items: center; padding: 16px 24px; border-radius: 12px; }
.t { font-size: 1.2rem; color: #e2e8f0; margin: 0; display: flex; align-items: center; gap: 8px; }
.sr { display: flex; gap: 12px; }
.s { flex: 1; padding: 14px 18px; border-radius: 10px; display: flex; justify-content: space-between; align-items: center; color: rgba(255,255,255,0.5); font-size: .85rem; }
.s b { font-size: 1.4rem; }
.c1 { color: #34d399; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 14px; }
.card { padding: 20px; border-radius: 12px; cursor: pointer; }
.card h4 { color: #e2e8f0; margin: 0 0 6px; }
.card p { color: rgba(255,255,255,0.4); font-size: 0.8rem; margin: 0 0 12px; }
.cb { display: flex; justify-content: space-between; align-items: center; color: rgba(255,255,255,0.25); font-size: 0.75rem; }
.tb { padding: 20px; border-radius: 12px; }
.tb h4 { color: #e2e8f0; margin: 0 0 12px; }
&lt;/style&gt;
&nbsp;
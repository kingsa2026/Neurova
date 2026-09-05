&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h2 &gt;
        &lt;MonitorOutlined :style="{ color: '#06b6d4' }" /&gt; 计算机使用
      &lt;/h2&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;div &gt;会话&lt;b &gt;{{ stats.sessions }}&lt;/b&gt;&lt;/div&gt;
      &lt;div &gt;脚本&lt;b &gt;{{ stats.scripts }}&lt;/b&gt;&lt;/div&gt;
      &lt;div &gt;视觉&lt;b &gt;{{ stats.vision }}&lt;/b&gt;&lt;/div&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;h4&gt;控制面板&lt;/h4&gt;
      &lt;div &gt;
        &lt;div  v-for="i in 4" :key="i"&gt;
          &lt;span &gt;$&lt;/span&gt;
          &lt;span &gt;{{ ['ls -la', 'cat config.yaml', 'python main.py', 'echo done'][i - 1] }}&lt;/span&gt;
        &lt;/div&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;h4&gt;操作历史&lt;/h4&gt;
      &lt;div v-for="h in hist" :key="h.id" &gt;
        &lt;div  :style="{ background: h.color }" /&gt;
        &lt;div&gt;
          &lt;span &gt;{{ h.name }}&lt;/span&gt;
          &lt;span &gt;{{ h.time }}&lt;/span&gt;
        &lt;/div&gt;
      &lt;/div&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref } from 'vue'
import { MonitorOutlined } from '@ant-design/icons-vue'
const stats = ref({ sessions: 12, scripts: 34, vision: '启用' })
const hist = ref([
  { id: '1', name: '执行脚本 data_process.py', color: '#3b82f6', time: '2分钟前' },
  { id: '2', name: '屏幕捕获分析完成', color: '#34d399', time: '30分钟前' },
  { id: '3', name: '自动化任务 #42 完成', color: '#a78bfa', time: '1小时前' },
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
.card { padding: 20px; border-radius: 12px; }
.card h4 { color: #e2e8f0; margin: 0 0 12px; }
.terminal { background: rgba(0,0,0,0.3); border-radius: 8px; padding: 16px; font-family: monospace; }
.tline { display: flex; gap: 8px; padding: 2px 0; }
.tprompt { color: #34d399; }
.tcmd { color: rgba(255,255,255,0.6); }
.hist { padding: 20px; border-radius: 12px; }
.hist h4 { color: #e2e8f0; margin: 0 0 12px; }
.hitem { display: flex; align-items: center; gap: 10px; padding: 10px 0; border-bottom: 1px solid rgba(255,255,255,0.04); }
.hdot { width: 8px; height: 8px; border-radius: 50%; }
.hn { color: rgba(255,255,255,0.6); font-size: .82rem; display: block; }
.ht { color: rgba(255,255,255,0.2); font-size: .7rem; }
&lt;/style&gt;
&nbsp;
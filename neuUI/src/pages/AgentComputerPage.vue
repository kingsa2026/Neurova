<template>
  <div >
    <div >
      <h2 >
        <MonitorOutlined :style="{ color: '#06b6d4' }" /> 计算机使用
      </h2>
    </div>
    <div >
      <div >会话<b >{{ stats.sessions }}</b></div>
      <div >脚本<b >{{ stats.scripts }}</b></div>
      <div >视觉<b >{{ stats.vision }}</b></div>
    </div>
    <div >
      <h4>控制面板</h4>
      <div >
        <div  v-for="i in 4" :key="i">
          <span >$</span>
          <span >{{ ['ls -la', 'cat config.yaml', 'python main.py', 'echo done'][i - 1] }}</span>
        </div>
      </div>
    </div>
    <div >
      <h4>操作历史</h4>
      <div v-for="h in hist" :key="h.id" >
        <div  :style="{ background: h.color }" />
        <div>
          <span >{{ h.name }}</span>
          <span >{{ h.time }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
<script setup lang="ts">
import { ref } from 'vue'
import { MonitorOutlined } from '@ant-design/icons-vue'
const stats = ref({ sessions: 12, scripts: 34, vision: '启用' })
const hist = ref([
  { id: '1', name: '执行脚本 data_process.py', color: '#3b82f6', time: '2分钟前' },
  { id: '2', name: '屏幕捕获分析完成', color: '#34d399', time: '30分钟前' },
  { id: '3', name: '自动化任务 #42 完成', color: '#a78bfa', time: '1小时前' },
])
</script>
<style scoped>
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
</style>
 
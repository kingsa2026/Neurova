<template><div ><div ><h2 ><PictureOutlined :style="{color:'#f59e0b'}"/> AIGC 生成</h2></div><a-tabs v-model:activeKey="tab"  style="padding:0 16px;border-radius:12px"><a-tab-pane key="text" tab="文本"/><a-tab-pane key="image" tab="图像"/><a-tab-pane key="audio" tab="音频"/></a-tabs><div ><div ><a-textarea v-model:value="prompt" placeholder="输入提示词..." :rows="3"/><div ><a-select v-model:value="model" style="width:180px" :options="['GPT-4','Claude-3','DeepSeek-V3'].map(v=>({label:v,value:v}))"/><a-button type="primary" :loading="gen" @click="generate">生成</a-button></div></div><div  v-if="results.length"><h4>生成历史</h4><div ><div v-for="r in results" :key="r.id" ><div >{{ r.preview }}</div><div ><a-tag size="small">{{ r.model }}</a-tag><span >{{ r.time }}</span></div></div></div></div></div></div></template>
<script setup lang="ts">
import { ref } from 'vue'
import { PictureOutlined } from '@ant-design/icons-vue'
const tab=ref('text')
const prompt=ref('')
const model=ref('DeepSeek-V3')
const gen=ref(false)
const results=ref([
  {id:1,preview:'生成了一篇关于 AI Agent 架构的技术文档...',model:'GPT-4',time:'10分钟前'},
  {id:2,preview:'创建了一个数据分析报告模板...',model:'DeepSeek-V3',time:'1小时前'},
  {id:3,preview:'生成了 Python API 接口代码...',model:'Claude-3',time:'3小时前'},
  {id:4,preview:'编写了一份项目需求文档...',model:'DeepSeek-V3',time:'昨天'},
])
async function generate(){ gen.value=true; await new Promise(r=>setTimeout(r,1500)); results.value.unshift({id:Date.now(),preview:prompt.value.slice(0,60)+'...',model:model.value,time:'刚刚'}); prompt.value=''; gen.value=false }
</script>
<style scoped>
.pg{display:flex;flex-direction:column;gap:14px;}
.hd{padding:16px 24px;border-radius:12px;}
.t{font-size:1.2rem;color:#e2e8f0;margin:0;display:flex;align-items:center;gap:8px;}
.body{padding:24px;border-radius:12px;}
.input-area{display:flex;flex-direction:column;gap:12px;}
:deep(.input-area textarea){background:rgba(255,255,255,0.05)!important;border:1px solid rgba(255,255,255,0.1)!important;color:#e2e8f0!important;}
.params{display:flex;align-items:center;gap:12px;}
.history h4{color:#e2e8f0;margin:24px 0 12px;}
.result-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;}
.r-card{padding:14px;border-radius:10px;}
.r-preview{color:rgba(255,255,255,0.6);font-size:0.85rem;margin-bottom:8px;}
.r-meta{display:flex;justify-content:space-between;align-items:center;}
.r-time{color:rgba(255,255,255,0.2);font-size:0.72rem;}
</style>
 
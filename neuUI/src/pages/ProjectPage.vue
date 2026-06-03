<template><div ><div ><h2 ><ProjectOutlined :style="{color:'#f59e0b'}"/> 项目管理</h2><a-button type="primary" size="small"><PlusOutlined/>新建</a-button></div><div ><div >活跃<b >5</b></div><div >成员<b >12</b></div><div >完成率<b >78%</b></div></div><div ><div v-for="p in list" :key="p.id" ><div ><h4>{{ p.name }}</h4><a-tag :color="p.st==='进行中'?'blue':p.st==='已完成'?'green':'default'">{{ p.st }}</a-tag></div><p>{{ p.desc }}</p><div ><div ><div  :style="{width:p.pg+'%'}"/></div><span>{{ p.pg }}%</span></div><div ><a-avatar-group :max-count="3" size="small"><a-avatar :style="{background:'#'+Math.floor(Math.random()*16777215).toString(16)}" v-for="i in p.ms" :key="i">{{ 'ABCDEFGH'[i-1] }}</a-avatar></a-avatar-group><span >{{ p.date }}</span></div></div></div></div></template>
<script setup lang="ts">
import { ref } from 'vue'
import { ProjectOutlined, PlusOutlined } from '@ant-design/icons-vue'
const list=ref([{id:'1',name:'Agent 对话系统优化',desc:'提升多轮对话的上下文理解能力',st:'进行中',pg:65,ms:4,date:'05-20'},{id:'2',name:'知识库重建',desc:'迁移知识库存储至向量数据库',st:'进行中',pg:40,ms:3,date:'05-18'},{id:'3',name:'技能市场 v2',desc:'重构技能市场 UI 和推荐算法',st:'进行中',pg:90,ms:5,date:'05-15'},{id:'4',name:'性能优化专项',desc:'优化 Token 消耗和响应延迟',st:'已完成',pg:100,ms:3,date:'05-10'},{id:'5',name:'安全审计集成',desc:'接入合规审计和日志系统',st:'规划中',pg:10,ms:2,date:'05-22'}])
</script>
<style scoped>
.pg{display:flex;flex-direction:column;gap:14px;}
.hd{display:flex;justify-content:space-between;align-items:center;padding:16px 24px;border-radius:12px;}
.t{font-size:1.2rem;color:#e2e8f0;margin:0;display:flex;align-items:center;gap:8px;}
.sr{display:flex;gap:12px;}
.s{flex:1;padding:14px 18px;border-radius:10px;display:flex;justify-content:space-between;align-items:center;color:rgba(255,255,255,0.5);font-size:.85rem;}
.s b{font-size:1.4rem;}.c1{color:#f59e0b;}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px;}
.card{padding:20px;border-radius:12px;cursor:pointer;}
.ct{display:flex;justify-content:space-between;align-items:center;}
.ct h4{color:#e2e8f0;margin:0;}
.card p{color:rgba(255,255,255,0.4);font-size:0.85rem;margin:8px 0 12px;}
.cbar{display:flex;align-items:center;gap:8px;margin-bottom:10px;}
.bar{flex:1;height:6px;background:rgba(255,255,255,0.06);border-radius:3px;overflow:hidden;}
.bf{height:100%;background:linear-gradient(90deg,#3b82f6,#8b5cf6);border-radius:3px;transition:width 0.3s;}
.cbar span{color:rgba(255,255,255,0.4);font-size:0.78rem;}
.cf{display:flex;justify-content:space-between;align-items:center;}
.cd{color:rgba(255,255,255,0.2);font-size:0.72rem;}
</style>
 
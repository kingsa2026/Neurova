<template><div ><div ><h2 ><UsergroupAddOutlined :style="{color:'#8b5cf6'}"/> 团队管理</h2><a-button type="primary" size="small"><PlusOutlined/>新建团队</a-button></div><div ><div >团队<b >3</b></div><div >成员<b >28</b></div></div><div ><div v-for="t in list" :key="t.id" ><div  :style="{background:t.c+'15',color:t.c}"><TeamOutlined/></div><div ><h4>{{ t.name }}</h4><p>{{ t.desc }}</p></div><div ><span >{{ t.ms }} 成员</span><a-button size="small" type="link">管理</a-button></div></div></div></div></template>
<script setup lang="ts">
import { ref } from 'vue'
import { UsergroupAddOutlined, TeamOutlined, PlusOutlined } from '@ant-design/icons-vue'
const list=ref([{id:'1',name:'前端开发组',desc:'负责 Neurova UI 开发和维护',ms:8,c:'#3b82f6'},{id:'2',name:'AI 核心组',desc:'Agent 能力开发和模型调优',ms:12,c:'#8b5cf6'},{id:'3',name:'基础设施组',desc:'服务器、数据库和 DevOps',ms:6,c:'#34d399'}])
</script>
<style scoped>
.pg{display:flex;flex-direction:column;gap:14px;}
.hd{display:flex;justify-content:space-between;align-items:center;padding:16px 24px;border-radius:12px;}
.t{font-size:1.2rem;color:#e2e8f0;margin:0;display:flex;align-items:center;gap:8px;}
.sr{display:flex;gap:12px;}
.s{flex:1;padding:14px 18px;border-radius:10px;display:flex;justify-content:space-between;align-items:center;color:rgba(255,255,255,0.5);font-size:.85rem;}
.s b{font-size:1.4rem;}.c1{color:#8b5cf6;}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px;}
.card{padding:20px;border-radius:12px;cursor:pointer;display:flex;flex-direction:column;gap:12px;}
.ci{width:44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:1.2rem;}
.cc h4{color:#e2e8f0;margin:0;}
.cc p{color:rgba(255,255,255,0.4);font-size:0.8rem;margin:4px 0 0;}
.cb{display:flex;justify-content:space-between;align-items:center;}
.mc{color:rgba(255,255,255,0.35);font-size:0.78rem;}
</style>
 
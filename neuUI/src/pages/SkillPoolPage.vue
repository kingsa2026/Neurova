<template><div ><div ><h2 ><SwitcherOutlined :style="{color:'#8b5cf6'}"/> 技能池</h2></div><a-tabs v-model:activeKey="tab"  style="padding:0 16px;border-radius:12px"><a-tab-pane key="mine" tab="我的技能"/><a-tab-pane key="pool" tab="技能池"/><a-tab-pane key="learning" tab="学习中"/></a-tabs><div ><div v-for="s in list" :key="s.id" ><div  :style="{background:s.color+'20',color:s.color}">{{ s.name[0] }}</div><div ><h4>{{ s.name }}</h4><a-tag size="small">{{ s.tag }}</a-tag></div><div v-if="tab==='mine'" ><div ><div  :style="{width:s.lv+'%',background:s.color}"/></div><span >Lv.{{ s.lv }}</span></div><a-button v-else-if="tab==='pool'" size="small" type="primary" ghost>学习</a-button><a-button v-else size="small" @click="list=list.filter(d=>d.id!==s.id)">取消</a-button></div></div></div></template>
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { listPrivateSkills } from '@/api/modules/skill'
import { SwitcherOutlined } from '@ant-design/icons-vue'
interface SkillPoolItem { id:string;name:string;tag:string;color:string;lv:number }
const tab=ref('mine')
const skills=ref<SkillPoolItem[]>([])
const loading=ref(false)
const tags=['对话','搜索','文档','代码','分析','图像','语音','知识']
const colors:Record<string,string>={'对话':'#3b82f6','搜索':'#8b5cf6','文档':'#34d399','代码':'#f59e0b','分析':'#ef4444','图像':'#06b6d4','语音':'#a78bfa','知识':'#f472b6'}
onMounted(async()=>{
  loading.value=true
  try{
    const data=await listPrivateSkills()
    if(data?.length) skills.value=data.map((s:Record<string,unknown>)=>({
      id:(s.id||s.skill_id) as string,
      name:(s.name||s.title||'') as string,
      tag:((s.tags as string[])?.[0]||s.tag||s.category||'其他') as string,
      color:colors[((s.tags as string[])?.[0] as string)]||colors[s.tag as string]||'#60a5fa',
      lv:Math.min(99,Math.floor(((s.rating||s.score||4) as number)*((s.version?parseFloat(s.version as string):1))*15))
    }))
  }catch(e:unknown){const err=e as {message?:string};message.error(err?.message||'加载技能池失败')}
  finally{loading.value=false}
})
const list=computed(()=>tab.value==='mine'?skills.value.filter(d=>d.lv>=50):tab.value==='learning'?skills.value.filter(d=>d.lv<50):skills.value)
</script>
<style scoped>
.pg{display:flex;flex-direction:column;gap:14px;}
.hd{padding:16px 24px;border-radius:12px;}
.t{font-size:1.2rem;color:#e2e8f0;margin:0;display:flex;align-items:center;gap:8px;}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px;}
.card{display:flex;align-items:center;gap:14px;padding:18px;border-radius:12px;cursor:pointer;}
.ci{width:40px;height:40px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:700;flex-shrink:0;}
.cc h4{color:#e2e8f0;margin:0 0 4px;}
.cbar{flex:1;display:flex;align-items:center;gap:8px;}
.bar{flex:1;height:6px;background:rgba(255,255,255,0.06);border-radius:3px;overflow:hidden;}
.bf{height:100%;border-radius:3px;transition:width 0.3s;}
.bl{color:rgba(255,255,255,0.4);font-size:0.75rem;min-width:40px;}
</style>
 
&lt;template&gt;&lt;div &gt;&lt;div &gt;&lt;h2 &gt;&lt;UsergroupAddOutlined :style="{color:'#8b5cf6'}"/&gt; 团队管理&lt;/h2&gt;&lt;a-button type="primary" size="small"&gt;&lt;PlusOutlined/&gt;新建团队&lt;/a-button&gt;&lt;/div&gt;&lt;div &gt;&lt;div &gt;团队&lt;b &gt;3&lt;/b&gt;&lt;/div&gt;&lt;div &gt;成员&lt;b &gt;28&lt;/b&gt;&lt;/div&gt;&lt;/div&gt;&lt;div &gt;&lt;div v-for="t in list" :key="t.id" &gt;&lt;div  :style="{background:t.c+'15',color:t.c}"&gt;&lt;TeamOutlined/&gt;&lt;/div&gt;&lt;div &gt;&lt;h4&gt;{{ t.name }}&lt;/h4&gt;&lt;p&gt;{{ t.desc }}&lt;/p&gt;&lt;/div&gt;&lt;div &gt;&lt;span &gt;{{ t.ms }} 成员&lt;/span&gt;&lt;a-button size="small" type="link"&gt;管理&lt;/a-button&gt;&lt;/div&gt;&lt;/div&gt;&lt;/div&gt;&lt;/div&gt;&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref } from 'vue'
import { UsergroupAddOutlined, TeamOutlined, PlusOutlined } from '@ant-design/icons-vue'
const list=ref([{id:'1',name:'前端开发组',desc:'负责 Neurova UI 开发和维护',ms:8,c:'#3b82f6'},{id:'2',name:'AI 核心组',desc:'Agent 能力开发和模型调优',ms:12,c:'#8b5cf6'},{id:'3',name:'基础设施组',desc:'服务器、数据库和 DevOps',ms:6,c:'#34d399'}])
&lt;/script&gt;
&lt;style scoped&gt;
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
&lt;/style&gt;
&nbsp;
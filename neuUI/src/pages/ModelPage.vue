<template>
  <div class="pg">
    <div class="hd glass-effect">
      <h2 class="t"><CloudOutlined :style="{ color: '#8b5cf6' }" /> 模型管理</h2>
      <div class="hd-actions">
        <a-button @click="handleDetectAll" :loading="detectingAll"><RadarChartOutlined /> 检测全部能力</a-button>
        <a-button type="primary" @click="openAddProvider"><PlusOutlined /> 添加服务商</a-button>
      </div>
    </div>

    <div class="sr">
      <div class="s glass-effect">服务商<b class="c1">{{ providers.length }}</b></div>
      <div class="s glass-effect">已启用<b class="c3">{{ providers.filter(p => p.enabled !== false).length }}</b></div>
      <div class="s glass-effect">模型<b class="c2">{{ totalModels }}</b></div>
      <div class="s glass-effect">当前<b class="c4">{{ currentModel || '--' }}</b></div>
    </div>

    <a-alert v-if="error" :message="error" type="error" show-icon closable @close="error = ''" />
    <a-spin v-if="loading" size="large" style="display:flex;justify-content:center;padding:40px" />

    <div v-if="!loading && providers.length" class="grid">
      <div v-for="p in providers" :key="p.id" class="card-wrapper" :class="{ disabled: p.enabled === false }">
        <GlassContainer 
          :displacement-scale="60"
          :blur-amount="2.56"
          :saturation="160"
          :aberration-intensity="3"
          :corner-radius="28"
          padding="0"
          :over-light="false"
        >
          <div class="card">
            <!-- 状态圆点 -->
            <span class="status-dot" :class="p._available ? 'green' : 'red'" :title="p._available ? '可用' : '不可用'">
              <CheckCircleFilled v-if="p._available" />
              <CloseCircleFilled v-else />
            </span>
            <div class="card-top">
              <div class="card-avatar" :style="{ background: pColor(p.id) }">{{ (p.icon || p.name || '?')[0] }}</div>
              <div class="card-meta">
                <h4>{{ p.name }}</h4>
                <div class="card-tags">
                  <a-tag v-if="p.is_builtin" size="small" color="blue">内置</a-tag>
                  <a-tag size="small" :color="p.enabled !== false ? 'green' : 'default'">{{ p.enabled !== false ? '启用' : '禁用' }}</a-tag>
                  <a-tag size="small" color="purple">{{ p.provider || 'openai' }}</a-tag>
                </div>
              </div>
            </div>
            <div class="card-body">
              <div class="info-row"><CloudServerOutlined class="ii" /> <span class="iv">{{ p.base_url || '--' }}</span></div>
              <div class="info-row"><KeyOutlined class="ii" /> <span class="iv">{{ p.has_api_key ? '🔑 已配置' : '⚠️ 未配置' }}</span></div>
              <div class="info-row"><BlockOutlined class="ii" /> <span class="iv">内置 {{ (p.models || []).length }} 个模型</span></div>
            </div>
            <div class="card-actions">
              <a-button size="small" type="primary" ghost @click="openModelModal(p)"><BlockOutlined /> 模型</a-button>
              <a-button size="small" @click="openSettings(p)"><SettingOutlined /> 设置</a-button>
              <a-button size="small" @click="handleTest(p)"><ApiOutlined /> 测试</a-button>
              <a-button size="small" :type="p.enabled !== false ? 'default' : 'primary'" ghost @click="handleToggle(p)">{{ p.enabled !== false ? '禁用' : '启用' }}</a-button>
              <a-popconfirm v-if="!p.is_builtin" title="删除服务商及模型?" @confirm="handleDelete(p.id)">
                <a-button size="small" danger><DeleteOutlined /></a-button>
              </a-popconfirm>
            </div>
          </div>
        </GlassContainer>
      </div>
    </div>
    <div v-else-if="!loading" class="empty-state glass-effect"><CloudOutlined style="font-size:48px;color:rgba(255,255,255,0.1)" /><p>暂无服务商</p></div>

    <!-- 服务商弹窗 -->
    <a-modal v-model:open="pmOpen" :title="editingP ? '编辑服务商' : '添加服务商'" @ok="saveP" :confirm-loading="saving" ok-text="保存" cancel-text="取消" width="520px">
      <a-form layout="vertical">
        <a-form-item label="名称" required><a-input v-model:value="pf.name" placeholder="DeepSeek/OpenAI" /></a-form-item>
        <a-form-item label="协议类型" required><a-select v-model:value="pf.protocol" :options="protoOpts" /></a-form-item>
        <a-form-item label="API URL" required><a-input v-model:value="pf.url" placeholder="https://api.xxx.com/v1" /></a-form-item>
        <a-form-item label="API Key">
          <template v-if="editingP && !pf._showKey">
            <span style="color:rgba(255,255,255,0.45)">🔒 已配置（留空保持不变）</span>
            <a-button type="link" size="small" @click="pf._showKey=true" style="padding:0 8px">更改</a-button>
          </template>
          <a-input-password v-else v-model:value="pf.api_key" :placeholder="editingP?'输入新密钥':'sk-xxx'" />
        </a-form-item>
        <a-form-item label="描述"><a-textarea v-model:value="pf.desc" placeholder="服务商描述" :rows="2" /></a-form-item>
      </a-form>
    </a-modal>

    <!-- 设置弹窗（协议+APIKey） -->
    <a-modal v-model:open="setOpen" title="设置：{{ settingP?.name || '' }}" @ok="saveSettings" :confirm-loading="setSaving" ok-text="保存并测试" cancel-text="取消" width="480px">
      <a-form layout="vertical">
        <a-form-item label="兼容模式" extra="切换 OpenAI 或 Anthropic 协议">
          <a-select v-model:value="setForm.protocol" :options="protoOpts" />
        </a-form-item>
        <a-form-item label="API Key">
          <a-input-password
            v-model:value="setForm.apiKey"
            :placeholder="setForm._hasKey ? '已配置（留空保持不变）' : 'sk-xxx'"
          />
          <div v-if="setForm._hasKey" style="color:rgba(255,255,255,0.45);font-size:0.78rem;margin-top:4px">
            ✅ 已配置（留空保持不变，输入新值将覆盖）
          </div>
          <div v-else style="color:rgba(255,255,255,0.3);font-size:0.78rem;margin-top:4px">
            未配置，请输入
          </div>
        </a-form-item>
        <a-form-item label="API URL" v-if="settingP && !settingP.is_builtin" extra="自定义服务商可修改 URL">
          <a-input v-model:value="setForm.url" placeholder="https://api.xxx.com/v1" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 模型管理浮层（modal） -->
    <a-modal v-model:open="mmOpen" :title="'「'+(activeP?.name||'')+'」模型配置'" width="720px" :footer="null">
      <template v-if="activeP">
        <a-table :columns="mCols" :data-source="activePModels" row-key="name" size="middle" :pagination="false" style="margin-bottom:16px">
          <template #bodyCell="{column,record}">
            <template v-if="column.key==='caps'">
              <template v-if="record.capabilities?.length"><a-tag v-for="c in record.capabilities" :key="c" size="small" :color="capC(c)">{{ capL(c) }}</a-tag></template>
              <span v-else class="cu">未检测</span>
            </template>
            <template v-if="column.key==='st'"><a-switch v-model:checked="record.enabled" size="small" @change="toggleModel(record)" /></template>
            <template v-if="column.key==='act'"><a-space><a-button type="link" size="small" @click="editM(record)"><EditOutlined /></a-button><a-button type="link" size="small" :loading="record._detect" @click="detectOne(record)"><ScanOutlined /></a-button><a-popconfirm title="删除?" @confirm="delM(record.name)"><a-button type="link" size="small" danger><DeleteOutlined /></a-button></a-popconfirm></a-space></template>
          </template>
        </a-table>
        <a-card size="small" :title="editMN ? '编辑: '+editMN : '添加模型'" style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06)">
          <a-form layout="inline" style="flex-wrap:wrap;gap:8px">
            <a-form-item label="标识"><a-input v-model:value="mf.name" placeholder="模型标识" style="width:150px" :disabled="!!editMN" /></a-form-item>
            <a-form-item label="显示名"><a-input v-model:value="mf.dname" placeholder="友好名称" style="width:130px" /></a-form-item>
            <a-form-item label="Token"><a-input-number v-model:value="mf.maxT" :min="1024" :max="131072" :step="1024" style="width:100px" /></a-form-item>
          </a-form>
          <div style="margin:8px 0">
            <span style="color:rgba(255,255,255,0.4);font-size:.78rem">能力：</span>
            <a-checkbox-group v-model:value="mf.caps" style="margin-left:4px">
              <a-checkbox value="text">📝纯文本</a-checkbox><a-checkbox value="image_understand">🖼️图形</a-checkbox>
              <a-checkbox value="video_understand">🎬视频</a-checkbox><a-checkbox value="audio_understand">🎵语音</a-checkbox>
              <a-checkbox value="image_generate">🎨图像生成</a-checkbox><a-checkbox value="video_generate">🎞️视频生成</a-checkbox>
              <a-checkbox value="audio_generate">🔊音频生成</a-checkbox>
            </a-checkbox-group>
            <a-button type="link" size="small" style="margin-left:8px" @click="autoDetectCaps" :loading="detectingOne"><ScanOutlined />自动检测</a-button>
          </div>
          <a-space><a-button type="primary" size="small" @click="saveM" :loading="savingModel">{{ editMN?'更新':'添加并测试' }}</a-button><a-button v-if="editMN" size="small" @click="cancelEditM">取消</a-button></a-space>
        </a-card>
      </template>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, reactive, onMounted } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { providerAPI, type ProviderCreateRequest, type ProviderUpdateRequest } from '@/api/modules/providers'
import { modelAPI } from '@/api/modules/models'
import { CloudOutlined, PlusOutlined, EditOutlined, DeleteOutlined, ApiOutlined, CloudServerOutlined, KeyOutlined, BlockOutlined, ScanOutlined, RadarChartOutlined, CheckCircleFilled, CloseCircleFilled, SettingOutlined } from '@ant-design/icons-vue'
import { GlassContainer } from '@/components/NeuGlass'

interface ProviderData {
  id: string
  name: string
  provider?: string
  protocol?: string
  base_url?: string
  url?: string
  description?: string
  has_api_key?: boolean
  is_builtin?: boolean
  enabled?: boolean
  models?: (string | { name?: string; model?: string; displayName?: string; model_display_name?: string; capabilities?: string[]; caps?: string[]; enabled?: boolean; max_tokens?: number })[]
  model_capabilities?: Record<string, string[]>
  _modelCaps?: Record<string, string[]>
  _available?: boolean
}

const loading=ref(false);const error=ref('');const saving=ref(false);const savingModel=ref(false)
const providers=ref<ProviderData[]>([]);const currentModel=ref('');const currentProvider=ref('')
const detectingOne=ref(false);const detectingAll=ref(false)

const pmOpen=ref(false);const editingP=ref(false);const editingPid=ref('')
const pf=reactive<ProviderCreateRequest&{desc:string;url:string;protocol:string;_showKey:boolean}>({name:'',provider:'openai',base_url:'',api_key:'',description:'',desc:'',url:'',protocol:'openai',_showKey:false})
const protoOpts=[{label:'OpenAI兼容',value:'openai'},{label:'Anthropic',value:'anthropic'},{label:'自定义',value:'custom'}]

// 设置弹窗
const setOpen=ref(false);const setSaving=ref(false);const settingP=ref<ProviderData | null>(null)
const setForm=reactive({protocol:'openai',apiKey:'',url:'',_hasKey:false})

function openSettings(p: ProviderData) {
  settingP.value = p
  setForm.protocol = p.provider || p.protocol || 'openai'
  setForm.apiKey = ''
  setForm.url = p.base_url || ''
  setForm._hasKey = !!p.has_api_key
  setOpen.value = true
}
async function saveSettings(){
  if(!settingP.value)return;setSaving.value=true
  try{
    const d:ProviderUpdateRequest={}
    const hasNewKey=!!setForm.apiKey
    if(hasNewKey)d.api_key=setForm.apiKey
    if(!settingP.value.is_builtin&&setForm.url)d.base_url=setForm.url
    const r=await providerAPI.update(settingP.value.id,d)
    if(r?.success||r?.code===0){
      message.success('设置已保存')
      setOpen.value=false
      await loadData()
      // 保存后自动测试连通性
      const testR=await providerAPI.test(settingP.value.id)
      const prov=providers.value.find(x=>x.id===settingP.value?.id)
      if(testR?.success||testR?.code===0){
        const td=testR.data||{}
        if(td.health_status==='unconfigured')message.warning('保存成功，但未配置API Key')
        else if(td.is_healthy){
          if(prov)prov._available=true
          message.success('连接测试通过 ✓')
          // 自动触发能力检测并持久化
          if(hasNewKey&&prov?.models?.length){
            try{const capsRes=await modelAPI.detectCapability(prov.id);if(capsRes?.success||capsRes?.code===0){const results=capsRes.data?.results||{};prov._modelCaps=results;if(Object.keys(results).length)message.success(`自动检测: ${Object.keys(results).length} 个模型能力已记录`)}}catch{}
          }
        }
        else{if(prov)prov._available=false;message.error('连接测试未通过')}
      }
    }else message.error(r?.message||'保存失败')
  }catch(e:unknown){const err=e as {message?:string};message.error(err?.message||'保存失败')}
  finally{setSaving.value=false}
}

// 模型浮层（modal 替代 drawer）
const mmOpen=ref(false);const activeP=ref<ProviderData | null>(null);const editMN=ref('')
const mf=reactive({name:'',dname:'',maxT:8192,caps:['text'] as string[]})
const mCols=[{title:'模型名',dataIndex:'name'},{title:'能力标签',key:'caps',width:280},{title:'启用',key:'st',width:60},{title:'操作',key:'act',width:160}]

const capL:Record<string,string>={text:'📝纯文本',image_understand:'🖼️图形',video_understand:'🎬视频',audio_understand:'🎵语音',image_generate:'🎨图像生成',video_generate:'🎞️视频生成',audio_generate:'🔊音频生成'}
const capC:Record<string,string>={text:'blue',image_understand:'green',video_understand:'purple',audio_understand:'orange',image_generate:'pink',video_generate:'magenta',audio_generate:'gold'}

const pColors=['#3b82f6','#8b5cf6','#10b981','#f59e0b','#ef4444','#06b6d4','#f472b6','#6366f1','#14b8a6','#f97316','#84cc16','#ec4899','#0ea5e9','#a855f7','#22c55e','#eab308','#ef4444','#64748b','#0891b2','#d946ef']
function pColor(id:string){let h=0;for(let i=0;i<id.length;i++)h=id.charCodeAt(i)+((h<<5)-h);return pColors[Math.abs(h)%pColors.length]}

const totalModels=computed(()=>providers.value.reduce((s,p)=>s+(p.models?.length||0),0))
const activePModels=computed(()=>{if(!activeP.value)return[];return (activeP.value.models||[]).map((m)=>{if(typeof m==='string')return{name:m,displayName:m,capabilities:(activeP.value!._modelCaps||{})[m]||[],enabled:true};return{name:m.name||m.model||'',displayName:m.displayName||m.model_display_name||m.name||'',capabilities:m.capabilities||m.caps||[],enabled:m.enabled!==false,maxTokens:m.max_tokens}})})

async function loadData(){loading.value=true;error.value='';try{const[pr,cr]=await Promise.all([providerAPI.list().catch(e=>({success:false,_err:e})),modelAPI.getCurrent().catch(e=>({success:false,_err:e}))]);if(pr?.success||pr?.code===0){const raw=pr.data?.providers||[];providers.value=raw.map((p)=>({...p,_modelCaps:p.model_capabilities||{},_available:p.has_api_key}));const builtin=raw.filter((p)=>p.is_builtin).length;localStorage.setItem('builtinProviders',JSON.stringify(builtin))}else error.value=pr?.message||pr?._err?.message||'获取服务商列表失败';if(cr?.success&&cr.data){currentProvider.value=cr.data.provider_id||'';currentModel.value=cr.data.model||''}}catch(e:unknown){const err=e as {message?:string};error.value=err?.message||'加载失败'}finally{loading.value=false}}

// 服务商连通检测 + 能力自动检测（已配置 Key 的自动检测能力并持久化）
async function checkProvidersAvailability(){for(const p of providers.value){if(!p.has_api_key)continue;try{const r=await providerAPI.test(p.id);if(r?.success||r?.code===0){const d=r.data||{};p._available=!!d.is_healthy}}catch{p._available=false}
  // 连通且无能力数据 → 自动检测
  if(p._available&&p.models?.length&&!Object.keys(p._modelCaps||{}).length){try{const capsRes=await modelAPI.detectCapability(p.id);if(capsRes?.success||capsRes?.code===0){const results=capsRes.data?.results||{};p._modelCaps=results;if(Object.keys(results).length)message.success(`${p.name}: ${Object.keys(results).length} 个模型能力已检测并记录`)}}catch{}}}}

// 单个服务商刷新能力（从后端重载）
async function refreshCaps(pid:string){try{const r=await modelAPI.getCapabilities(pid);if(r?.success||r?.code===0){const caps=r.data?.model_capabilities||{};const p=providers.value.find(x=>x.id===pid);if(p){p._modelCaps=caps}}}catch{}}

onMounted(async()=>{await loadData();checkProvidersAvailability()})

function openAddProvider(){editingP.value=false;editingPid.value='';pf.name='';pf.protocol='openai';pf.url='';pf.api_key='';pf.desc='';pf._showKey=true;pmOpen.value=true}
function openEditProvider(p:ProviderData){editingP.value=true;editingPid.value=p.id;pf.name=p.name;pf.protocol=p.provider||p.protocol||'openai';pf.url=p.base_url||p.url||'';pf.api_key='';pf.desc=p.description||'';pf._showKey=false;pmOpen.value=true}
async function saveP(){if(!pf.name.trim()||!pf.url.trim()){message.warning('请填写名称和API URL');return};saving.value=true;try{if(editingP.value){const d:ProviderUpdateRequest={name:pf.name,base_url:pf.url,description:pf.desc};if(pf.api_key)d.api_key=pf.api_key;const r=await providerAPI.update(editingPid.value,d);if(r?.success||r?.code===0)message.success('已更新');else message.error(r?.message||'失败')}else{const r=await providerAPI.create({name:pf.name,provider:pf.protocol,base_url:pf.url,api_key:pf.api_key||undefined,description:pf.desc});if(r?.success||r?.code===0)message.success('已创建');else message.error(r?.message||'失败')};pmOpen.value=false;await loadData();checkProvidersAvailability()}catch(e:unknown){const err=e as {message?:string};message.error(err?.message||'保存失败')}finally{saving.value=false}}
async function handleDelete(id:string){try{const r=await providerAPI.delete(id);if(r?.success||r?.code===0){message.success('已删除');await loadData()}else message.error(r?.message||'失败')}catch(e:unknown){const err=e as {message?:string};message.error(err?.message||'失败')}}
async function handleToggle(p:ProviderData){const v=p.enabled===false;try{const r=await providerAPI.toggle(p.id,v);if(r?.success||r?.code===0){p.enabled=v;message.success(v?'已启用':'已禁用')}else message.error(r?.message||'失败')}catch(e:unknown){const err=e as {message?:string};message.error(err?.message||'失败')}}
async function handleTest(p:ProviderData){try{const r=await providerAPI.test(p.id);if(r?.success||r?.code===0){const d=r.data||{};if(d.health_status==='unconfigured'){message.warning(d.message||'未配置 API Key，无法测试')}else if(d.is_healthy){p._available=true;message.success('连接成功')}else{p._available=false;message.error('连接失败: '+(d.health_status||'unhealthy'))}}else message.error(r?.message||'测试失败')}catch(e:unknown){const err=e as {message?:string};message.error(err?.message||'测试失败')}}

// 模型浮层（modal）
function openModelModal(p:ProviderData){activeP.value=p;editMN.value='';mf.name='';mf.dname='';mf.maxT=8192;mf.caps=['text'];mmOpen.value=true}
function editM(m:{name:string;displayName?:string;maxTokens?:number;capabilities?:string[]}){editMN.value=m.name;mf.name=m.name;mf.dname=m.displayName||m.name;mf.maxT=m.maxTokens||8192;mf.caps=m.capabilities?.slice()||['text']}
function cancelEditM(){editMN.value='';mf.name='';mf.dname='';mf.maxT=8192;mf.caps=['text']}
async function delM(name:string){try{const r=await modelAPI.remove(activeP.value!.id,name);if(r?.success||r?.code===0){message.success('已删除');await refreshP()}else message.error(r?.message||'失败')}catch(e:unknown){const err=e as {message?:string};message.error(err?.message||'失败')}}
function toggleModel(m:{name:string;enabled?:boolean}){message.info(`「${m.name}」${m.enabled?'已启用':'已禁用'}`)}
async function saveM(){if(!mf.name.trim()){message.warning('请输入模型名');return}

  // 新增模型时：先测试连通性
  if(!editMN.value){
    savingModel.value=true
    try{
      const testRes=await providerAPI.test(activeP.value.id)
      const connected=testRes?.success&&testRes.data?.is_healthy
      if(!connected){
        // 不可连通 → 弹窗确认
        const reason=testRes?.data?.health_status==='unconfigured'?'未配置 API Key':(testRes?.data?.health_status||'无法连接')
        await new Promise<void>((resolve,reject)=>{
          Modal.confirm({
            title:'连接测试失败',
            content:`「${activeP.value.name}」${reason}。是否仍然添加该模型？`,
            okText:'继续添加',
            cancelText:'取消',
            onOk:()=>resolve(),
            onCancel:()=>reject(new Error('USER_CANCEL')),
          })
        })
      }
    }catch(e:unknown){const err=e as {message?:string};if(err.message==='USER_CANCEL'){savingModel.value=false;return}/* 其他错误继续添加 */}
    savingModel.value=false
  }

  savingModel.value=true
  try{
    if(editMN.value){const r=await modelAPI.updateModel(activeP.value.id,editMN.value,{model_display_name:mf.dname||undefined,max_tokens:mf.maxT,capabilities:mf.caps});if(r?.success||r?.code===0){message.success('已更新');cancelEditM();await refreshP()}else message.error(r?.message||'失败')}
    else{const r=await modelAPI.add({provider_id:activeP.value.id,model_name:mf.name,model_display_name:mf.dname||undefined,max_tokens:mf.maxT,capabilities:mf.caps});if(r?.success||r?.code===0){message.success('已添加');mf.name='';mf.dname='';mf.caps=['text'];await refreshP()}else message.error(r?.message||'失败')}
  }catch(e:unknown){const err=e as {message?:string};message.error(err?.message||'保存失败')}
  finally{savingModel.value=false}
}
async function autoDetectCaps(){if(!mf.name.trim()&&!editMN.value){message.warning('请先输入模型名');return};detectingOne.value=true;try{const r=await modelAPI.detectCapability(activeP.value.id,mf.name||editMN.value);if(r?.success||r?.code===0){const results=r.data?.results||{};const caps=results[mf.name||editMN.value||'']||[];if(caps.length){mf.caps=caps;message.success(`检测到${caps.length}项能力: ${caps.join(',')}`)}}}catch{}finally{detectingOne.value=false}}
async function detectOne(m:{name:string;_detect?:boolean}){m._detect=true;try{const r=await modelAPI.detectCapability(activeP.value!.id,m.name);if(r?.success||r?.code===0){const results=r.data?.results||{};const caps=results[m.name]||[];if(caps.length){m.capabilities=caps;if(activeP.value._modelCaps)activeP.value._modelCaps[m.name]=caps;message.success(`${m.name}:${caps.length}项已记录`)}}}catch{}finally{m._detect=false}}
async function handleDetectAll(){detectingAll.value=true;let c=0;for(const p of providers.value){if(!p.models?.length)continue;try{const r=await modelAPI.detectCapability(p.id);if(r?.success||r?.code===0){const results=r.data?.results||{};p._modelCaps=results;c+=Object.keys(results).length}}catch{}}message.success(`全部检测完成: ${c} 项能力已记录`);detectingAll.value=false}
async function refreshP(){try{const r=await providerAPI.list();if(r?.success||r?.code===0){const newP=(r.data?.providers||[]).map((p:Record<string,unknown>)=>({...p,_modelCaps:(p.model_capabilities as Record<string,string[]>)||{}}));const cur=providers.value.find(x=>x.id===activeP.value?.id);const upd=newP.find(x=>x.id===activeP.value?.id);if(cur&&upd){Object.assign(cur,upd);activeP.value=cur}}}catch{}}
</script>

<style scoped>
.pg{display:flex;flex-direction:column;gap:16px}
.hd{
  padding:18px 28px;
  border-radius:24px;
  display:flex;
  justify-content:space-between;
  align-items:center;
  background: linear-gradient(
    135deg,
    rgba(255,255,255,0.08) 0%,
    rgba(255,255,255,0.03) 50%,
    rgba(255,255,255,0.06) 100%
  );
  border: 1px solid rgba(255,255,255,0.1);
  box-shadow:
    0 8px 32px rgba(0,0,0,0.2),
    inset 0 0 0 0.5px rgba(255,255,255,0.08),
    inset 0 1px 0 rgba(255,255,255,0.15);
  backdrop-filter: blur(40px) saturate(180%);
  -webkit-backdrop-filter: blur(40px) saturate(180%);
}
.hd-actions{display:flex;gap:10px}
.t{font-size:1.25rem;color:#e2e8f0;margin:0;display:flex;align-items:center;gap:10px;font-weight:600;letter-spacing:-0.2px}
.sr{display:flex;gap:14px}
.s{
  flex:1;
  padding:18px 22px;
  border-radius:20px;
  display:flex;
  justify-content:space-between;
  align-items:center;
  color:rgba(255,255,255,0.55);
  font-size:.86rem;
  background: linear-gradient(
    135deg,
    rgba(255,255,255,0.07) 0%,
    rgba(255,255,255,0.02) 100%
  );
  border: 1px solid rgba(255,255,255,0.08);
  box-shadow:
    0 4px 24px rgba(0,0,0,0.15),
    inset 0 0 0 0.5px rgba(255,255,255,0.06);
  backdrop-filter: blur(32px) saturate(180%);
  -webkit-backdrop-filter: blur(32px) saturate(180%);
  transition: all 0.35s cubic-bezier(0.4,0,0.2,1);
}
.s:hover{
  transform: translateY(-2px);
  box-shadow:
    0 8px 32px rgba(0,0,0,0.22),
    inset 0 0 0 0.5px rgba(255,255,255,0.1);
}
.s b{font-size:1.5rem;font-weight:700}.c1{color:#8b5cf6}.c2{color:#f59e0b}.c3{color:#34d399}.c4{color:#60a5fa}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:18px}

/* 卡片包裹层 */
.card-wrapper{display:block;position:relative;isolation:isolate;overflow:visible}
.card-wrapper.disabled{opacity:.55;filter:grayscale(0.3)}

/* iOS 16 液态玻璃卡片 - 现在是内容层 */
.card{
  padding:22px;
  border-radius:28px;
  display:flex;
  flex-direction:column;
  gap:14px;
  position:relative;
  overflow:hidden;
  background:
    radial-gradient(
      120px 80px at 20% 0%,
      rgba(139,92,246,0.12) 0%,
      transparent 100%
    ),
    radial-gradient(
      90px 60px at 90% 20%,
      rgba(99,102,241,0.08) 0%,
      transparent 100%
    ),
    linear-gradient(
      145deg,
      rgba(255,255,255,0.08) 0%,
      rgba(255,255,255,0.03) 50%,
      rgba(255,255,255,0.06) 100%
    );
  border: 1px solid rgba(255,255,255,0.12);
  box-shadow:
    0 8px 32px rgba(0,0,0,0.25),
    0 2px 8px rgba(0,0,0,0.1),
    inset 0 0 0 0.5px rgba(255,255,255,0.12),
    inset 0 1px 0 rgba(255,255,255,0.18);
  backdrop-filter: blur(40px) saturate(180%);
  -webkit-backdrop-filter: blur(40px) saturate(180%);
}

.card.disabled{opacity:.55;filter:grayscale(0.3)}
.card.disabled:hover{transform:none}

/* 状态圆点 */
.status-dot{
  position:absolute;
  top:18px;
  right:18px;
  font-size:1.15rem;
  line-height:1;
  padding:4px;
  border-radius:50%;
  background:rgba(0,0,0,0.2);
  backdrop-filter: blur(8px);
}
.status-dot.green{color:#34d399;text-shadow:0 0 12px rgba(52,211,153,0.4)}
.status-dot.red{color:#ef4444;text-shadow:0 0 12px rgba(239,68,68,0.4)}

.card-top{display:flex;align-items:center;gap:14px}
.card-avatar{
  width:52px;height:52px;
  border-radius:16px;
  display:flex;align-items:center;justify-content:center;
  color:#fff;font-weight:800;font-size:1.25rem;
  flex-shrink:0;
  box-shadow:
    0 8px 24px rgba(0,0,0,0.3),
    inset 0 0 0 0.5px rgba(255,255,255,0.2);
}
.card-meta{flex:1}.card-meta h4{color:#e2e8f0;margin:0 0 6px;font-size:1rem;font-weight:600;letter-spacing:-0.2px}
.card-tags{display:flex;gap:8px}
.card-body{display:flex;flex-direction:column;gap:8px}
.info-row{display:flex;align-items:center;gap:10px;color:rgba(255,255,255,0.48);font-size:.82rem}
.ii{font-size:.9rem;opacity:.7}.iv{font-family:monospace;font-size:.8rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:260px}
.card-actions{
  display:flex;gap:10px;flex-wrap:wrap;
  border-top:1px solid rgba(255,255,255,0.08);
  padding-top:14px;
  margin-top:4px;
}
.empty-state{
  text-align:center;padding:80px 30px;border-radius:28px;
  display:flex;flex-direction:column;align-items:center;gap:18px;
  background: linear-gradient(
    135deg,
    rgba(255,255,255,0.05) 0%,
    rgba(255,255,255,0.02) 100%
  );
  border:1px solid rgba(255,255,255,0.08);
  backdrop-filter: blur(40px) saturate(180%);
  -webkit-backdrop-filter: blur(40px) saturate(180%);
}
.empty-state p{color:rgba(255,255,255,0.35);margin:0;font-size:.95rem}
.cu{color:rgba(255,255,255,0.22);font-size:.78rem;font-style:italic}
</style>

<template>
  <div >
    <!-- 顶部工具栏 -->
    <div >
      <h2 ><ApartmentOutlined /> 工作流设计</h2>
      <a-space>
        <a-select v-model:value="currentWfId" style="width:180px" :options="wfOptions" @change="loadWorkflow" placeholder="选择工作流" />
        <a-input v-model:value="wfName" placeholder="新工作流名称" style="width:150px" size="small" />
        <a-button size="small" type="primary" @click="createWf"><PlusOutlined /></a-button>
        <a-button size="small" @click="saveWf"><SaveOutlined /></a-button>
        <a-popconfirm title="删除?" @confirm="delWf"><a-button size="small" danger><DeleteOutlined /></a-button></a-popconfirm>
        <a-divider type="vertical" />
        <a-button size="small" type="primary" ghost @click="aiGenOpen=true" style="background:linear-gradient(135deg,rgba(139,92,246,0.2),rgba(59,130,246,0.15));border-color:rgba(139,92,246,0.3)">
          ✨ AI 设计
        </a-button>
        <a-divider type="vertical" />
        <a-button size="small" ghost @click="undo" :disabled="!canUndo"><UndoOutlined /></a-button>
        <a-badge :count="nodes.length" :number-style="{background:'#60a5fa'}" title="节点数" />
        <a-badge :count="edges.length" :number-style="{background:'#a78bfa'}" title="连线数" />
      </a-space>
      <a-space style="margin-left:auto">
        <a-button size="small" type="text" @click="helpOpen=true"><QuestionCircleOutlined /></a-button>
        <span >{{ Math.round(zoom * 100) }}%</span>
        <a-button size="small" shape="circle" @click="zoomOut"><MinusOutlined /></a-button>
        <a-button size="small" shape="circle" @click="zoomIn"><PlusOutlined /></a-button>
        <a-button size="small" @click="fitView"><ExpandOutlined /></a-button>
      </a-space>
    </div>
    <div >
      <!-- 左侧节点面板（AI 内容输出分类） -->
      <div >
        <div >🧩 节点库</div>
        <div v-for="cat in nodeCategories" :key="cat.key" >
          <div  @click="cat.open=!cat.open">
            <span  :>▶</span>
            <span >{{ cat.icon }}</span>
            <span >{{ cat.label }}</span>
            <span >{{ cat.items.length }}</span>
          </div>
          <div v-show="cat.open" >
            <div v-for="nt in cat.items" :key="nt.type"  :title="nt.desc" draggable="true" @dragstart="onDragStart($event, nt)">
              <span  :style="{background:nt.color}"></span>
              <span >{{ nt.icon }}</span>
              <span >{{ nt.label }}</span>
            </div>
          </div>
        </div>
        <div style="margin-top:auto;padding-top:8px">
          <a-button size="small" type="dashed" block @click="helpOpen=true" style="font-size:.72rem;color:rgba(255,255,255,0.35)">📖 使用帮助</a-button>
        </div>
      </div>
      <!-- 画布 -->
      <div  @drop="onDrop" @dragover.prevent>
        <VueFlow
          ref="vfRef"
          v-model:nodes="nodes"
          v-model:edges="edges"
          :node-types="customNodeTypes"
          :default-viewport="{ x: 0, y: 0, zoom: 1 }"
          :min-zoom="0.1"
          :max-zoom="4"
          :snap-to-grid="true"
          :snap-grid="[20, 20]"
          :default-edge-options="{ type: 'smoothstep', animated: true, style: { stroke: 'rgba(150,180,210,0.5)', strokeWidth: 1.5 } }"
          fit-view-on-init
          connection-line-style="color:rgba(96,165,250,0.5)"
          @connect="onConnect"
          @viewport-change="onViewportChange"
          @pane-click="selectedNode=null"
          @node-click="onNodeSelect"
          @node-double-click="onNodeDblClick"
          delete-key-code="Delete"
          multi-selection-key-code="Shift"
        >
          <template #node-default="props">
            <WorkflowNode :id="props.id" :data="props.data" :type-name="props.type" :selected="selectedNode===props.id"
              @delete="removeNode(props.id)" @configure="openNodeConfig(props.id)" />
          </template>
        </VueFlow>
        <!-- 画布提示 -->
        <div  v-if="!nodes.length">
          <div >🖱️</div>
          <div>从左侧<span style="color:#60a5fa">拖拽节点</span>到画布<br>拖拽节点圆点<span style="color:#a78bfa">连线</span> · 滚轮缩放 · Alt+/-缩放</div>
        </div>
      </div>
    </div>
    <!-- 节点配置抽屉 -->
    <a-drawer v-model:open="configOpen" :title="'⚙ '+ (configNode?.data?.label || '节点配置')" width="400px" placement="right">
      <template v-if="configNode">
        <a-form layout="vertical" size="small">
          <a-form-item label="节点名称"><a-input v-model:value="configForm.label" /></a-form-item>
          <a-form-item label="节点描述"><a-input v-model:value="configForm.description" placeholder="简要说明该节点的作用" /></a-form-item>
          <!-- AI 处理类 -->
          <template v-if="configNode.type==='llm'">
            <a-form-item label="选择 LLM（已联通的服务商）">
              <a-row :gutter="8">
                <a-col :span="12"><a-select v-model:value="configForm.llmProviderId" placeholder="服务商" :options="providerOpts" size="small" style="width:100%" @change="(v:string)=>{configForm.llmProviderId=v;configForm.model=''}" /></a-col>
                <a-col :span="12"><a-select v-model:value="configForm.model" placeholder="模型" :options="llmModelOpts" size="small" style="width:100%" show-search /></a-col>
              </a-row>
              <div v-if="!providerOpts.length" style="font-size:.7rem;color:#ef4444;margin-top:4px">⚠ 暂无已联通的服务商</div>
            </a-form-item>
            <a-divider style="margin:8px 0;border-color:rgba(255,255,255,0.05)" />
            <a-form-item label="System Prompt"><a-textarea v-model:value="configForm.prompt" :rows="3" placeholder="定义 AI 的角色和行为..." /></a-form-item>
            <a-form-item label="用户输入模板"><a-textarea v-model:value="configForm.userTemplate" :rows="2" placeholder="使用 {{$input}} 引用上游输出" /></a-form-item>
            <a-form-item label="Temperature"><a-slider v-model:value="configForm.temperature" :min="0" :max="2" :step="0.1" /></a-form-item>
            <a-form-item label="Max Tokens"><a-input-number v-model:value="configForm.maxTokens" :min="256" :max="131072" :step="256" style="width:100%" /></a-form-item>
          </template>
          <template v-else-if="configNode.type==='rag'">
            <a-form-item label="知识库"><a-input v-model:value="configForm.kbName" placeholder="选择知识库" /></a-form-item>
            <a-form-item label="检索方式"><a-radio-group v-model:value="configForm.retrievalMode"><a-radio value="semantic">语义搜索</a-radio><a-radio value="keyword">关键词</a-radio><a-radio value="hybrid">混合</a-radio></a-radio-group></a-form-item>
            <a-form-item label="Top K"><a-input-number v-model:value="configForm.topK" :min="1" :max="20" style="width:100%" /></a-form-item>
          </template>
          <template v-else-if="configNode.type==='prompt'">
            <a-form-item label="Prompt 模板"><a-textarea v-model:value="configForm.template" :rows="4" placeholder="可使用 {{$input}} {{$memory}} {{$context}} 等变量" /></a-form-item>
          </template>
          <template v-else-if="configNode.type==='context'">
            <a-form-item label="上下文窗口大小"><a-input-number v-model:value="configForm.contextWindow" :min="1" :max="100" style="width:100%" /></a-form-item>
            <a-form-item label="组装策略"><a-radio-group v-model:value="configForm.contextStrategy"><a-radio value="recent">最近N轮</a-radio><a-radio value="summary">摘要压缩</a-radio><a-radio value="relevance">相关性筛选</a-radio></a-radio-group></a-form-item>
          </template>
          <!-- 内容生成类 -->
          <!-- LLM 选择器（仅联通且有能力的服务商） -->
          <template v-if="genTypes.includes(configNode.type)">
            <a-form-item :label="'选择 LLM（已联通且有'+genCapLabel(configNode.type)+'能力）'">
              <a-row :gutter="8">
                <a-col :span="12"><a-select v-model:value="configForm.genProviderId" placeholder="服务商" :options="providerOpts" size="small" style="width:100%" @change="(v:string)=>onGenPChange(v,configNode.type)" /></a-col>
                <a-col :span="12"><a-select v-model:value="configForm.genModel" placeholder="模型" :options="genModelOpts(configNode.type)" size="small" style="width:100%" show-search /></a-col>
              </a-row>
              <div v-if="!genModelOpts(configNode.type).length" style="font-size:.7rem;color:#ef4444;margin-top:4px">⚠ 暂无具备所需能力的服务商，请先在「模型管理」配置并确保联通</div>
            </a-form-item>
            <a-divider style="margin:8px 0;border-color:rgba(255,255,255,0.05)" />
          </template>
          <template v-if="configNode.type==='gen-text'">
            <a-form-item label="生成风格"><a-select v-model:value="configForm.genStyle" :options="[{label:'正式',value:'formal'},{label:'创意',value:'creative'},{label:'简洁',value:'concise'},{label:'技术',value:'technical'}]" /></a-form-item>
            <a-form-item label="字数限制"><a-input-number v-model:value="configForm.wordLimit" :min="50" :max="10000" :step="100" style="width:100%" /></a-form-item>
          </template>
          <template v-if="configNode.type==='gen-code'">
            <a-form-item label="编程语言"><a-select v-model:value="configForm.codeLang" :options="[{label:'Python',value:'python'},{label:'JavaScript',value:'js'},{label:'TypeScript',value:'ts'},{label:'Go',value:'go'},{label:'Rust',value:'rust'}]" /></a-form-item>
            <a-form-item label="需求规格"><a-textarea v-model:value="configForm.codeSpec" :rows="4" placeholder="描述代码需要实现的功能、接口、异常处理等" /></a-form-item>
          </template>
          <template v-if="configNode.type==='gen-image'">
            <a-form-item label="画风"><a-select v-model:value="configForm.imgStyle" :options="[{label:'写实',value:'realistic'},{label:'插画',value:'illustration'},{label:'二次元',value:'anime'},{label:'3D渲染',value:'3d'},{label:'极简',value:'minimal'}]" /></a-form-item>
            <a-form-item label="分辨率"><a-select v-model:value="configForm.imgRes" :options="[{label:'1024×1024',value:'1024x1024'},{label:'1792×1024',value:'1792x1024'},{label:'1024×1792',value:'1024x1792'}]" /></a-form-item>
          </template>
          <template v-if="configNode.type==='gen-video'">
            <a-form-item label="时长（秒）"><a-input-number v-model:value="configForm.videoDuration" :min="3" :max="120" :step="1" style="width:100%" /></a-form-item>
            <a-form-item label="分辨率"><a-select v-model:value="configForm.videoRes" :options="[{label:'720p',value:'720p'},{label:'1080p',value:'1080p'}]" /></a-form-item>
            <a-form-item label="帧率"><a-input-number v-model:value="configForm.videoFps" :min="15" :max="60" :step="5" style="width:100%" /></a-form-item>
          </template>
          <!-- 后处理类 -->
          <template v-else-if="configNode.type==='format'">
            <a-form-item label="输出格式"><a-select v-model:value="configForm.outFormat" :options="[{label:'纯文本',value:'text'},{label:'Markdown',value:'md'},{label:'JSON',value:'json'},{label:'HTML',value:'html'},{label:'Table',value:'table'}]" /></a-form-item>
          </template>
          <template v-else-if="configNode.type==='translate'">
            <a-form-item label="源语言"><a-select v-model:value="configForm.srcLang" :options="langOpts" show-search /></a-form-item>
            <a-form-item label="目标语言"><a-select v-model:value="configForm.tgtLang" :options="langOpts" show-search /></a-form-item>
          </template>
          <template v-else-if="configNode.type==='summarize'">
            <a-form-item label="摘要方式"><a-radio-group v-model:value="configForm.summaryMode"><a-radio value="extractive">抽取式</a-radio><a-radio value="abstractive">生成式</a-radio><a-radio value="bullets">要点列表</a-radio></a-radio-group></a-form-item>
            <a-form-item label="目标字数"><a-input-number v-model:value="configForm.summaryWords" :min="50" :max="5000" :step="50" style="width:100%" /></a-form-item>
          </template>
          <template v-else-if="configNode.type==='extract'">
            <a-form-item label="提取目标"><a-textarea v-model:value="configForm.extractTarget" :rows="2" placeholder="描述要提取的内容：如「人名、日期、金额」" /></a-form-item>
          </template>
          <!-- 质量控制类 -->
          <template v-else-if="configNode.type==='validate'">
            <a-form-item label="验证规则"><a-textarea v-model:value="configForm.validateRule" :rows="2" placeholder="如：字数 > 100、包含关键词、JSON 格式正确" /></a-form-item>
            <a-form-item label="失败处理"><a-select v-model:value="configForm.failAction" :options="[{label:'阻断并报错',value:'block'},{label:'标记后继续',value:'warn'},{label:'自动修复',value:'fix'}]" /></a-form-item>
          </template>
          <template v-else-if="configNode.type==='review'">
            <a-form-item label="审核人"><a-select v-model:value="configForm.reviewer" placeholder="选择审核人" :options="memberOpts" /></a-form-item>
            <a-form-item label="超时自动通过"><a-switch v-model:checked="configForm.autoApprove" /></a-form-item>
          </template>
          <template v-else-if="configNode.type==='filter'">
            <a-form-item label="过滤规则"><a-textarea v-model:value="configForm.filterRule" :rows="2" placeholder="如：score > 0.7 && !is_sensitive" /></a-form-item>
            <a-form-item label="过滤方向"><a-radio-group v-model:value="configForm.filterPass"><a-radio :value="true">通过符合条件的 → 真出口</a-radio><a-radio :value="false">拦截符合条件的 → 假出口</a-radio></a-radio-group></a-form-item>
          </template>
          <!-- 输出分发类 -->
          <template v-else-if="configNode.type==='send'">
            <a-form-item label="发送渠道"><a-select v-model:value="configForm.channel" :options="[{label:'即时通讯',value:'im'},{label:'邮件',value:'email'},{label:'Webhook',value:'webhook'},{label:'API 响应',value:'api'}]" /></a-form-item>
            <a-form-item label="目标地址"><a-input v-model:value="configForm.targetAddr" placeholder="接收方 ID / URL" /></a-form-item>
          </template>
          <template v-else-if="configNode.type==='store'">
            <a-form-item label="存储类型"><a-select v-model:value="configForm.storeType" :options="[{label:'数据库',value:'db'},{label:'文件系统',value:'fs'},{label:'向量库',value:'vector'},{label:'缓存',value:'cache'}]" /></a-form-item>
            <a-form-item label="存储键/路径"><a-input v-model:value="configForm.storePath" placeholder="collection/table/file path" /></a-form-item>
          </template>
          <!-- 记忆类 -->
          <template v-else-if="configNode.type==='load-mem'">
            <a-form-item label="所属 Agent"><a-select v-model:value="configForm.memAgentId" placeholder="选择 Agent" :options="agentOpts" show-search allow-clear /></a-form-item>
            <a-form-item label="记忆范围"><a-radio-group v-model:value="configForm.memScope"><a-radio value="session">会话</a-radio><a-radio value="agent">Agent</a-radio><a-radio value="global">全局</a-radio></a-radio-group></a-form-item>
            <a-form-item label="检索数量"><a-input-number v-model:value="configForm.memTopK" :min="1" :max="50" style="width:100%" /></a-form-item>
          </template>
          <template v-else-if="configNode.type==='save-mem'">
            <a-form-item label="所属 Agent"><a-select v-model:value="configForm.memAgentId" placeholder="选择 Agent" :options="agentOpts" show-search allow-clear /></a-form-item>
            <a-form-item label="记忆类型"><a-select v-model:value="configForm.memType" :options="[{label:'对话',value:'dialog'},{label:'事实',value:'fact'},{label:'经验',value:'experience'},{label:'偏好',value:'preference'}]" /></a-form-item>
            <a-form-item label="重要性"><a-slider v-model:value="configForm.memImportance" :min="1" :max="10" /></a-form-item>
            <a-form-item label="过期时间"><a-input-number v-model:value="configForm.memTTL" :min="0" :max="365" placeholder="天，0=永久" style="width:100%" /></a-form-item>
          </template>
          <!-- 输入类 -->
          <template v-else-if="configNode.type==='input-text'">
            <a-form-item label="默认文本"><a-textarea v-model:value="configForm.inputDefault" :rows="2" placeholder="默认输入内容（可被上游覆盖）" /></a-form-item>
          </template>
          <template v-else-if="configNode.type==='input-image'">
            <a-form-item label="图片来源"><a-radio-group v-model:value="configForm.inputSrc"><a-radio value="upload">上传</a-radio><a-radio value="url">URL</a-radio><a-radio value="upstream">上游传递</a-radio></a-radio-group></a-form-item>
          </template>
          <template v-else-if="configNode.type==='input-audio'||configNode.type==='input-video'">
            <a-form-item label="媒体来源"><a-radio-group v-model:value="configForm.inputSrc"><a-radio value="upload">上传</a-radio><a-radio value="url">URL</a-radio><a-radio value="upstream">上游传递</a-radio></a-radio-group></a-form-item>
          </template>
          <!-- 任务类 -->
          <template v-else-if="configNode.type==='task'">
            <a-form-item label="任务描述"><a-textarea v-model:value="configForm.taskDesc" :rows="2" placeholder="描述任务的工作内容" /></a-form-item>
            <a-form-item label="指派成员"><a-select v-model:value="configForm.assignee" placeholder="自动分配" allow-clear :options="memberOpts" /></a-form-item>
            <a-form-item label="所需技能"><a-select v-model:value="configForm.skill" placeholder="自动匹配" allow-clear :options="skillOpts" show-search /></a-form-item>
            <a-form-item label="超时(秒)"><a-input-number v-model:value="configForm.timeout" :min="10" :max="3600" style="width:100%" /></a-form-item>
          </template>
          <!-- 逻辑控制类 -->
          <template v-else-if="configNode.type==='switch'">
            <a-form-item label="条件表达式"><a-textarea v-model:value="configForm.expression" :rows="2" placeholder="如: $input.score > 0.8 && $input.type === 'article'" /></a-form-item>
            <a-form-item label="逻辑组合">
              <a-radio-group v-model:value="configForm.gate">
                <a-radio-button value="and">AND</a-radio-button>
                <a-radio-button value="or">OR</a-radio-button>
                <a-radio-button value="nand">NAND</a-radio-button>
                <a-radio-button value="xor">XOR</a-radio-button>
              </a-radio-group>
            </a-form-item>
          </template>
          <template v-else-if="configNode.type==='loop'">
            <a-form-item label="循环方式"><a-radio-group v-model:value="configForm.loopType"><a-radio value="fixed">固定次数</a-radio><a-radio value="condition">条件循环</a-radio><a-radio value="each">遍历数组</a-radio></a-radio-group></a-form-item>
            <a-form-item label="次数 / 条件"><a-input-number v-if="configForm.loopType!=='each'" v-model:value="configForm.loopCount" :min="1" :max="1000" style="width:100%" /></a-form-item>
            <a-form-item label="循环变量" v-if="configForm.loopType==='each'"><a-input v-model:value="configForm.loopVar" placeholder="item" /></a-form-item>
          </template>
          <template v-else-if="configNode.type==='merge'">
            <a-form-item label="合并策略"><a-radio-group v-model:value="configForm.mergeMode"><a-radio value="waitAll">等候全部</a-radio><a-radio value="waitAny">任一到达即合并</a-radio></a-radio-group></a-form-item>
          </template>
          <!-- 触发器 -->
          <template v-else-if="configNode.type==='trigger-cron'">
            <a-form-item label="Cron 表达式"><a-input v-model:value="configForm.cron" placeholder="0 */6 * * *" /></a-form-item>
            <div style="font-size:.7rem;color:rgba(255,255,255,0.25)">秒 分 时 日 月 周</div>
          </template>
          <template v-else-if="configNode.type==='trigger-webhook'">
            <a-form-item label="鉴权方式"><a-radio-group v-model:value="configForm.webhookAuth"><a-radio value="none">无</a-radio><a-radio value="token">Token</a-radio><a-radio value="signature">签名</a-radio></a-radio-group></a-form-item>
          </template>
        </a-form>
        <div style="margin-top:16px;display:flex;gap:8px;justify-content:flex-end">
          <a-button size="small" danger @click="removeNode(configNode!.id);configOpen=false">删除节点</a-button>
          <a-button type="primary" size="small" @click="applyConfig">应用配置</a-button>
        </div>
      </template>
    </a-drawer>
    <!-- 使用帮助 -->
    <a-modal v-model:open="helpOpen" title="📖 使用指南" width="520px" :footer="null">
      <div style="color:#cbd5e1;font-size:.84rem;line-height:2">
        <p><b>+ 节点：</b>左侧拖拽到画布 | <b>删除：</b><kbd>Delete</kbd> 或右键 | <b>配置：</b>双击节点</p>
        <p><b>连线：</b>拖拽节点边缘 <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#60a5fa;vertical-align:middle;margin:0 3px"></span> 到另一个的对应圆点上</p>
        <p><b>缩放：</b><kbd>滚轮</kbd> · <kbd>Alt+/-</kbd> · <kbd>Alt+0</kbd> 适应画布</p>
        <a-divider style="margin:10px 0;border-color:rgba(255,255,255,0.05)" />
        <p style="font-size:.75rem;color:rgba(255,255,255,0.3)">✅ 自动检测死循环 · 重复连线 · 自连接</p>
      </div>
    </a-modal>
    <!-- AI 自动设计 -->
    <a-modal v-model:open="aiGenOpen" title="✨ AI 自动设计工作流" width="560px" :footer="null">
      <a-form layout="vertical">
        <a-form-item label="描述你的需求" extra="用自然语言描述你想要的工作流，AI 将自动生成节点和连线">
          <a-textarea v-model:value="aiGenDesc" :rows="5" placeholder="例如：从 Webhook 接收文章链接 → 用 AI 提取关键信息 → 翻译成英文 → 验证字数 > 100 → 通过后发送到 Slack，不通过返回重写"
            :disabled="aiGenLoading" />
        </a-form-item>
        <a-form-item label="可用技能（可选）">
          <a-select v-model:value="aiGenSkills" mode="tags" placeholder="输入技能名后回车" :options="skillOpts" :disabled="aiGenLoading" style="width:100%" />
        </a-form-item>
        <div style="display:flex;gap:8px;margin-top:4px">
          <a-button type="primary" @click="aiGenerate(false)" :loading="aiGenLoading" block>
            <template v-if="!aiGenLoading">🤖 生成预览</template>
            <template v-else>生成中...</template>
          </a-button>
          <a-button @click="aiGenerate(true)" :loading="aiGenSaving" :disabled="aiGenLoading" block>
            💾 生成并保存
          </a-button>
        </div>
        <div v-if="aiGenResult" style="margin-top:12px;padding:8px 12px;background:rgba(52,211,153,0.08);border-radius:8px;font-size:.78rem;color:#34d399">
          完成：{{ aiGenResult.node_count }} 个节点，{{ aiGenResult.edge_count }} 条连线
        </div>
        <div v-if="aiGenError" style="margin-top:12px;padding:8px 12px;background:rgba(239,68,68,0.08);border-radius:8px;font-size:.78rem;color:#ef4444">
          {{ aiGenError }}
        </div>
      </a-form>
    </a-modal>
  </div>
</template>
<script setup lang="ts">
import { ref, reactive, onMounted, nextTick, h, computed } from 'vue'
import { message } from 'ant-design-vue'
import { VueFlow, Handle, Position, type Node, type Edge, type Connection } from '@vue-flow/core'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import { workflowAPI } from '@/api/modules/workflows'
import {
  ApartmentOutlined, PlusOutlined, DeleteOutlined, SaveOutlined,
  MinusOutlined, ExpandOutlined, UndoOutlined, QuestionCircleOutlined,
} from '@ant-design/icons-vue'
// ─── AI 内容输出节点库 ───
const nodeCategories = reactive([
  { key:'source', icon:'📥', label:'输入源', open:true, items:[
    { type:'trigger-webhook', icon:'🪝', label:'Webhook', desc:'接收外部 HTTP 回调', color:'#22c55e' },
    { type:'trigger-cron', icon:'⏰', label:'定时触发', desc:'按 Cron 表达式定时执行', color:'#22c55e' },
    { type:'trigger-manual', icon:'👆', label:'手动触发', desc:'用户手动启动工作流', color:'#22c55e' },
    { type:'input-text', icon:'📝', label:'文本输入', desc:'用户输入文本内容', color:'#10b981' },
    { type:'input-image', icon:'🖼️', label:'图片输入', desc:'上传或引用图片', color:'#10b981' },
    { type:'input-audio', icon:'🎤', label:'音频输入', desc:'上传或录制音频', color:'#10b981' },
    { type:'input-video', icon:'🎬', label:'视频输入', desc:'上传或引用视频', color:'#10b981' },
  ]},
  { key:'ai', icon:'🧠', label:'AI 处理', open:true, items:[
    { type:'llm', icon:'🤖', label:'LLM 对话', desc:'调用大语言模型生成内容', color:'#a78bfa' },
    { type:'prompt', icon:'💬', label:'Prompt 构建', desc:'模板化组装提示词', color:'#a78bfa' },
    { type:'rag', icon:'🔍', label:'RAG 检索', desc:'从知识库检索增强上下文', color:'#a78bfa' },
    { type:'context', icon:'🧩', label:'上下文组装', desc:'组装多轮对话上下文', color:'#a78bfa' },
  ]},
  { key:'generate', icon:'✨', label:'内容生成', open:true, items:[
    { type:'gen-text', icon:'📝', label:'文本生成', desc:'生成文章/报告/文案', color:'#f59e0b' },
    { type:'gen-code', icon:'💻', label:'代码生成', desc:'根据需求生成代码', color:'#f59e0b' },
    { type:'gen-image', icon:'🎨', label:'图片生成', desc:'AI 图像创作', color:'#f59e0b' },
    { type:'gen-video', icon:'🎞️', label:'视频生成', desc:'AI 视频创作', color:'#f59e0b' },
  ]},
  { key:'postprocess', icon:'🔧', label:'后处理', open:false, items:[
    { type:'format', icon:'📐', label:'格式化', desc:'转换输出格式', color:'#06b6d4' },
    { type:'translate', icon:'🌍', label:'翻译', desc:'多语言翻译', color:'#06b6d4' },
    { type:'summarize', icon:'📋', label:'摘要', desc:'内容摘要提取', color:'#06b6d4' },
    { type:'extract', icon:'⛏', label:'信息提取', desc:'结构化提取关键信息', color:'#06b6d4' },
  ]},
  { key:'quality', icon:'✅', label:'质量控制', open:false, items:[
    { type:'validate', icon:'🛡', label:'验证检查', desc:'校验内容质量/格式', color:'#8b5cf6' },
    { type:'review', icon:'👤', label:'人工审核', desc:'Human-in-the-loop 审核', color:'#8b5cf6' },
    { type:'filter', icon:'🔎', label:'内容过滤', desc:'敏感词/质量过滤', color:'#8b5cf6' },
  ]},
  { key:'output', icon:'📤', label:'输出分发', open:true, items:[
    { type:'send', icon:'📨', label:'发送消息', desc:'推送到 IM/邮件/Webhook', color:'#f472b6' },
    { type:'store', icon:'💾', label:'存储', desc:'保存到数据库/向量库/文件', color:'#f472b6' },
    { type:'output', icon:'📤', label:'结果输出', desc:'工作流最终输出节点', color:'#f472b6' },
  ]},
  { key:'memory', icon:'💿', label:'记忆/上下文', open:false, items:[
    { type:'load-mem', icon:'📖', label:'加载记忆', desc:'从记忆系统检索上下文', color:'#ec4899' },
    { type:'save-mem', icon:'💾', label:'保存记忆', desc:'将结果写入长期记忆', color:'#ec4899' },
  ]},
  { key:'logic', icon:'🔀', label:'流程控制', open:false, items:[
    { type:'switch', icon:'⇆', label:'条件分支', desc:'if/else 多路分流', color:'#ef4444' },
    { type:'loop', icon:'🔄', label:'循环', desc:'重复执行子流程', color:'#ef4444' },
    { type:'merge', icon:'⊕', label:'合并', desc:'多路汇合为一路', color:'#ef4444' },
    { type:'task', icon:'📋', label:'人工任务', desc:'指派成员执行操作', color:'#ef4444' },
  ]},
])
// ─── 表单字段 & 通用类型 ───
interface NodeConfig {
  label:string; description?:string
  // LLM
  prompt?:string; userTemplate?:string; model?:string; temperature?:number; maxTokens?:number
  // RAG
  kbName?:string; retrievalMode?:string; topK?:number
  // Prompt构建
  template?:string
  // 上下文
  contextWindow?:number; contextStrategy?:string
  // 文本生成
  genStyle?:string; wordLimit?:number
  // 代码生成
  codeLang?:string; codeSpec?:string
  // 图像
  imgStyle?:string; imgRes?:string
  // 视频
  videoDuration?:number; videoRes?:string; videoFps?:number
  // 输入
  inputDefault?:string; inputSrc?:string
  // 格式化
  outFormat?:string
  // 翻译
  srcLang?:string; tgtLang?:string
  // 摘要
  summaryMode?:string; summaryWords?:number
  // 提取
  extractTarget?:string
  // 验证
  validateRule?:string; failAction?:string
  // 审核
  reviewer?:string; autoApprove?:boolean
  // 过滤
  filterRule?:string; filterPass?:boolean
  // 发送
  channel?:string; targetAddr?:string
  // 存储
  storeType?:string; storePath?:string
  // 记忆
  memScope?:string; memTopK?:number; memType?:string; memImportance?:number; memTTL?:number
  // 任务
  taskDesc?:string; assignee?:string; skill?:string; timeout?:number
  // 条件
  expression?:string; gate?:string
  // 循环
  loopType?:string; loopCount?:number; loopVar?:string
  // 合并
  mergeMode?:string
  // 触发器
  cron?:string; webhookAuth?:string
}
const vfRef = ref()
const nodes = ref<Node[]>([])
const edges = ref<Edge[]>([])
const zoom = ref(1)
const selectedNode = ref<string|null>(null)
const currentWfId = ref('')
let viewportTimer: ReturnType<typeof setTimeout> | null = null
const wfName = ref('')
const wfOptions = ref<{label:string;value:string}[]>([])
const configOpen = ref(false)
const configNode = ref<Node|null>(null)
const configForm = reactive<NodeConfig>({
  label:'', temperature:0.7, maxTokens:4096, contextWindow:10, contextStrategy:'recent',
  retrievalMode:'hybrid', topK:5, wordLimit:500, genStyle:'formal', codeLang:'python',
  imgStyle:'realistic', imgRes:'1024x1024', videoDuration:10, videoRes:'1080p', videoFps:30,
  outFormat:'text', summaryMode:'abstractive',
  summaryWords:200, failAction:'block', filterPass:true, channel:'api', storeType:'db',
  memScope:'session', memTopK:10, memType:'dialog', memImportance:5, memTTL:0,
  timeout:300, gate:'and', loopType:'fixed', loopCount:10, loopVar:'item',
  mergeMode:'waitAll', webhookAuth:'none',
  srcLang:'auto', tgtLang:'zh-CN', autoApprove:false,
  genProviderId:'', genModel:'', llmProviderId:'', memAgentId:'', inputDefault:'', inputSrc:'upstream',
})
const helpOpen = ref(false)
const memberOpts = [{label:'管理员',value:'admin'},{label:'开发者',value:'dev'},{label:'分析师',value:'analyst'}]
const skillOpts = [{label:'文本处理',value:'text'},{label:'代码生成',value:'code'},{label:'数据分析',value:'data'},{label:'图像识别',value:'vision'}]
const langOpts = [{label:'中文',value:'zh-CN'},{label:'英文',value:'en'},{label:'日文',value:'ja'},{label:'韩文',value:'ko'},{label:'法文',value:'fr'},{label:'德文',value:'de'},{label:'自动检测',value:'auto'}]
// LLM 服务商+模型列表（仅已联通且有正确能力的）
interface ProviderModel {
  name?: string
  model?: string
  capabilities?: string[]
  caps?: string[]
}
interface ProviderInfo {
  id: string
  name: string
  models?: (string | ProviderModel)[]
  model_capabilities?: Record<string, string[]>
}
const providerList = ref<ProviderInfo[]>([])
const agentOpts = ref<{label:string;value:string}[]>([])
const genTypes = ['gen-text','gen-code','gen-image','gen-video']
const providerOpts = computed(() => providerList.value.map((p)=>({label:p.name,value:p.id})))
const genCapMap:Record<string,string> = { 'gen-text':'text','gen-code':'text','gen-image':'image_generate','gen-video':'video_generate' }
function genCapLabel(type:string):string {
  const capLabels: Record<string,string> = {text:'文本',image_generate:'图片生成',video_generate:'视频生成'}
  return capLabels[genCapMap[type]]||''
}
function genModelOpts(type:string):{label:string;value:string;disabled?:boolean}[] {
  const cap = genCapMap[type]||'text'; const pid = configForm.genProviderId||''
  const p = providerList.value.find(x=>x.id===pid)
  if(!p?.models) return []
  return p.models.map((m)=>{
    const name = typeof m==='string'?m:(m.name||m.model||'')
    const caps = typeof m==='string'?(p.model_capabilities||{})[name]||[]:(m.capabilities||m.caps||[])
    return {label:name,value:name,disabled:cap!=='text'&&caps.length&&!caps.includes(cap)?true:false}
  })
}
const llmModelOpts = computed(() => {
  const p = providerList.value.find(x=>x.id===configForm.llmProviderId)
  if(!p?.models) return []
  return p.models.map((m)=>({label:typeof m==='string'?m:(m.name||m.model||''),value:typeof m==='string'?m:(m.name||m.model||'')}))
})
function onGenPChange(id:string, type:string) {
  configForm.genProviderId = id
  configForm.genModel = ''
  const cap = genCapMap[type]||'text'
  const p = providerList.value.find(x=>x.id===id)
  if(p?.models?.length) {
    const first = p.models.find((m)=>{
      const name = typeof m==='string'?m:(m.name||m.model||'')
      const caps = typeof m==='string'?(p.model_capabilities||{})[name]||[]:(m.capabilities||m.caps||[])
      return cap==='text'||caps.includes(cap)
    })
    if(first) configForm.genModel = typeof first==='string'?first:(first.name||first.model||'')
  }
}
// ─── 撤销 ───
interface HistoryState {
  nodes: typeof nodes.value
  edges: typeof edges.value
}
const history = ref<HistoryState[]>([])
const canUndo = ref(false)
function pushHistory() { history.value.push({nodes:JSON.parse(JSON.stringify(nodes.value)),edges:JSON.parse(JSON.stringify(edges.value))}); canUndo.value=true; if(history.value.length>50) history.value.shift() }
function undo() { if(!canUndo.value)return; const s=history.value.pop()!; nodes.value=s.nodes; edges.value=s.edges; canUndo.value=history.value.length>0 }
// ─── 拖放 ───
interface NodeType {
  type: string
  label: string
  color: string
  icon?: string
  desc?: string
}
let dragNodeType: NodeType | null = null
const idC = { v:0 }
function nid(){return'n_'+(idC.v++)}
function onDragStart(e:DragEvent,nt:NodeType){dragNodeType=nt;e.dataTransfer!.effectAllowed='move'}
function onDrop(e:DragEvent){
  if(!dragNodeType)return
  const b=(e.currentTarget as HTMLElement).getBoundingClientRect()
  pushHistory()
  addNode(dragNodeType.type,dragNodeType.label,dragNodeType.color,e.clientX-b.left-90,e.clientY-b.top-20)
  dragNodeType=null
}
function addNode(type:string,label:string,color:string,x:number,y:number):string{
  const id=nid()
  nodes.value.push({id,type,position:{x,y},data:{label,color,type},width:180,height:64})
  nodes.value=[...nodes.value];return id
}
function removeNode(id:string){
  pushHistory()
  nodes.value=nodes.value.filter(n=>n.id!==id)
  edges.value=edges.value.filter(e=>e.source!==id&&e.target!==id)
  nodes.value=[...nodes.value];edges.value=[...edges.value]
  if(selectedNode.value===id)selectedNode.value=null
}
// ─── 节点渲染（Handle 连线） ───
interface WorkflowNodeProps {
  id: string
  data: { label?: string; color?: string; type?: string; icon?: string }
  type?: string
  selected?: boolean
  configure?: () => void
}
const WorkflowNode = (props: WorkflowNodeProps)=>{
  const d=props.data||{},sel=props.selected
  const c=d.color||'#60a5fa'
  const isT=!!d.type?.startsWith('trigger'),isO=d.type==='output',isS=d.type==='switch',isM=d.type==='merge',isL=d.type==='loop',isF=d.type==='filter'
  const handleStyle = (bg:string) => ({background:bg,border:'2px solid '+bg,width:10,height:10})
  const children: ReturnType<typeof h>[]=[
    h('div',{class:'cn-header',style:`background:rgba(${c.slice(1).match(/.{2}/g)!.map(x=>parseInt(x,16)).join(',')},0.12)`,ondblclick:()=>props.configure?.()},[
      h('span',{class:'cn-icon'},d.icon||'◆'),
      h('span',{class:'cn-title'},d.label||props.typeName||''),
      h('span',{class:'cn-del',onClick:(e:MouseEvent)=>{e.stopPropagation();removeNode(props.id)}},'✕'),
    ]),
  ]
  // input handle
  if(!isT&&!isM) children.push(h(Handle,{key:'hi',type:'target',position:Position.Left,id:'in',style:handleStyle(c)}))
  // output handles
  if(isS){
    children.push(h(Handle,{key:'ht',type:'source',position:Position.Right,id:'true',style:handleStyle('#34d399')}))
    children.push(h(Handle,{key:'hf',type:'source',position:Position.Right,id:'false',style:handleStyle('#ef4444')}))
  }else if(isF){
    children.push(h(Handle,{key:'hp',type:'source',position:Position.Right,id:'pass',style:handleStyle('#34d399')}))
    children.push(h(Handle,{key:'hr',type:'source',position:Position.Right,id:'reject',style:handleStyle('#ef4444')}))
  }else if(isL){
    children.push(h(Handle,{key:'hb',type:'source',position:Position.Right,id:'body',style:handleStyle(c)}))
    children.push(h(Handle,{key:'hd',type:'source',position:Position.Right,id:'done',style:handleStyle('#34d399')}))
  }else if(isM){
    children.push(h(Handle,{key:'hi1',type:'target',position:Position.Left,id:'in1',style:handleStyle(c)}))
    children.push(h(Handle,{key:'hi2',type:'target',position:Position.Left,id:'in2',style:handleStyle(c)}))
    children.push(h(Handle,{key:'ho',type:'source',position:Position.Right,id:'out',style:handleStyle(c)}))
  }else if(!isO){
    children.push(h(Handle,{key:'ho',type:'source',position:Position.Right,id:'out',style:handleStyle(c)}))
  }
  return h('div',{
    class:'cn-node',style:`border-left:3px solid ${c};${sel?'box-shadow:0 6px 28px rgba(0,0,0,0.5),0 0 0 2px rgba(96,165,250,0.3)':''}`,
    onContextmenu:(e:MouseEvent)=>{e.preventDefault();removeNode(props.id)},
  },children)
}
const customNodeTypes:Record<string, typeof WorkflowNode> = { default: WorkflowNode }
// ─── 连线（验证） ───
function onConnect(cx:Connection){
  if(!cx.source||!cx.target)return
  if(cx.source===cx.target){message.error('不能连接自身');return}
  if(edges.value.some(e=>e.source===cx.source&&e.target===cx.target&&e.sourceHandle===cx.sourceHandle)){message.warning('已存在');return}
  if(hasCycle(cx.source,cx.target)){message.error('死循环，已阻止');return}
  pushHistory()
  edges.value.push({id:`e_${cx.source}_${cx.sourceHandle||'out'}_${cx.target}`,source:cx.source,target:cx.target,sourceHandle:cx.sourceHandle||'out',targetHandle:cx.targetHandle||'in',type:'smoothstep',animated:true,style:{stroke:'rgba(150,180,210,0.5)',strokeWidth:1.5}})
  edges.value=[...edges.value]
}
function hasCycle(from:string,to:string):boolean{
  const adj=new Map<string,string[]>()
  for(const e of edges.value){if(!adj.has(e.source))adj.set(e.source,[]);adj.get(e.source)!.push(e.target)}
  if(!adj.has(from))adj.set(from,[]);adj.get(from)!.push(to)
  const vis=new Set<string>();const stack=[to]
  while(stack.length){const cur=stack.pop()!;if(cur===from)return true;if(vis.has(cur))continue;vis.add(cur);for(const n of adj.get(cur)||[])if(!vis.has(n))stack.push(n)}
  return false
}
// ─── 交互 ───
function onNodeSelect({node}:{node:Node}){selectedNode.value=node.id}
function onNodeDblClick({node}:{node:Node}){openNodeConfig(node.id)}
function onViewportChange(vp:{zoom:number; x:number; y:number}){
  zoom.value=vp.zoom
  // 防抖保存视图状态到后端
  if(currentWfId.value){
    if(viewportTimer) clearTimeout(viewportTimer)
    viewportTimer = setTimeout(()=>{
      workflowAPI.updateViewport(currentWfId.value,{
        zoom: vp.zoom,
        offset_x: Math.round(vp.x),
        offset_y: Math.round(vp.y)
      }).catch(()=>{})
    },500)
  }
}
function zoomIn(){vfRef.value?.zoomIn?.()}
function zoomOut(){vfRef.value?.zoomOut?.()}
function fitView(){vfRef.value?.fitView?.({padding:0.2})}
function openNodeConfig(nodeId:string){
  const n=nodes.value.find(x=>x.id===nodeId);if(!n)return
  configNode.value=n
  const d=n.data||{}
  configForm.label=d.label||''
  ;['description','prompt','userTemplate','model','temperature','maxTokens','kbName','retrievalMode','topK','template','contextWindow','contextStrategy','genStyle','wordLimit','codeLang','codeSpec','imgStyle','imgRes','videoDuration','videoRes','videoFps','outFormat','srcLang','tgtLang','summaryMode','summaryWords','extractTarget','validateRule','failAction','reviewer','autoApprove','filterRule','filterPass','channel','targetAddr','storeType','storePath','memScope','memTopK','memType','memImportance','memTTL','memAgentId','taskDesc','assignee','skill','timeout','expression','gate','loopType','loopCount','loopVar','mergeMode','cron','webhookAuth','genProviderId','genModel','llmProviderId','inputDefault','inputSrc'].forEach(k=>{(configForm as Record<string, unknown>)[k]=(d as Record<string, unknown>)[k]??(configForm as Record<string, unknown>)[k]})
  configOpen.value=true
}
function applyConfig(){
  if(!configNode.value)return;const n=nodes.value.find(x=>x.id===configNode.value!.id);if(!n)return
  pushHistory();n.data={...n.data,...configForm};nodes.value=[...nodes.value];message.success('已应用')
}
// ─── CRUD ───
async function loadList(){try{const r=await workflowAPI.list();if(r?.success||r?.code===0){const wfs=r.data?.workflows||r.data||[];wfOptions.value=wfs.map((w:Record<string,unknown>)=>({label:(w.name as string)||String(w.id),value:String(w.id)}))}}catch{}}
async function restoreViewport(id:string){
  try{
    const r=await workflowAPI.getViewport(id)
    if(r?.success||r?.code===0){
      const vp=r.data
      if(vp&&vfRef.value){
        vfRef.value.setViewport({x:vp.offset_x||0,y:vp.offset_y||0,zoom:vp.zoom||1})
      }
    }
  }catch{}
}
async function loadWorkflow(id:string){if(!id){nodes.value=[];edges.value=[];return};try{const r=await workflowAPI.get(id);if(r?.success||r?.code===0){const d=r.data;wfName.value=d?.name||'';nodes.value=(d?.nodes||[]).map((n:Record<string,unknown>)=>({...n,data:(n as Node).data||{},width:180,height:64}));edges.value=(d?.edges||[]).map((e:Record<string,unknown>)=>({...e,type:'smoothstep',animated:true,style:{stroke:'rgba(150,180,210,0.5)',strokeWidth:1.5}}));idC.v=nodes.value.length;nextTick(()=>{fitView();restoreViewport(id)})}}catch{}}
async function createWf(){if(!wfName.value.trim()){message.warning('请输入名称');return};try{const r=await workflowAPI.create({name:wfName.value,nodes:[],edges:[]});if(r?.success||r?.code===0){message.success('已创建');currentWfId.value=r.data?.id||'';await loadList()}}catch(e:unknown){const err=e as {message?:string};message.error(err?.message||'失败')}}
async function saveWf(){if(!currentWfId.value){message.warning('请先新建或选择');return};try{await workflowAPI.update(currentWfId.value,{name:wfName.value,nodes:nodes.value.map(n=>({id:n.id,type:n.type,position:n.position,data:n.data})),edges:edges.value.map(e=>({id:e.id,source:e.source,target:e.target}))});message.success('已保存')}catch(e:unknown){const err=e as {message?:string};message.error(err?.message||'失败')}}
async function delWf(){if(!currentWfId.value)return;try{await workflowAPI.delete(currentWfId.value);message.success('已删除');currentWfId.value='';nodes.value=[];edges.value=[];await loadList()}catch(e:unknown){const err=e as {message?:string};message.error(err?.message||'失败')}}
// ─── AI 自动设计 ───
const aiGenOpen = ref(false)
const aiGenDesc = ref('')
const aiGenSkills = ref<string[]>([])
const aiGenLoading = ref(false)
const aiGenSaving = ref(false)
interface AIGenResult {
  nodes?: { type: string; label: string; color?: string; x?: number; y?: number }[]
  edges?: { source: string; target: string }[]
}
const aiGenResult = ref<AIGenResult | null>(null)
const aiGenError = ref('')
async function aiGenerate(save: boolean) {
  if(!aiGenDesc.value.trim()){message.warning('请描述你的工作流需求');return}
  aiGenLoading.value=true;aiGenError.value='';aiGenResult.value=null
  try{
    const r = save
      ? await workflowAPI.generateAndSave({
          description: aiGenDesc.value, name: wfName.value||undefined,
          available_skills: aiGenSkills.value.length?aiGenSkills.value:undefined,
        })
      : await workflowAPI.generate({
          description: aiGenDesc.value,
          available_skills: aiGenSkills.value.length?aiGenSkills.value:undefined,
        })
    if(r?.success||r?.code===0){
      const d = r.data||r
      let genNodes = d.nodes || d.steps || []
      let genEdges = d.edges || []
      // 适配后端可能返回不同结构的节点
      genNodes = genNodes.map((n,i)=>{
        if(!n.id) n.id = 'ai_'+i
        if(!n.type) n.type = n.node_type||'task'
        if(!n.position) n.position = n.position||n.pos||{x:300,y:100+i*120}
        if(!n.data) n.data = {label:(n.name||n.label||n.title||n.type),color:'#a78bfa',type:n.type}
        n.width=180;n.height=64
        return n
      })
      genEdges = genEdges.map((e,i)=>{
        if(!e.id) e.id = 'aie_'+i
        return {...e,type:'smoothstep',animated:true,style:{stroke:'rgba(150,180,210,0.5)',strokeWidth:1.5}}
      })
      // 应用到画布
      pushHistory()
      nodes.value = genNodes;idC.v=genNodes.length
      edges.value = genEdges
      nodes.value=[...nodes.value];edges.value=[...edges.value]
      aiGenResult.value = {node_count:genNodes.length,edge_count:genEdges.length}
      if(save){currentWfId.value=d.id||d.workflow_id||'';message.success('已生成并保存');aiGenOpen.value=false;await loadList()}
      else{message.success(`已生成 ${genNodes.length} 个节点`)}
      nextTick(()=>fitView())
    }else{aiGenError.value=r?.message||'生成失败'}
  }catch(e:unknown){const err=e as {response?:{data?:{message?:string}};message?:string};aiGenError.value=err?.response?.data?.message||err?.message||'AI 生成失败，请检查后端 LLM 配置'}
  finally{aiGenLoading.value=false;aiGenSaving.value=false}
}
onMounted(async ()=>{
  loadList()
  // 加载已联通服务商列表
  try{const {providerAPI}=await import('@/api/modules/providers');const pr=await providerAPI.list();if(pr?.success||pr?.code===0){providerList.value=(pr.data?.providers||[]).filter((p:Record<string,unknown>)=>(p.has_api_key as boolean)&&p.enabled!==false)}}catch{}
  // 加载 Agent 列表
  try{const {request}=await import('@/api');const r=await request.get('/agents');if(r?.code===0){agentOpts.value=(r.data?.agents||[]).map((a:Record<string,unknown>)=>({label:(a.name as string)||String(a.agent_id||a.id),value:String(a.agent_id||a.id)}))}}catch{}
})
const onKD=(e:KeyboardEvent)=>{
  if(e.altKey&&e.key==='='){e.preventDefault();zoomIn()}else if(e.altKey&&e.key==='-'){e.preventDefault();zoomOut()}else if(e.altKey&&e.key==='0'){e.preventDefault();fitView()}else if((e.ctrlKey||e.metaKey)&&e.key==='z'){e.preventDefault();undo()}
}
onMounted(()=>window.addEventListener('keydown',onKD))
</script>
<style scoped>
.wf-root{display:flex;flex-direction:column;height:calc(100vh - 88px);gap:8px;padding:0 0 8px}
.wf-toolbar{padding:10px 16px;border-radius:10px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.wf-title{font-size:1.1rem;color:#e2e8f0;margin:0;display:flex;align-items:center;gap:6px}
.wf-zoom-label{font-size:.78rem;color:rgba(255,255,255,0.4);font-family:monospace;min-width:40px;text-align:center}
.wf-body{display:flex;flex:1;gap:8px;overflow:hidden}
.wf-panel{width:170px;flex-shrink:0;padding:8px;border-radius:10px;display:flex;flex-direction:column;overflow-y:auto}
.panel-title{font-size:.8rem;color:rgba(255,255,255,0.5);font-weight:600;margin-bottom:6px;text-align:center}
.cat-group{margin-bottom:2px}
.cat-header{padding:5px 6px;border-radius:4px;cursor:pointer;font-size:.7rem;color:rgba(255,255,255,0.5);display:flex;align-items:center;gap:4px;transition:all .15s}
.cat-header:hover{background:rgba(255,255,255,0.04);color:rgba(255,255,255,0.7)}
.cat-arrow{font-size:.5rem;transition:transform .15s;color:rgba(255,255,255,0.25);width:10px}
.cat-arrow.open{transform:rotate(90deg)}
.cat-header-icon{font-size:.7rem;width:16px;text-align:center}
.cat-header-label{flex:1}
.cat-count{font-size:.6rem;color:rgba(255,255,255,0.2);font-family:monospace}
.node-list{display:flex;flex-direction:column;gap:1px;padding-left:4px}
.node-item{display:flex;align-items:center;gap:5px;padding:5px 6px;border-radius:5px;background:rgba(255,255,255,0.02);cursor:grab;transition:all .12s;border:1px solid transparent;font-size:.7rem}
.node-item:hover{background:rgba(255,255,255,0.06);border-color:rgba(255,255,255,0.06)}
.node-item:active{cursor:grabbing}
.ni-dot{width:6px;height:6px;border-radius:50%;flex-shrink:0;opacity:.8}
.ni-icon{font-size:.75rem;width:16px;text-align:center;flex-shrink:0}
.ni-label{color:rgba(255,255,255,0.55);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.wf-canvas-wrap{flex:1;position:relative;border-radius:10px;overflow:hidden;background:rgba(10,15,30,0.55)}
.vf-canvas{width:100%;height:100%}
.canvas-hint{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);text-align:center;color:rgba(255,255,255,0.22);font-size:.8rem;pointer-events:none;line-height:1.8}
.hint-icon{font-size:1.8rem;margin-bottom:6px;opacity:.4}
:deep(.cn-node){background:rgba(20,28,48,0.92);backdrop-filter:blur(12px);border:1px solid rgba(255,255,255,0.08);border-radius:8px;font-size:.73rem;color:#cbd5e1;position:relative;min-width:140px;box-shadow:0 2px 12px rgba(0,0,0,0.25);transition:all .2s;cursor:move}
:deep(.cn-node:hover){box-shadow:0 4px 20px rgba(0,0,0,0.4)}
:deep(.cn-header){padding:6px 10px;border-radius:8px 8px 0 0;display:flex;align-items:center;gap:5px;cursor:pointer}
:deep(.cn-icon){font-size:.8rem;flex-shrink:0}
:deep(.cn-title){font-weight:600;font-size:.73rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
:deep(.cn-del){margin-left:auto;width:16px;height:16px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:.55rem;color:rgba(255,255,255,0.15);cursor:pointer;transition:all .15s;flex-shrink:0}
:deep(.cn-del:hover){background:rgba(239,68,68,0.2);color:#ef4444}
:deep(.vue-flow__edge-path){stroke:rgba(150,180,210,0.5)!important}
:deep(.vue-flow__connection-line){stroke:rgba(96,165,250,0.5)!important;stroke-width:2px}
:deep(.vue-flow__background){background:rgba(10,15,30,0.55)!important}
:deep(.vue-flow__controls){display:none}
</style>
 
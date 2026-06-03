&lt;template&gt;
  &lt;div &gt;
    &lt;!-- 顶部工具栏 --&gt;
    &lt;div &gt;
      &lt;h2 &gt;&lt;ApartmentOutlined /&gt; 工作流设计&lt;/h2&gt;
      &lt;a-space&gt;
        &lt;a-select v-model:value="currentWfId" style="width:180px" :options="wfOptions" @change="loadWorkflow" placeholder="选择工作流" /&gt;
        &lt;a-input v-model:value="wfName" placeholder="新工作流名称" style="width:150px" size="small" /&gt;
        &lt;a-button size="small" type="primary" @click="createWf"&gt;&lt;PlusOutlined /&gt;&lt;/a-button&gt;
        &lt;a-button size="small" @click="saveWf"&gt;&lt;SaveOutlined /&gt;&lt;/a-button&gt;
        &lt;a-popconfirm title="删除?" @confirm="delWf"&gt;&lt;a-button size="small" danger&gt;&lt;DeleteOutlined /&gt;&lt;/a-button&gt;&lt;/a-popconfirm&gt;
        &lt;a-divider type="vertical" /&gt;
        &lt;a-button size="small" type="primary" ghost @click="aiGenOpen=true" style="background:linear-gradient(135deg,rgba(139,92,246,0.2),rgba(59,130,246,0.15));border-color:rgba(139,92,246,0.3)"&gt;
          ✨ AI 设计
        &lt;/a-button&gt;
        &lt;a-divider type="vertical" /&gt;
        &lt;a-button size="small" ghost @click="undo" :disabled="!canUndo"&gt;&lt;UndoOutlined /&gt;&lt;/a-button&gt;
        &lt;a-badge :count="nodes.length" :number-style="{background:'#60a5fa'}" title="节点数" /&gt;
        &lt;a-badge :count="edges.length" :number-style="{background:'#a78bfa'}" title="连线数" /&gt;
      &lt;/a-space&gt;
      &lt;a-space style="margin-left:auto"&gt;
        &lt;a-button size="small" type="text" @click="helpOpen=true"&gt;&lt;QuestionCircleOutlined /&gt;&lt;/a-button&gt;
        &lt;span &gt;{{ Math.round(zoom * 100) }}%&lt;/span&gt;
        &lt;a-button size="small" shape="circle" @click="zoomOut"&gt;&lt;MinusOutlined /&gt;&lt;/a-button&gt;
        &lt;a-button size="small" shape="circle" @click="zoomIn"&gt;&lt;PlusOutlined /&gt;&lt;/a-button&gt;
        &lt;a-button size="small" @click="fitView"&gt;&lt;ExpandOutlined /&gt;&lt;/a-button&gt;
      &lt;/a-space&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;!-- 左侧节点面板（AI 内容输出分类） --&gt;
      &lt;div &gt;
        &lt;div &gt;🧩 节点库&lt;/div&gt;
        &lt;div v-for="cat in nodeCategories" :key="cat.key" &gt;
          &lt;div  @click="cat.open=!cat.open"&gt;
            &lt;span  :&gt;▶&lt;/span&gt;
            &lt;span &gt;{{ cat.icon }}&lt;/span&gt;
            &lt;span &gt;{{ cat.label }}&lt;/span&gt;
            &lt;span &gt;{{ cat.items.length }}&lt;/span&gt;
          &lt;/div&gt;
          &lt;div v-show="cat.open" &gt;
            &lt;div v-for="nt in cat.items" :key="nt.type"  :title="nt.desc" draggable="true" @dragstart="onDragStart($event, nt)"&gt;
              &lt;span  :style="{background:nt.color}"&gt;&lt;/span&gt;
              &lt;span &gt;{{ nt.icon }}&lt;/span&gt;
              &lt;span &gt;{{ nt.label }}&lt;/span&gt;
            &lt;/div&gt;
          &lt;/div&gt;
        &lt;/div&gt;
        &lt;div style="margin-top:auto;padding-top:8px"&gt;
          &lt;a-button size="small" type="dashed" block @click="helpOpen=true" style="font-size:.72rem;color:rgba(255,255,255,0.35)"&gt;📖 使用帮助&lt;/a-button&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;!-- 画布 --&gt;
      &lt;div  @drop="onDrop" @dragover.prevent&gt;
        &lt;VueFlow
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
        &gt;
          &lt;template #node-default="props"&gt;
            &lt;WorkflowNode :id="props.id" :data="props.data" :type-name="props.type" :selected="selectedNode===props.id"
              @delete="removeNode(props.id)" @configure="openNodeConfig(props.id)" /&gt;
          &lt;/template&gt;
        &lt;/VueFlow&gt;
        &lt;!-- 画布提示 --&gt;
        &lt;div  v-if="!nodes.length"&gt;
          &lt;div &gt;🖱️&lt;/div&gt;
          &lt;div&gt;从左侧&lt;span style="color:#60a5fa"&gt;拖拽节点&lt;/span&gt;到画布&lt;br&gt;拖拽节点圆点&lt;span style="color:#a78bfa"&gt;连线&lt;/span&gt; · 滚轮缩放 · Alt+/-缩放&lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;!-- 节点配置抽屉 --&gt;
    &lt;a-drawer v-model:open="configOpen" :title="'⚙ '+ (configNode?.data?.label || '节点配置')" width="400px" placement="right"&gt;
      &lt;template v-if="configNode"&gt;
        &lt;a-form layout="vertical" size="small"&gt;
          &lt;a-form-item label="节点名称"&gt;&lt;a-input v-model:value="configForm.label" /&gt;&lt;/a-form-item&gt;
          &lt;a-form-item label="节点描述"&gt;&lt;a-input v-model:value="configForm.description" placeholder="简要说明该节点的作用" /&gt;&lt;/a-form-item&gt;
          &lt;!-- AI 处理类 --&gt;
          &lt;template v-if="configNode.type==='llm'"&gt;
            &lt;a-form-item label="选择 LLM（已联通的服务商）"&gt;
              &lt;a-row :gutter="8"&gt;
                &lt;a-col :span="12"&gt;&lt;a-select v-model:value="configForm.llmProviderId" placeholder="服务商" :options="providerOpts" size="small" style="width:100%" @change="(v:string)=&gt;{configForm.llmProviderId=v;configForm.model=''}" /&gt;&lt;/a-col&gt;
                &lt;a-col :span="12"&gt;&lt;a-select v-model:value="configForm.model" placeholder="模型" :options="llmModelOpts" size="small" style="width:100%" show-search /&gt;&lt;/a-col&gt;
              &lt;/a-row&gt;
              &lt;div v-if="!providerOpts.length" style="font-size:.7rem;color:#ef4444;margin-top:4px"&gt;⚠ 暂无已联通的服务商&lt;/div&gt;
            &lt;/a-form-item&gt;
            &lt;a-divider style="margin:8px 0;border-color:rgba(255,255,255,0.05)" /&gt;
            &lt;a-form-item label="System Prompt"&gt;&lt;a-textarea v-model:value="configForm.prompt" :rows="3" placeholder="定义 AI 的角色和行为..." /&gt;&lt;/a-form-item&gt;
            &lt;a-form-item label="用户输入模板"&gt;&lt;a-textarea v-model:value="configForm.userTemplate" :rows="2" placeholder="使用 {{$input}} 引用上游输出" /&gt;&lt;/a-form-item&gt;
            &lt;a-form-item label="Temperature"&gt;&lt;a-slider v-model:value="configForm.temperature" :min="0" :max="2" :step="0.1" /&gt;&lt;/a-form-item&gt;
            &lt;a-form-item label="Max Tokens"&gt;&lt;a-input-number v-model:value="configForm.maxTokens" :min="256" :max="131072" :step="256" style="width:100%" /&gt;&lt;/a-form-item&gt;
          &lt;/template&gt;
          &lt;template v-else-if="configNode.type==='rag'"&gt;
            &lt;a-form-item label="知识库"&gt;&lt;a-input v-model:value="configForm.kbName" placeholder="选择知识库" /&gt;&lt;/a-form-item&gt;
            &lt;a-form-item label="检索方式"&gt;&lt;a-radio-group v-model:value="configForm.retrievalMode"&gt;&lt;a-radio value="semantic"&gt;语义搜索&lt;/a-radio&gt;&lt;a-radio value="keyword"&gt;关键词&lt;/a-radio&gt;&lt;a-radio value="hybrid"&gt;混合&lt;/a-radio&gt;&lt;/a-radio-group&gt;&lt;/a-form-item&gt;
            &lt;a-form-item label="Top K"&gt;&lt;a-input-number v-model:value="configForm.topK" :min="1" :max="20" style="width:100%" /&gt;&lt;/a-form-item&gt;
          &lt;/template&gt;
          &lt;template v-else-if="configNode.type==='prompt'"&gt;
            &lt;a-form-item label="Prompt 模板"&gt;&lt;a-textarea v-model:value="configForm.template" :rows="4" placeholder="可使用 {{$input}} {{$memory}} {{$context}} 等变量" /&gt;&lt;/a-form-item&gt;
          &lt;/template&gt;
          &lt;template v-else-if="configNode.type==='context'"&gt;
            &lt;a-form-item label="上下文窗口大小"&gt;&lt;a-input-number v-model:value="configForm.contextWindow" :min="1" :max="100" style="width:100%" /&gt;&lt;/a-form-item&gt;
            &lt;a-form-item label="组装策略"&gt;&lt;a-radio-group v-model:value="configForm.contextStrategy"&gt;&lt;a-radio value="recent"&gt;最近N轮&lt;/a-radio&gt;&lt;a-radio value="summary"&gt;摘要压缩&lt;/a-radio&gt;&lt;a-radio value="relevance"&gt;相关性筛选&lt;/a-radio&gt;&lt;/a-radio-group&gt;&lt;/a-form-item&gt;
          &lt;/template&gt;
          &lt;!-- 内容生成类 --&gt;
          &lt;!-- LLM 选择器（仅联通且有能力的服务商） --&gt;
          &lt;template v-if="genTypes.includes(configNode.type)"&gt;
            &lt;a-form-item :label="'选择 LLM（已联通且有'+genCapLabel(configNode.type)+'能力）'"&gt;
              &lt;a-row :gutter="8"&gt;
                &lt;a-col :span="12"&gt;&lt;a-select v-model:value="configForm.genProviderId" placeholder="服务商" :options="providerOpts" size="small" style="width:100%" @change="(v:string)=&gt;onGenPChange(v,configNode.type)" /&gt;&lt;/a-col&gt;
                &lt;a-col :span="12"&gt;&lt;a-select v-model:value="configForm.genModel" placeholder="模型" :options="genModelOpts(configNode.type)" size="small" style="width:100%" show-search /&gt;&lt;/a-col&gt;
              &lt;/a-row&gt;
              &lt;div v-if="!genModelOpts(configNode.type).length" style="font-size:.7rem;color:#ef4444;margin-top:4px"&gt;⚠ 暂无具备所需能力的服务商，请先在「模型管理」配置并确保联通&lt;/div&gt;
            &lt;/a-form-item&gt;
            &lt;a-divider style="margin:8px 0;border-color:rgba(255,255,255,0.05)" /&gt;
          &lt;/template&gt;
          &lt;template v-if="configNode.type==='gen-text'"&gt;
            &lt;a-form-item label="生成风格"&gt;&lt;a-select v-model:value="configForm.genStyle" :options="[{label:'正式',value:'formal'},{label:'创意',value:'creative'},{label:'简洁',value:'concise'},{label:'技术',value:'technical'}]" /&gt;&lt;/a-form-item&gt;
            &lt;a-form-item label="字数限制"&gt;&lt;a-input-number v-model:value="configForm.wordLimit" :min="50" :max="10000" :step="100" style="width:100%" /&gt;&lt;/a-form-item&gt;
          &lt;/template&gt;
          &lt;template v-if="configNode.type==='gen-code'"&gt;
            &lt;a-form-item label="编程语言"&gt;&lt;a-select v-model:value="configForm.codeLang" :options="[{label:'Python',value:'python'},{label:'JavaScript',value:'js'},{label:'TypeScript',value:'ts'},{label:'Go',value:'go'},{label:'Rust',value:'rust'}]" /&gt;&lt;/a-form-item&gt;
            &lt;a-form-item label="需求规格"&gt;&lt;a-textarea v-model:value="configForm.codeSpec" :rows="4" placeholder="描述代码需要实现的功能、接口、异常处理等" /&gt;&lt;/a-form-item&gt;
          &lt;/template&gt;
          &lt;template v-if="configNode.type==='gen-image'"&gt;
            &lt;a-form-item label="画风"&gt;&lt;a-select v-model:value="configForm.imgStyle" :options="[{label:'写实',value:'realistic'},{label:'插画',value:'illustration'},{label:'二次元',value:'anime'},{label:'3D渲染',value:'3d'},{label:'极简',value:'minimal'}]" /&gt;&lt;/a-form-item&gt;
            &lt;a-form-item label="分辨率"&gt;&lt;a-select v-model:value="configForm.imgRes" :options="[{label:'1024×1024',value:'1024x1024'},{label:'1792×1024',value:'1792x1024'},{label:'1024×1792',value:'1024x1792'}]" /&gt;&lt;/a-form-item&gt;
          &lt;/template&gt;
          &lt;template v-if="configNode.type==='gen-video'"&gt;
            &lt;a-form-item label="时长（秒）"&gt;&lt;a-input-number v-model:value="configForm.videoDuration" :min="3" :max="120" :step="1" style="width:100%" /&gt;&lt;/a-form-item&gt;
            &lt;a-form-item label="分辨率"&gt;&lt;a-select v-model:value="configForm.videoRes" :options="[{label:'720p',value:'720p'},{label:'1080p',value:'1080p'}]" /&gt;&lt;/a-form-item&gt;
            &lt;a-form-item label="帧率"&gt;&lt;a-input-number v-model:value="configForm.videoFps" :min="15" :max="60" :step="5" style="width:100%" /&gt;&lt;/a-form-item&gt;
          &lt;/template&gt;
          &lt;!-- 后处理类 --&gt;
          &lt;template v-else-if="configNode.type==='format'"&gt;
            &lt;a-form-item label="输出格式"&gt;&lt;a-select v-model:value="configForm.outFormat" :options="[{label:'纯文本',value:'text'},{label:'Markdown',value:'md'},{label:'JSON',value:'json'},{label:'HTML',value:'html'},{label:'Table',value:'table'}]" /&gt;&lt;/a-form-item&gt;
          &lt;/template&gt;
          &lt;template v-else-if="configNode.type==='translate'"&gt;
            &lt;a-form-item label="源语言"&gt;&lt;a-select v-model:value="configForm.srcLang" :options="langOpts" show-search /&gt;&lt;/a-form-item&gt;
            &lt;a-form-item label="目标语言"&gt;&lt;a-select v-model:value="configForm.tgtLang" :options="langOpts" show-search /&gt;&lt;/a-form-item&gt;
          &lt;/template&gt;
          &lt;template v-else-if="configNode.type==='summarize'"&gt;
            &lt;a-form-item label="摘要方式"&gt;&lt;a-radio-group v-model:value="configForm.summaryMode"&gt;&lt;a-radio value="extractive"&gt;抽取式&lt;/a-radio&gt;&lt;a-radio value="abstractive"&gt;生成式&lt;/a-radio&gt;&lt;a-radio value="bullets"&gt;要点列表&lt;/a-radio&gt;&lt;/a-radio-group&gt;&lt;/a-form-item&gt;
            &lt;a-form-item label="目标字数"&gt;&lt;a-input-number v-model:value="configForm.summaryWords" :min="50" :max="5000" :step="50" style="width:100%" /&gt;&lt;/a-form-item&gt;
          &lt;/template&gt;
          &lt;template v-else-if="configNode.type==='extract'"&gt;
            &lt;a-form-item label="提取目标"&gt;&lt;a-textarea v-model:value="configForm.extractTarget" :rows="2" placeholder="描述要提取的内容：如「人名、日期、金额」" /&gt;&lt;/a-form-item&gt;
          &lt;/template&gt;
          &lt;!-- 质量控制类 --&gt;
          &lt;template v-else-if="configNode.type==='validate'"&gt;
            &lt;a-form-item label="验证规则"&gt;&lt;a-textarea v-model:value="configForm.validateRule" :rows="2" placeholder="如：字数 &gt; 100、包含关键词、JSON 格式正确" /&gt;&lt;/a-form-item&gt;
            &lt;a-form-item label="失败处理"&gt;&lt;a-select v-model:value="configForm.failAction" :options="[{label:'阻断并报错',value:'block'},{label:'标记后继续',value:'warn'},{label:'自动修复',value:'fix'}]" /&gt;&lt;/a-form-item&gt;
          &lt;/template&gt;
          &lt;template v-else-if="configNode.type==='review'"&gt;
            &lt;a-form-item label="审核人"&gt;&lt;a-select v-model:value="configForm.reviewer" placeholder="选择审核人" :options="memberOpts" /&gt;&lt;/a-form-item&gt;
            &lt;a-form-item label="超时自动通过"&gt;&lt;a-switch v-model:checked="configForm.autoApprove" /&gt;&lt;/a-form-item&gt;
          &lt;/template&gt;
          &lt;template v-else-if="configNode.type==='filter'"&gt;
            &lt;a-form-item label="过滤规则"&gt;&lt;a-textarea v-model:value="configForm.filterRule" :rows="2" placeholder="如：score &gt; 0.7 &amp;&amp; !is_sensitive" /&gt;&lt;/a-form-item&gt;
            &lt;a-form-item label="过滤方向"&gt;&lt;a-radio-group v-model:value="configForm.filterPass"&gt;&lt;a-radio :value="true"&gt;通过符合条件的 → 真出口&lt;/a-radio&gt;&lt;a-radio :value="false"&gt;拦截符合条件的 → 假出口&lt;/a-radio&gt;&lt;/a-radio-group&gt;&lt;/a-form-item&gt;
          &lt;/template&gt;
          &lt;!-- 输出分发类 --&gt;
          &lt;template v-else-if="configNode.type==='send'"&gt;
            &lt;a-form-item label="发送渠道"&gt;&lt;a-select v-model:value="configForm.channel" :options="[{label:'即时通讯',value:'im'},{label:'邮件',value:'email'},{label:'Webhook',value:'webhook'},{label:'API 响应',value:'api'}]" /&gt;&lt;/a-form-item&gt;
            &lt;a-form-item label="目标地址"&gt;&lt;a-input v-model:value="configForm.targetAddr" placeholder="接收方 ID / URL" /&gt;&lt;/a-form-item&gt;
          &lt;/template&gt;
          &lt;template v-else-if="configNode.type==='store'"&gt;
            &lt;a-form-item label="存储类型"&gt;&lt;a-select v-model:value="configForm.storeType" :options="[{label:'数据库',value:'db'},{label:'文件系统',value:'fs'},{label:'向量库',value:'vector'},{label:'缓存',value:'cache'}]" /&gt;&lt;/a-form-item&gt;
            &lt;a-form-item label="存储键/路径"&gt;&lt;a-input v-model:value="configForm.storePath" placeholder="collection/table/file path" /&gt;&lt;/a-form-item&gt;
          &lt;/template&gt;
          &lt;!-- 记忆类 --&gt;
          &lt;template v-else-if="configNode.type==='load-mem'"&gt;
            &lt;a-form-item label="所属 Agent"&gt;&lt;a-select v-model:value="configForm.memAgentId" placeholder="选择 Agent" :options="agentOpts" show-search allow-clear /&gt;&lt;/a-form-item&gt;
            &lt;a-form-item label="记忆范围"&gt;&lt;a-radio-group v-model:value="configForm.memScope"&gt;&lt;a-radio value="session"&gt;会话&lt;/a-radio&gt;&lt;a-radio value="agent"&gt;Agent&lt;/a-radio&gt;&lt;a-radio value="global"&gt;全局&lt;/a-radio&gt;&lt;/a-radio-group&gt;&lt;/a-form-item&gt;
            &lt;a-form-item label="检索数量"&gt;&lt;a-input-number v-model:value="configForm.memTopK" :min="1" :max="50" style="width:100%" /&gt;&lt;/a-form-item&gt;
          &lt;/template&gt;
          &lt;template v-else-if="configNode.type==='save-mem'"&gt;
            &lt;a-form-item label="所属 Agent"&gt;&lt;a-select v-model:value="configForm.memAgentId" placeholder="选择 Agent" :options="agentOpts" show-search allow-clear /&gt;&lt;/a-form-item&gt;
            &lt;a-form-item label="记忆类型"&gt;&lt;a-select v-model:value="configForm.memType" :options="[{label:'对话',value:'dialog'},{label:'事实',value:'fact'},{label:'经验',value:'experience'},{label:'偏好',value:'preference'}]" /&gt;&lt;/a-form-item&gt;
            &lt;a-form-item label="重要性"&gt;&lt;a-slider v-model:value="configForm.memImportance" :min="1" :max="10" /&gt;&lt;/a-form-item&gt;
            &lt;a-form-item label="过期时间"&gt;&lt;a-input-number v-model:value="configForm.memTTL" :min="0" :max="365" placeholder="天，0=永久" style="width:100%" /&gt;&lt;/a-form-item&gt;
          &lt;/template&gt;
          &lt;!-- 输入类 --&gt;
          &lt;template v-else-if="configNode.type==='input-text'"&gt;
            &lt;a-form-item label="默认文本"&gt;&lt;a-textarea v-model:value="configForm.inputDefault" :rows="2" placeholder="默认输入内容（可被上游覆盖）" /&gt;&lt;/a-form-item&gt;
          &lt;/template&gt;
          &lt;template v-else-if="configNode.type==='input-image'"&gt;
            &lt;a-form-item label="图片来源"&gt;&lt;a-radio-group v-model:value="configForm.inputSrc"&gt;&lt;a-radio value="upload"&gt;上传&lt;/a-radio&gt;&lt;a-radio value="url"&gt;URL&lt;/a-radio&gt;&lt;a-radio value="upstream"&gt;上游传递&lt;/a-radio&gt;&lt;/a-radio-group&gt;&lt;/a-form-item&gt;
          &lt;/template&gt;
          &lt;template v-else-if="configNode.type==='input-audio'||configNode.type==='input-video'"&gt;
            &lt;a-form-item label="媒体来源"&gt;&lt;a-radio-group v-model:value="configForm.inputSrc"&gt;&lt;a-radio value="upload"&gt;上传&lt;/a-radio&gt;&lt;a-radio value="url"&gt;URL&lt;/a-radio&gt;&lt;a-radio value="upstream"&gt;上游传递&lt;/a-radio&gt;&lt;/a-radio-group&gt;&lt;/a-form-item&gt;
          &lt;/template&gt;
          &lt;!-- 任务类 --&gt;
          &lt;template v-else-if="configNode.type==='task'"&gt;
            &lt;a-form-item label="任务描述"&gt;&lt;a-textarea v-model:value="configForm.taskDesc" :rows="2" placeholder="描述任务的工作内容" /&gt;&lt;/a-form-item&gt;
            &lt;a-form-item label="指派成员"&gt;&lt;a-select v-model:value="configForm.assignee" placeholder="自动分配" allow-clear :options="memberOpts" /&gt;&lt;/a-form-item&gt;
            &lt;a-form-item label="所需技能"&gt;&lt;a-select v-model:value="configForm.skill" placeholder="自动匹配" allow-clear :options="skillOpts" show-search /&gt;&lt;/a-form-item&gt;
            &lt;a-form-item label="超时(秒)"&gt;&lt;a-input-number v-model:value="configForm.timeout" :min="10" :max="3600" style="width:100%" /&gt;&lt;/a-form-item&gt;
          &lt;/template&gt;
          &lt;!-- 逻辑控制类 --&gt;
          &lt;template v-else-if="configNode.type==='switch'"&gt;
            &lt;a-form-item label="条件表达式"&gt;&lt;a-textarea v-model:value="configForm.expression" :rows="2" placeholder="如: $input.score &gt; 0.8 &amp;&amp; $input.type === 'article'" /&gt;&lt;/a-form-item&gt;
            &lt;a-form-item label="逻辑组合"&gt;
              &lt;a-radio-group v-model:value="configForm.gate"&gt;
                &lt;a-radio-button value="and"&gt;AND&lt;/a-radio-button&gt;
                &lt;a-radio-button value="or"&gt;OR&lt;/a-radio-button&gt;
                &lt;a-radio-button value="nand"&gt;NAND&lt;/a-radio-button&gt;
                &lt;a-radio-button value="xor"&gt;XOR&lt;/a-radio-button&gt;
              &lt;/a-radio-group&gt;
            &lt;/a-form-item&gt;
          &lt;/template&gt;
          &lt;template v-else-if="configNode.type==='loop'"&gt;
            &lt;a-form-item label="循环方式"&gt;&lt;a-radio-group v-model:value="configForm.loopType"&gt;&lt;a-radio value="fixed"&gt;固定次数&lt;/a-radio&gt;&lt;a-radio value="condition"&gt;条件循环&lt;/a-radio&gt;&lt;a-radio value="each"&gt;遍历数组&lt;/a-radio&gt;&lt;/a-radio-group&gt;&lt;/a-form-item&gt;
            &lt;a-form-item label="次数 / 条件"&gt;&lt;a-input-number v-if="configForm.loopType!=='each'" v-model:value="configForm.loopCount" :min="1" :max="1000" style="width:100%" /&gt;&lt;/a-form-item&gt;
            &lt;a-form-item label="循环变量" v-if="configForm.loopType==='each'"&gt;&lt;a-input v-model:value="configForm.loopVar" placeholder="item" /&gt;&lt;/a-form-item&gt;
          &lt;/template&gt;
          &lt;template v-else-if="configNode.type==='merge'"&gt;
            &lt;a-form-item label="合并策略"&gt;&lt;a-radio-group v-model:value="configForm.mergeMode"&gt;&lt;a-radio value="waitAll"&gt;等候全部&lt;/a-radio&gt;&lt;a-radio value="waitAny"&gt;任一到达即合并&lt;/a-radio&gt;&lt;/a-radio-group&gt;&lt;/a-form-item&gt;
          &lt;/template&gt;
          &lt;!-- 触发器 --&gt;
          &lt;template v-else-if="configNode.type==='trigger-cron'"&gt;
            &lt;a-form-item label="Cron 表达式"&gt;&lt;a-input v-model:value="configForm.cron" placeholder="0 */6 * * *" /&gt;&lt;/a-form-item&gt;
            &lt;div style="font-size:.7rem;color:rgba(255,255,255,0.25)"&gt;秒 分 时 日 月 周&lt;/div&gt;
          &lt;/template&gt;
          &lt;template v-else-if="configNode.type==='trigger-webhook'"&gt;
            &lt;a-form-item label="鉴权方式"&gt;&lt;a-radio-group v-model:value="configForm.webhookAuth"&gt;&lt;a-radio value="none"&gt;无&lt;/a-radio&gt;&lt;a-radio value="token"&gt;Token&lt;/a-radio&gt;&lt;a-radio value="signature"&gt;签名&lt;/a-radio&gt;&lt;/a-radio-group&gt;&lt;/a-form-item&gt;
          &lt;/template&gt;
        &lt;/a-form&gt;
        &lt;div style="margin-top:16px;display:flex;gap:8px;justify-content:flex-end"&gt;
          &lt;a-button size="small" danger @click="removeNode(configNode!.id);configOpen=false"&gt;删除节点&lt;/a-button&gt;
          &lt;a-button type="primary" size="small" @click="applyConfig"&gt;应用配置&lt;/a-button&gt;
        &lt;/div&gt;
      &lt;/template&gt;
    &lt;/a-drawer&gt;
    &lt;!-- 使用帮助 --&gt;
    &lt;a-modal v-model:open="helpOpen" title="📖 使用指南" width="520px" :footer="null"&gt;
      &lt;div style="color:#cbd5e1;font-size:.84rem;line-height:2"&gt;
        &lt;p&gt;&lt;b&gt;+ 节点：&lt;/b&gt;左侧拖拽到画布 | &lt;b&gt;删除：&lt;/b&gt;&lt;kbd&gt;Delete&lt;/kbd&gt; 或右键 | &lt;b&gt;配置：&lt;/b&gt;双击节点&lt;/p&gt;
        &lt;p&gt;&lt;b&gt;连线：&lt;/b&gt;拖拽节点边缘 &lt;span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#60a5fa;vertical-align:middle;margin:0 3px"&gt;&lt;/span&gt; 到另一个的对应圆点上&lt;/p&gt;
        &lt;p&gt;&lt;b&gt;缩放：&lt;/b&gt;&lt;kbd&gt;滚轮&lt;/kbd&gt; · &lt;kbd&gt;Alt+/-&lt;/kbd&gt; · &lt;kbd&gt;Alt+0&lt;/kbd&gt; 适应画布&lt;/p&gt;
        &lt;a-divider style="margin:10px 0;border-color:rgba(255,255,255,0.05)" /&gt;
        &lt;p style="font-size:.75rem;color:rgba(255,255,255,0.3)"&gt;✅ 自动检测死循环 · 重复连线 · 自连接&lt;/p&gt;
      &lt;/div&gt;
    &lt;/a-modal&gt;
    &lt;!-- AI 自动设计 --&gt;
    &lt;a-modal v-model:open="aiGenOpen" title="✨ AI 自动设计工作流" width="560px" :footer="null"&gt;
      &lt;a-form layout="vertical"&gt;
        &lt;a-form-item label="描述你的需求" extra="用自然语言描述你想要的工作流，AI 将自动生成节点和连线"&gt;
          &lt;a-textarea v-model:value="aiGenDesc" :rows="5" placeholder="例如：从 Webhook 接收文章链接 → 用 AI 提取关键信息 → 翻译成英文 → 验证字数 &gt; 100 → 通过后发送到 Slack，不通过返回重写"
            :disabled="aiGenLoading" /&gt;
        &lt;/a-form-item&gt;
        &lt;a-form-item label="可用技能（可选）"&gt;
          &lt;a-select v-model:value="aiGenSkills" mode="tags" placeholder="输入技能名后回车" :options="skillOpts" :disabled="aiGenLoading" style="width:100%" /&gt;
        &lt;/a-form-item&gt;
        &lt;div style="display:flex;gap:8px;margin-top:4px"&gt;
          &lt;a-button type="primary" @click="aiGenerate(false)" :loading="aiGenLoading" block&gt;
            &lt;template v-if="!aiGenLoading"&gt;🤖 生成预览&lt;/template&gt;
            &lt;template v-else&gt;生成中...&lt;/template&gt;
          &lt;/a-button&gt;
          &lt;a-button @click="aiGenerate(true)" :loading="aiGenSaving" :disabled="aiGenLoading" block&gt;
            💾 生成并保存
          &lt;/a-button&gt;
        &lt;/div&gt;
        &lt;div v-if="aiGenResult" style="margin-top:12px;padding:8px 12px;background:rgba(52,211,153,0.08);border-radius:8px;font-size:.78rem;color:#34d399"&gt;
          完成：{{ aiGenResult.node_count }} 个节点，{{ aiGenResult.edge_count }} 条连线
        &lt;/div&gt;
        &lt;div v-if="aiGenError" style="margin-top:12px;padding:8px 12px;background:rgba(239,68,68,0.08);border-radius:8px;font-size:.78rem;color:#ef4444"&gt;
          {{ aiGenError }}
        &lt;/div&gt;
      &lt;/a-form&gt;
    &lt;/a-modal&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
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
// ─── 表单字段 &amp; 通用类型 ───
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
const nodes = ref&lt;Node[]&gt;([])
const edges = ref&lt;Edge[]&gt;([])
const zoom = ref(1)
const selectedNode = ref&lt;string|null&gt;(null)
const currentWfId = ref('')
let viewportTimer: ReturnType&lt;typeof setTimeout&gt; | null = null
const wfName = ref('')
const wfOptions = ref&lt;{label:string;value:string}[]&gt;([])
const configOpen = ref(false)
const configNode = ref&lt;Node|null&gt;(null)
const configForm = reactive&lt;NodeConfig&gt;({
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
  model_capabilities?: Record&lt;string, string[]&gt;
}
const providerList = ref&lt;ProviderInfo[]&gt;([])
const agentOpts = ref&lt;{label:string;value:string}[]&gt;([])
const genTypes = ['gen-text','gen-code','gen-image','gen-video']
const providerOpts = computed(() =&gt; providerList.value.map((p)=&gt;({label:p.name,value:p.id})))
const genCapMap:Record&lt;string,string&gt; = { 'gen-text':'text','gen-code':'text','gen-image':'image_generate','gen-video':'video_generate' }
function genCapLabel(type:string):string {
  const capLabels: Record&lt;string,string&gt; = {text:'文本',image_generate:'图片生成',video_generate:'视频生成'}
  return capLabels[genCapMap[type]]||''
}
function genModelOpts(type:string):{label:string;value:string;disabled?:boolean}[] {
  const cap = genCapMap[type]||'text'; const pid = configForm.genProviderId||''
  const p = providerList.value.find(x=&gt;x.id===pid)
  if(!p?.models) return []
  return p.models.map((m)=&gt;{
    const name = typeof m==='string'?m:(m.name||m.model||'')
    const caps = typeof m==='string'?(p.model_capabilities||{})[name]||[]:(m.capabilities||m.caps||[])
    return {label:name,value:name,disabled:cap!=='text'&amp;&amp;caps.length&amp;&amp;!caps.includes(cap)?true:false}
  })
}
const llmModelOpts = computed(() =&gt; {
  const p = providerList.value.find(x=&gt;x.id===configForm.llmProviderId)
  if(!p?.models) return []
  return p.models.map((m)=&gt;({label:typeof m==='string'?m:(m.name||m.model||''),value:typeof m==='string'?m:(m.name||m.model||'')}))
})
function onGenPChange(id:string, type:string) {
  configForm.genProviderId = id
  configForm.genModel = ''
  const cap = genCapMap[type]||'text'
  const p = providerList.value.find(x=&gt;x.id===id)
  if(p?.models?.length) {
    const first = p.models.find((m)=&gt;{
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
const history = ref&lt;HistoryState[]&gt;([])
const canUndo = ref(false)
function pushHistory() { history.value.push({nodes:JSON.parse(JSON.stringify(nodes.value)),edges:JSON.parse(JSON.stringify(edges.value))}); canUndo.value=true; if(history.value.length&gt;50) history.value.shift() }
function undo() { if(!canUndo.value)return; const s=history.value.pop()!; nodes.value=s.nodes; edges.value=s.edges; canUndo.value=history.value.length&gt;0 }
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
  nodes.value=nodes.value.filter(n=&gt;n.id!==id)
  edges.value=edges.value.filter(e=&gt;e.source!==id&amp;&amp;e.target!==id)
  nodes.value=[...nodes.value];edges.value=[...edges.value]
  if(selectedNode.value===id)selectedNode.value=null
}
// ─── 节点渲染（Handle 连线） ───
interface WorkflowNodeProps {
  id: string
  data: { label?: string; color?: string; type?: string; icon?: string }
  type?: string
  selected?: boolean
  configure?: () =&gt; void
}
const WorkflowNode = (props: WorkflowNodeProps)=&gt;{
  const d=props.data||{},sel=props.selected
  const c=d.color||'#60a5fa'
  const isT=!!d.type?.startsWith('trigger'),isO=d.type==='output',isS=d.type==='switch',isM=d.type==='merge',isL=d.type==='loop',isF=d.type==='filter'
  const handleStyle = (bg:string) =&gt; ({background:bg,border:'2px solid '+bg,width:10,height:10})
  const children: ReturnType&lt;typeof h&gt;[]=[
    h('div',{class:'cn-header',style:`background:rgba(${c.slice(1).match(/.{2}/g)!.map(x=&gt;parseInt(x,16)).join(',')},0.12)`,ondblclick:()=&gt;props.configure?.()},[
      h('span',{class:'cn-icon'},d.icon||'◆'),
      h('span',{class:'cn-title'},d.label||props.typeName||''),
      h('span',{class:'cn-del',onClick:(e:MouseEvent)=&gt;{e.stopPropagation();removeNode(props.id)}},'✕'),
    ]),
  ]
  // input handle
  if(!isT&amp;&amp;!isM) children.push(h(Handle,{key:'hi',type:'target',position:Position.Left,id:'in',style:handleStyle(c)}))
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
    onContextmenu:(e:MouseEvent)=&gt;{e.preventDefault();removeNode(props.id)},
  },children)
}
const customNodeTypes:Record&lt;string, typeof WorkflowNode&gt; = { default: WorkflowNode }
// ─── 连线（验证） ───
function onConnect(cx:Connection){
  if(!cx.source||!cx.target)return
  if(cx.source===cx.target){message.error('不能连接自身');return}
  if(edges.value.some(e=&gt;e.source===cx.source&amp;&amp;e.target===cx.target&amp;&amp;e.sourceHandle===cx.sourceHandle)){message.warning('已存在');return}
  if(hasCycle(cx.source,cx.target)){message.error('死循环，已阻止');return}
  pushHistory()
  edges.value.push({id:`e_${cx.source}_${cx.sourceHandle||'out'}_${cx.target}`,source:cx.source,target:cx.target,sourceHandle:cx.sourceHandle||'out',targetHandle:cx.targetHandle||'in',type:'smoothstep',animated:true,style:{stroke:'rgba(150,180,210,0.5)',strokeWidth:1.5}})
  edges.value=[...edges.value]
}
function hasCycle(from:string,to:string):boolean{
  const adj=new Map&lt;string,string[]&gt;()
  for(const e of edges.value){if(!adj.has(e.source))adj.set(e.source,[]);adj.get(e.source)!.push(e.target)}
  if(!adj.has(from))adj.set(from,[]);adj.get(from)!.push(to)
  const vis=new Set&lt;string&gt;();const stack=[to]
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
    viewportTimer = setTimeout(()=&gt;{
      workflowAPI.updateViewport(currentWfId.value,{
        zoom: vp.zoom,
        offset_x: Math.round(vp.x),
        offset_y: Math.round(vp.y)
      }).catch(()=&gt;{})
    },500)
  }
}
function zoomIn(){vfRef.value?.zoomIn?.()}
function zoomOut(){vfRef.value?.zoomOut?.()}
function fitView(){vfRef.value?.fitView?.({padding:0.2})}
function openNodeConfig(nodeId:string){
  const n=nodes.value.find(x=&gt;x.id===nodeId);if(!n)return
  configNode.value=n
  const d=n.data||{}
  configForm.label=d.label||''
  ;['description','prompt','userTemplate','model','temperature','maxTokens','kbName','retrievalMode','topK','template','contextWindow','contextStrategy','genStyle','wordLimit','codeLang','codeSpec','imgStyle','imgRes','videoDuration','videoRes','videoFps','outFormat','srcLang','tgtLang','summaryMode','summaryWords','extractTarget','validateRule','failAction','reviewer','autoApprove','filterRule','filterPass','channel','targetAddr','storeType','storePath','memScope','memTopK','memType','memImportance','memTTL','memAgentId','taskDesc','assignee','skill','timeout','expression','gate','loopType','loopCount','loopVar','mergeMode','cron','webhookAuth','genProviderId','genModel','llmProviderId','inputDefault','inputSrc'].forEach(k=&gt;{(configForm as Record&lt;string, unknown&gt;)[k]=(d as Record&lt;string, unknown&gt;)[k]??(configForm as Record&lt;string, unknown&gt;)[k]})
  configOpen.value=true
}
function applyConfig(){
  if(!configNode.value)return;const n=nodes.value.find(x=&gt;x.id===configNode.value!.id);if(!n)return
  pushHistory();n.data={...n.data,...configForm};nodes.value=[...nodes.value];message.success('已应用')
}
// ─── CRUD ───
async function loadList(){try{const r=await workflowAPI.list();if(r?.success||r?.code===0){const wfs=r.data?.workflows||r.data||[];wfOptions.value=wfs.map((w:Record&lt;string,unknown&gt;)=&gt;({label:(w.name as string)||String(w.id),value:String(w.id)}))}}catch{}}
async function restoreViewport(id:string){
  try{
    const r=await workflowAPI.getViewport(id)
    if(r?.success||r?.code===0){
      const vp=r.data
      if(vp&amp;&amp;vfRef.value){
        vfRef.value.setViewport({x:vp.offset_x||0,y:vp.offset_y||0,zoom:vp.zoom||1})
      }
    }
  }catch{}
}
async function loadWorkflow(id:string){if(!id){nodes.value=[];edges.value=[];return};try{const r=await workflowAPI.get(id);if(r?.success||r?.code===0){const d=r.data;wfName.value=d?.name||'';nodes.value=(d?.nodes||[]).map((n:Record&lt;string,unknown&gt;)=&gt;({...n,data:(n as Node).data||{},width:180,height:64}));edges.value=(d?.edges||[]).map((e:Record&lt;string,unknown&gt;)=&gt;({...e,type:'smoothstep',animated:true,style:{stroke:'rgba(150,180,210,0.5)',strokeWidth:1.5}}));idC.v=nodes.value.length;nextTick(()=&gt;{fitView();restoreViewport(id)})}}catch{}}
async function createWf(){if(!wfName.value.trim()){message.warning('请输入名称');return};try{const r=await workflowAPI.create({name:wfName.value,nodes:[],edges:[]});if(r?.success||r?.code===0){message.success('已创建');currentWfId.value=r.data?.id||'';await loadList()}}catch(e:unknown){const err=e as {message?:string};message.error(err?.message||'失败')}}
async function saveWf(){if(!currentWfId.value){message.warning('请先新建或选择');return};try{await workflowAPI.update(currentWfId.value,{name:wfName.value,nodes:nodes.value.map(n=&gt;({id:n.id,type:n.type,position:n.position,data:n.data})),edges:edges.value.map(e=&gt;({id:e.id,source:e.source,target:e.target}))});message.success('已保存')}catch(e:unknown){const err=e as {message?:string};message.error(err?.message||'失败')}}
async function delWf(){if(!currentWfId.value)return;try{await workflowAPI.delete(currentWfId.value);message.success('已删除');currentWfId.value='';nodes.value=[];edges.value=[];await loadList()}catch(e:unknown){const err=e as {message?:string};message.error(err?.message||'失败')}}
// ─── AI 自动设计 ───
const aiGenOpen = ref(false)
const aiGenDesc = ref('')
const aiGenSkills = ref&lt;string[]&gt;([])
const aiGenLoading = ref(false)
const aiGenSaving = ref(false)
interface AIGenResult {
  nodes?: { type: string; label: string; color?: string; x?: number; y?: number }[]
  edges?: { source: string; target: string }[]
}
const aiGenResult = ref&lt;AIGenResult | null&gt;(null)
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
      genNodes = genNodes.map((n,i)=&gt;{
        if(!n.id) n.id = 'ai_'+i
        if(!n.type) n.type = n.node_type||'task'
        if(!n.position) n.position = n.position||n.pos||{x:300,y:100+i*120}
        if(!n.data) n.data = {label:(n.name||n.label||n.title||n.type),color:'#a78bfa',type:n.type}
        n.width=180;n.height=64
        return n
      })
      genEdges = genEdges.map((e,i)=&gt;{
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
      nextTick(()=&gt;fitView())
    }else{aiGenError.value=r?.message||'生成失败'}
  }catch(e:unknown){const err=e as {response?:{data?:{message?:string}};message?:string};aiGenError.value=err?.response?.data?.message||err?.message||'AI 生成失败，请检查后端 LLM 配置'}
  finally{aiGenLoading.value=false;aiGenSaving.value=false}
}
onMounted(async ()=&gt;{
  loadList()
  // 加载已联通服务商列表
  try{const {providerAPI}=await import('@/api/modules/providers');const pr=await providerAPI.list();if(pr?.success||pr?.code===0){providerList.value=(pr.data?.providers||[]).filter((p:Record&lt;string,unknown&gt;)=&gt;(p.has_api_key as boolean)&amp;&amp;p.enabled!==false)}}catch{}
  // 加载 Agent 列表
  try{const {request}=await import('@/api');const r=await request.get('/agents');if(r?.code===0){agentOpts.value=(r.data?.agents||[]).map((a:Record&lt;string,unknown&gt;)=&gt;({label:(a.name as string)||String(a.agent_id||a.id),value:String(a.agent_id||a.id)}))}}catch{}
})
const onKD=(e:KeyboardEvent)=&gt;{
  if(e.altKey&amp;&amp;e.key==='='){e.preventDefault();zoomIn()}else if(e.altKey&amp;&amp;e.key==='-'){e.preventDefault();zoomOut()}else if(e.altKey&amp;&amp;e.key==='0'){e.preventDefault();fitView()}else if((e.ctrlKey||e.metaKey)&amp;&amp;e.key==='z'){e.preventDefault();undo()}
}
onMounted(()=&gt;window.addEventListener('keydown',onKD))
&lt;/script&gt;
&lt;style scoped&gt;
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
&lt;/style&gt;
&nbsp;
/**
 * 聊天步骤化时间轴（2026-09-07 三需求 ②）。
 *
 * 把助手消息的推理/工具/正文按 SSE 到达顺序重组为 steps 时间轴：
 * - reasoning 与 tool 各自成段，段落结束即封口（后续同类事件开新段）——
 *   治"推理全部集中在前、正文另起"的旧渲染；
 * - 每段独立 open 态（治 msg.toolOpen/msg.reasoningOpen 消息级单开关
 *   "一开全开、一折全折"）；
 * - 流式期间当前活动段展开、结束时自动收起（open=true→false 翻转一次），
 *   用户随时可单独点开。
 *
 * 纯函数 + 数据契约，供 ChatPage / useChat 历史合成 / 单测共用。
 */

export type ChatStepKind = 'reasoning' | 'tool'

export interface ChatStep {
  /** 稳定 key（v-for :key 用，段序号即可——steps 只追加不重排） */
  id: string
  kind: ChatStepKind
  /** 推理段落聚合文本 */
  text?: string
  /** 工具段字段 */
  name?: string
  arguments?: string
  result?: string
  /** B3：模型自述的执行摘要（active 起、complete 收），时间轴标题优先用它 */
  taskName?: string
  /** 独立折叠态：流式中活动段为 true，封口时翻 false（用户手动展开后不再自动收） */
  open: boolean
  /** 流式中该段仍在增长（扫光/进行中标记） */
  active?: boolean
  /** 段落封口时刻（"持续了几秒"展示用） */
  startedAt?: number
  endedAt?: number
}

/**
 * 追加一段推理文本到 steps 尾部。
 * - 尾段是活跃 reasoning 段 → 续写；
 * - 否则（无段/尾段是工具/推理段已封口）→ 开新段。
 *   规则"推理段一旦被工具打断即封口"产生图示的 思考→工具→思考→工具 交替轴。
 */
export function appendReasoningStep(steps: ChatStep[], text: string): ChatStep[] {
  if (!text) return steps
  const last = steps[steps.length - 1]
  if (last && last.kind === 'reasoning' && last.active) {
    last.text = (last.text || '') + text
    return steps
  }
  if (last) finishStep(last)
  steps.push({
    id: `s${steps.length}-${Date.now().toString(36)}`,
    kind: 'reasoning',
    text,
    open: true,
    active: true,
    startedAt: Date.now(),
  })
  return steps
}

/**
 * 追加一个工具调用段。
 * 任何未封口的尾段（推理段）先封口；工具段保持活跃至 tool_result 到达。
 * taskName：模型自述的进行中短语（B3，可选）——时间轴标题优先显示。
 */
export function appendToolStep(steps: ChatStep[], name: string, args: string, taskName?: string): ChatStep[] {
  const last = steps[steps.length - 1]
  if (last) finishStep(last)
  steps.push({
    id: `s${steps.length}-${Date.now().toString(36)}`,
    kind: 'tool',
    name,
    arguments: args,
    taskName: taskName || undefined,
    open: true,
    active: true,
    startedAt: Date.now(),
  })
  return steps
}

/** 给尾部的活跃工具段落结果（tool_result 语义：只落在最近一个活跃工具段）。 */
export function attachToolResult(steps: ChatStep[], result: string, taskName?: string): ChatStep[] {
  for (let i = steps.length - 1; i >= 0; i--) {
    const s = steps[i]
    if (s.kind === 'tool' && s.active) {
      s.result = result
      // v0 语义：完成态短语替换进行中短语（标题随生命周期迁移到 complete 态）；
      // active 文案仅作 complete 缺失时的兜底
      if (taskName) s.taskName = taskName
      finishStep(s)
      return steps
    }
    // 越过已封口段继续向前找（tool_result 可能迟到）
    if (s.kind === 'tool' && !s.result) {
      s.result = result
      if (taskName) s.taskName = taskName
      return steps
    }
  }
  return steps
}

/** 封口：active 翻 false；open 若未被用户手动改过则自动收起。 */
export function finishStep(step: ChatStep): void {
  if (!step.active) return
  step.active = false
  step.endedAt = Date.now()
  // 自动折叠：仅当段仍处于"流式默认展开"态；用户手动收起/展开过的不动
  if (step.open) step.open = false
}

/** 正文首个 chunk 到达：封口一切仍活跃的段（推理段收尾）。 */
export function finishAllSteps(steps: ChatStep[]): void {
  for (const s of steps) finishStep(s)
}

/** 用户手动切换折叠态（此后 finishStep 不再动该段——open 已脱离默认值语义）。 */
export function toggleStep(steps: ChatStep[], stepId: string): void {
  const s = steps.find((x) => x.id === stepId)
  if (s) s.open = !s.open
}

/**
 * 从历史消息（后端落盘形状）合成 steps。
 *
 * 历史只有" reasoning 全文 + toolCalls 数组"两路数据，无顺序信息；
 * 合成规则：reasoning 段在前（若非空），随后每个 toolCall 一段（有 result
 * 即已完成）。全部折叠（历史默认收起，点开可看）。
 */
export function buildStepsFromHistory(
  reasoning: string | undefined,
  toolCalls: Array<{ name: string; arguments: string; result?: string; taskName?: string }> | undefined,
): ChatStep[] {
  const steps: ChatStep[] = []
  if (reasoning) {
    steps.push({
      id: 'h-reasoning',
      kind: 'reasoning',
      text: reasoning,
      open: false,
      active: false,
    })
  }
  for (const tc of toolCalls || []) {
    steps.push({
      id: `h-tool-${steps.length}`,
      kind: 'tool',
      name: tc.name,
      arguments: tc.arguments,
      result: tc.result,
      taskName: tc.taskName,
      open: false,
      active: false,
    })
  }
  return steps
}

/**
 * 流式状态派生（三需求 ①）。
 *
 * SSE 无阶段事件，状态由消息数据形状派生：
 * - received 但正文为空、无任何步骤 → 「理解中」（消息已收到，理解输入）
 * - 活跃推理段 → 「思考中」
 * - 活跃工具段 → 「执行中」（命令/工具）
 * - 正文开始输出 → 「输出中」
 */
export type StreamPhase = 'understanding' | 'thinking' | 'tool' | 'output'

export function deriveStreamPhase(msg: {
  content?: string
  steps?: ChatStep[]
  streaming?: boolean
}): StreamPhase {
  if (msg.content) return 'output'
  const steps = msg.steps || []
  for (let i = steps.length - 1; i >= 0; i--) {
    const s = steps[i]
    if (!s.active) continue
    return s.kind === 'reasoning' ? 'thinking' : 'tool'
  }
  return 'understanding'
}

/**
 * channel-agent-context: agent 选择器选项的唯一组装点。
 *
 * ## 为什么要有这个文件（2026-09-28 缺陷取证）
 *
 * `stores/agents.ts` 的 `agentOptions` 元素契约是 `{label, value, isWorkflow}`。
 * 渠道两页曾各自写成 `o.id / o.name` —— 两个键名在契约里都不存在，于是：
 *
 * 1. `a-select` 收到一串 `value: undefined`：渲染成**无文字空白行**（用户「看不到智能体」）；
 * 2. 选中它 → `agentId = undefined`；
 * 3. `channel-configs.ts` 的 `agentId ? {agent_id} : {}` 因此**不发参数**；
 * 4. 后端 `Query(default="default")` 把它兜成 `default` ——
 *    用户以为在给 `凯蒂` 配飞书，配置实际写进了 `default` 的表，且无任何提示。
 *
 * 第 3、4 步是最坏的一面：错键名不只是「看不见」，而是「写错地方」。
 * 同一份契约在仓内已有 3 处正确消费方（AgentSchedulerPage / CollaborationPage /
 * CanvasDesignerPage），只有渠道两页各写了一份错映射 —— 故按 AGENTS.md 第 6 条
 * 收口到**一处**，两页共用，禁止第三份写法。
 *
 * ## 契约
 *
 * 输入是 store 的 `agentOptions`（生产端的形状，不得在此改写生产契约——
 * 它已被 3 处正确消费方依赖）；输出恒为 `{value, label}` 的 antdv 选项形状。
 * `isWorkflow` 透传供需要区分展示的调用方读取。
 */

/** store `agentOptions` 的元素形状（与 `stores/agents.ts` 同源，不在此另立一套）。 */
export interface AgentOptionSource {
  label?: string
  value?: string
  isWorkflow?: boolean
  /** 历史宽松入参：个别调用方曾直接传 Agent 对象。 */
  id?: string
  name?: string
}

/** 选择器选项：`value` 恒为真 agent 身份，`label` 恒为可读名字。 */
export interface AgentSelectOption {
  value: string
  label: string
  isWorkflow: boolean
}

/**
 * 把 store 的 `agentOptions` 归一成 `a-select` 选项。
 *
 * 缺 `value`（即身份）的条目**整条丢弃**：一条没有身份的选项落进选择器，
 * 唯一后果就是让用户误选并静默写错配置 —— 宁可少一项，也不要一个假项。
 */
export function buildAgentSelectOptions(
  sources: readonly AgentOptionSource[] | null | undefined,
): AgentSelectOption[] {
  const options: AgentSelectOption[] = []
  for (const source of sources ?? []) {
    const value = source?.value ?? source?.id
    if (!value) continue
    options.push({
      value: String(value),
      label: source?.label ?? source?.name ?? String(value),
      isWorkflow: !!source?.isWorkflow,
    })
  }
  return options
}

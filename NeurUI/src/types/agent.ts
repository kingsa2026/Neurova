import type { Team } from '@/api/modules/teams'

export interface Agent {
  id: string
  name: string
  description?: string
  model?: string
  provider?: string
  status: 'active' | 'inactive' | 'sleeping' | 'error'
  avatar?: string
  /** 人设提示词（后端 agent_config.json 的 system_prompt） */
  system_prompt?: string
  /** Agent 角色（如 assistant/researcher，用于蜂群派生时挑选执行者） */
  role?: string
  /** 所属分组（后端 group_id；编辑态回显用，缺省串 = 未绑定） */
  group_id?: string
  /** 性格设定（后端 AgentConfig.personality，表单编辑态回显） */
  personality?: string
  /** 行为准则/宪法（后端 AgentConfig.constitution，表单编辑态回显） */
  constitution?: string
  /** 执行档位回显（lite/standard/heavy；null=未设置跟随部署档位） */
  exec_profile?: string | null
  createdAt: string
  updatedAt: string
  config?: AgentConfig
  stats?: AgentStats
}

export interface AgentConfig {
  systemPrompt?: string
  temperature?: number
  maxTokens?: number
  topP?: number
  ttsEnabled?: boolean
  ttsVoice?: string
  ttsSpeed?: number
  ttsPitch?: number
  tools?: string[]
  skills?: string[]
}

export interface AgentStats {
  totalConversations: number
  totalMessages: number
  totalTokens: number
  avgResponseTime: number
  lastActiveAt?: string
}

// ---------------------------------------------------------------------------
// ACP 外部编码代理（设计文档 docs/04-plans/2026-11-19-acp-coding-agent-team-integration-plan.md §4.1/§4.7/§5）
// ---------------------------------------------------------------------------

/** 外部编码代理执行体配置（与后端 NeuacpExecutorSpec 对齐；凭据只落键名不落值） */
export interface NeuacpExecutorSpec {
  /** 执行体类型：acp（原生/适配器）| plugin（headless CLI 行协议插件） */
  kind: 'acp' | 'plugin'
  /** 工具目录标识（catalog） */
  tool: string
  /** stdio（本地子进程）| ssh（远程隧道跑 stdio） */
  transport: 'stdio' | 'ssh'
  /** 完整启动命令 argv */
  command: string[]
  /** 外部代理工作目录（编码任务目标仓库根，必填） */
  cwd: string
  /** 需注入子进程的凭据键名清单（键值运行时经凭据面按租户+成员取） */
  env_keys: string[]
  /** chain（审批链，默认）| auto（仅 L0，admin 专属） */
  permission_mode: 'chain' | 'auto'
  /** transport=ssh 时的连接参数（key_ref 指向凭据面，不落明文） */
  remote?: { host?: string; port?: number; user?: string; key_ref?: string } | null
}

/** 目录项能力声明（F1：per-runtime 支持面；缺省字段前端按保守档回退全开） */
export interface NeuacpCapabilitySet {
  /** 支持的传输形态（stdio/ssh） */
  transports?: string[]
  /** 支持的审批交互形态（chain/auto） */
  permission_modes?: string[]
  /** 事件流是否流式 */
  streaming?: boolean
  /** 是否支持跨进程续跑 */
  resume?: boolean
  /** 是否支持进程/会话复用 */
  session_reuse?: boolean
}

/** GET /external-agents/catalog 单条目录项 */
export interface NeuacpCatalogItem {
  tool: string
  /** 是否在已知目录中（registry 收录） */
  known: boolean
  kind: 'acp' | 'plugin'
  /** 目录来源（builtin / registry 等） */
  origin?: string
  /** 默认启动命令（名册可覆盖） */
  command: string[]
  /** 适配器经 npx 拉包时需要 Node 运行时 */
  requires_node?: boolean
  /** 目录项是否停用（如暂不接入的工具） */
  disabled?: boolean
  /** 本机命令探测结果（启用连接时实时检查） */
  installed?: boolean
  /** 未安装时的安装指引 */
  install_hint?: string
  /** 能力声明（打开前拒绝的契约面；缺省=旧目录，前端按保守档全开） */
  capabilities?: NeuacpCapabilitySet
}

/** POST /external-agents/test 握手结果 */
export interface NeuacpTestResult {
  ok: boolean
  protocolVersion?: string
  serverCapabilities?: Record<string, unknown>
  error?: string
}

/** GET /external-agents/runs/{id}/frames 单条一手帧记录（F2 帧账本读面） */
export interface NeuacpFrameRecord {
  /** 流内单调序号（游标回放锚点） */
  seq: number
  subagent_id: string
  /** in=runtime 原话 / out=本仓请求（含 cancel）/ observed=进程退出等观测事实 */
  direction: 'in' | 'out' | 'observed' | string
  /** 原生帧（凭据已脱敏） */
  frame: Record<string, unknown>
  /** 谱系（tenant/team/agentPath/depth/trace） */
  lineage?: Record<string, unknown>
  occurred_at: string
}

/** frames 读面响应（count=本页条数；游标翻页用末条 seq 作 after_seq） */
export interface NeuacpFramesPage {
  subagent_id: string
  count: number
  frames: NeuacpFrameRecord[]
}

/** GET /external-agents/status 进程池状态（M6：真实水位；进程行字段后端自由扩展，前端按需展示） */
export interface NeuacpStatusInfo {
  processes: Array<Record<string, unknown>>
  /** 存活进程数（空闲 + 在用）——状态卡主读数 */
  live?: number
  /** 在用（非空闲）进程数 */
  busy?: number
  /** 空闲驻留进程数 */
  idle?: number
  /** 排队等待取件的派活数 */
  waiters?: number
  /** 近端崩溃累计计数 */
  crashes?: number
  /** 全局进程上限 */
  max_procs?: number
  /** 空闲回收阈值（秒） */
  idle_seconds?: number
  /** 池是否已关闭 */
  closed?: boolean
  note?: string
}

/** 团队名册成员明细（后端 TeamInfo.members_detail 单条，A5 起 executor 可选） */
export interface TeamMemberDetail {
  user_id: string
  name: string
  role: string
  prompt?: string
  joined_at?: number
  /** 外部编码代理执行体标记；缺省 = 内置成员 */
  executor?: NeuacpExecutorSpec
}

/** POST /teams/{id}/members 请求体（在 teams.ts {members, prompt} 契约上扩 A5 字段） */
export interface TeamMemberAddBody {
  members: string[]
  prompt?: string
  /** 成员角色（coder/reviewer/member，沿蜂群角色语义） */
  role?: string
  /** 外部编码代理执行体（仅 admin） */
  executor?: NeuacpExecutorSpec
}

export interface ApiResponse<T = unknown> {
  code: number
  success: boolean
  message: string
  data: T
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  pageSize: number
}

/** 团队信息（teams.ts Team 基础上补 A5 新增字段；teams.ts 本卡不改，扩展类型收口在本文件） */
export interface TeamWithDetail extends Team {
  /** 名册成员明细（后端 A5 起返回；缺省时回退 members 字符串数组渲染） */
  members_detail?: TeamMemberDetail[]
  /** 团队归属租户（部门根，缺省 default） */
  tenant_id?: string
}

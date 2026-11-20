/**
 * ACP 外部编码代理管理面 API（设计文档 docs/04-plans/2026-11-19-acp-coding-agent-team-integration-plan.md §4.7/§4.1）
 *
 * 端点（均挂 /api/v1，admin 门由后端 requireAdmin 承担）：
 * - GET    /external-agents/catalog        工具目录（内置预设 ∪ registry 缓存 ∪ 本机命令探测）
 * - POST   /external-agents/test           握手级连通测试（body = executor 配置）
 * - GET    /external-agents/status         进程池状态（存活进程/近端崩溃计数）
 * - DELETE /teams/{id}/members/{member_id} 名册移除成员（复用 teams 端点，A5）
 */
import api from '@/api'
import type {
  NeuacpCatalogItem,
  NeuacpExecutorSpec,
  NeuacpFramesPage,
  NeuacpStatusInfo,
  NeuacpTestResult,
} from '@/types/agent'

const BASE = '/external-agents'

/** 拉取外部编码代理工具目录（含本机 installed 探测与 install_hint）。 */
export function fetchNeuacpCatalog() {
  return api.get<NeuacpCatalogItem[]>(`${BASE}/catalog`)
}

/** 对给定 executor 配置做一次握手级连通测试（initialize 往返）。 */
export function testNeuacpConnection(executor: NeuacpExecutorSpec) {
  return api.post<NeuacpTestResult>(`${BASE}/test`, executor)
}

/** 拉取外部代理进程池状态。 */
export function fetchNeuacpStatus() {
  return api.get<NeuacpStatusInfo>(`${BASE}/status`)
}

/**
 * 回放外部编码代理的一手帧流（F2 帧账本读面；admin 门+同租户由后端承担）。
 * after_seq 游标：传上一页末条 seq 翻页；limit 服务端夹取 [1,1000]。
 */
export function fetchNeuacpRunFrames(subagentId: string, afterSeq = 0, limit = 200) {
  const params = new URLSearchParams({
    after_seq: String(afterSeq),
    limit: String(limit),
  })
  return api.get<NeuacpFramesPage>(
    `${BASE}/runs/${encodeURIComponent(subagentId)}/frames?${params.toString()}`,
  )
}

/** 从团队名册移除成员（内置/外部成员通用；后端 A5 同租户+属主/admin 门）。 */
export function removeTeamMember(teamId: string, memberId: string) {
  return api.delete<null>(`/teams/${teamId}/members/${encodeURIComponent(memberId)}`)
}

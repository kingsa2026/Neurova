/**
 * useAgentPage — agentId 来源解析优先级纯函数测试。
 *
 * 根因（从智能体管理点"对话"进入默认智能体会话）:
 *   AgentListPage 点击对话跳 /agent/:agentId/chat, router 把该路由
 *   redirect 到 /chat 且不保留 agentId; useAgentPage 只读 route.params,
 *   agentId 回落 agentStore.currentAgentId(默认智能体)——用户选择丢失。
 *
 * 契约（resolveAgentId）:
 *   1. params.agentId 优先级最高（agent-scoped 页面既有行为不变）;
 *   2. query.agentId 次之（/chat?agentId=x 重定向入口）;
 *   3. store currentAgentId 兜底（普通 /chat 入口）;
 *   4. 空串/缺省一律按下一级回退, 不产生 falsy agentId。
 */
import { describe, expect, it } from 'vitest'
import { resolveAgentId } from '../useAgentPage'

describe('resolveAgentId', () => {
  it('params 优先于 query 与 store 兜底', () => {
    expect(
      resolveAgentId({ agentId: 'agent-b' }, { agentId: 'agent-c' }, 'fallback'),
    ).toBe('agent-b')
  })

  it('无 params 时 query 生效（/agent/:id/chat 重定向 /chat?agentId=id 场景）', () => {
    expect(
      resolveAgentId(undefined, { agentId: 'agent-kai' }, 'default-1'),
    ).toBe('agent-kai')
  })

  it('params/query 均缺失时回退 store currentAgentId（普通 /chat 入口）', () => {
    expect(
      resolveAgentId(undefined, undefined, 'default-1'),
    ).toBe('default-1')
  })

  it('空串 key 视为缺失, 按下一级回退', () => {
    expect(
      resolveAgentId({ agentId: '' }, { agentId: 'agent-kai' }, 'fallback'),
    ).toBe('agent-kai')
    expect(resolveAgentId({ agentId: '' }, { agentId: '' }, 'fallback')).toBe('fallback')
  })

  it('query 数组形态取首个（vue-router 重复参数）', () => {
    expect(
      resolveAgentId(undefined, { agentId: ['agent-a', 'agent-b'] }, 'fallback'),
    ).toBe('agent-a')
  })

  it('全缺省时返回空串（调用方按空处理）', () => {
    expect(resolveAgentId(undefined, undefined, '')).toBe('')
  })
})

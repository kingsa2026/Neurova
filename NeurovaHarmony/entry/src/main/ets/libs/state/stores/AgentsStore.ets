/**
 * AgentsStore - Agent 列表与当前 Agent 状态
 */
import { StateManager } from '../StateManager';
import { EventBus } from '../bus/EventBus';
import { Agent } from '../../types';

const KEY_AGENTS = 'agents:list';
const KEY_CURRENT_AGENT_ID = 'agents:current_id';

export class AgentsStore {
  private state: StateManager = StateManager.getInstance();
  private bus: EventBus = EventBus.getInstance();

  get agents(): Agent[] {
    return this.state.get<Agent[]>(KEY_AGENTS, []);
  }

  setAgents(agents: Agent[]): void {
    this.state.set(KEY_AGENTS, agents);
  }

  get currentAgentId(): string {
    return this.state.get<string>(KEY_CURRENT_AGENT_ID, '');
  }

  get currentAgent(): Agent | undefined {
    const id = this.currentAgentId;
    if (!id) return undefined;
    return this.agents.find(a => a.id === id);
  }

  /** 切换当前 Agent，触发事件 */
  switchAgent(agentId: string): void {
    const agent = this.agents.find(a => a.id === agentId);
    if (!agent) return;
    this.state.set(KEY_CURRENT_AGENT_ID, agentId);
    this.bus.emit('agent:switched', { agentId, agent });
  }
}
